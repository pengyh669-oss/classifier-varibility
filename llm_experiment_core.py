from __future__ import annotations

import argparse
import base64
import mimetypes
import os
import random
import re
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from openai import OpenAI


DATA_FILES = {
    "result_data": "result_data.xlsx",
    "result_data_special": "result_data_special.xlsx",
    "result_data_free": "result_data_free.xlsx",
    "result_data_downWord": "result_data_downWord.xlsx",
    "result_data_upWord": "result_data_upWord.xlsx",
    "result_data_normalWord": "result_data_normalWord.xlsx",
}

DEFAULT_BASE_URL = "https://api.zhizengzeng.com/v1"
DEFAULT_MODEL = "glm-4.6v"
DEFAULT_SEED = 20260406
DEFAULT_REQUEST_TIMEOUT_SECONDS = 90.0
DEFAULT_REQUEST_RETRIES = 2
IMAGE_BASE_DIR = Path("image")
IMAGE_SUB_DIRS = {
    "result_data": "normal",
    "result_data_special": "special",
    "result_data_free": "free",
    "result_data_downWord": "downword",
    "result_data_upWord": "upword",
    "result_data_normalWord": "middle",
}
MIN_LOCAL_IMAGE_SIZE_BYTES = 1024
_IMAGE_DATA_URL_CACHE: dict[str, str] = {}
COMMON_CLASSIFIERS = (
    "个",
    "只",
    "位",
    "名",
    "辆",
    "架",
    "艘",
    "株",
    "棵",
    "朵",
    "件",
    "张",
    "条",
    "把",
    "间",
    "座",
    "家",
    "台",
    "本",
    "匹",
    "头",
    "双",
    "片",
    "块",
    "瓶",
    "杯",
    "碗",
    "盒",
    "支",
    "根",
    "顶",
    "扇",
    "面",
    "封",
    "幅",
    "颗",
    "粒",
    "盏",
)
_CLASSIFIER_ALT = "|".join(sorted(COMMON_CLASSIFIERS, key=len, reverse=True))
GENERIC_PROMPT_SUFFIXES = (
    "动物",
    "植物",
    "载具",
    "家具",
    "衣服",
    "建筑",
    "食物",
)
_NUMERAL_PATTERN = r"(?:一|两|二|三|四|五|六|七|八|九|十)"
_NOISE_PREFIX_PATTERN = re.compile(
    r"^(?:答案(?:是|为)?|回答(?:是|为)?|填空(?:是|为)?|可填(?:是|为)?|应填(?:是|为)?|应该填(?:是|为)?|"
    r"图中(?:是|为)?|图片中(?:是|为)?|红框中(?:是|为)?|目标是|应为|是)\s*[:：]?\s*"
)


@dataclass
class Question:
    unique_key: str
    source_file: str
    vg_object_id: str
    prompt: str
    image_url: str
    image_local_path: Path | None = None
    bbox_xywh: str = ""

    def pseudo_filename(self, run_label: str, index: int) -> str:
        return f"LLM_{run_label}_{self.source_file}_{self.vg_object_id}_{index:03d}.wav"


def build_common_arg_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Random seed for reproducible shuffle (default: {DEFAULT_SEED}).",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model name for chat.completions (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"OpenAI-compatible API base URL (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument(
        "--output-dir",
        default="translation/LLM_answer",
        help="Output folder for generated txt files.",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        help=(
            "Per-request timeout in seconds for model API calls "
            f"(default: {DEFAULT_REQUEST_TIMEOUT_SECONDS})."
        ),
    )
    parser.add_argument(
        "--request-retries",
        type=int,
        default=DEFAULT_REQUEST_RETRIES,
        help=(
            "Retry count on failed request (default: "
            f"{DEFAULT_REQUEST_RETRIES}). Set 0 for fail-fast."
        ),
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Resume from existing output file if present (default: True). "
            "Use --no-resume to restart from scratch."
        ),
    )
    return parser


def resolve_data_file(filename: str) -> Path:
    candidates = [Path(filename), Path("数据源") / filename]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    matches = list(Path(".").rglob(filename))
    if matches:
        return matches[0]

    raise FileNotFoundError(f"Data file not found: {filename}")


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def build_local_image_path(
    image_url: str,
    source_file: str,
    vg_object_id: str,
) -> Path | None:
    if not image_url:
        return None

    parsed_url = urllib.parse.urlparse(image_url)
    filename = os.path.basename(parsed_url.path)
    if not filename:
        return None

    file_stem, file_ext = os.path.splitext(filename)
    if not file_ext:
        file_ext = ".jpg"

    safe_source = source_file.replace("result_data_", "").replace("result_data", "")
    local_filename = f"{safe_source}_{vg_object_id}_{file_stem}{file_ext}"
    local_filename = re.sub(r'[<>:"/\\|?*]', "_", local_filename)

    sub_dir = IMAGE_SUB_DIRS.get(source_file, "other")
    return IMAGE_BASE_DIR / sub_dir / local_filename


def encode_local_image_as_data_url(image_path: Path) -> str:
    cache_key = str(image_path.resolve())
    cached = _IMAGE_DATA_URL_CACHE.get(cache_key)
    if cached:
        return cached

    if not image_path.exists():
        raise FileNotFoundError(f"Local image not found: {image_path}")
    if image_path.stat().st_size < MIN_LOCAL_IMAGE_SIZE_BYTES:
        raise ValueError(f"Local image too small: {image_path}")

    mime_type, _ = mimetypes.guess_type(str(image_path))
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/png"

    payload = base64.b64encode(image_path.read_bytes()).decode("ascii")
    data_url = f"data:{mime_type};base64,{payload}"
    _IMAGE_DATA_URL_CACHE[cache_key] = data_url
    return data_url


def load_question_pool() -> list[Question]:
    questions: list[Question] = []

    for source_key, file_name in DATA_FILES.items():
        file_path = resolve_data_file(file_name)
        df = pd.read_excel(file_path)

        for row_index, row in df.iterrows():
            prompt = _safe_str(row.get("prompt", ""))
            image_url = _safe_str(row.get("link_mn", ""))
            vg_object_id = _safe_str(row.get("vg_object_id", ""))
            bbox_xywh = _safe_str(row.get("bbox_xywh", ""))

            if not prompt:
                continue

            unique_key = f"{source_key}_{vg_object_id}_{row_index}"
            questions.append(
                Question(
                    unique_key=unique_key,
                    source_file=source_key,
                    vg_object_id=vg_object_id or str(row_index),
                    prompt=prompt,
                    image_url=image_url,
                    image_local_path=build_local_image_path(
                        image_url=image_url,
                        source_file=source_key,
                        vg_object_id=vg_object_id or str(row_index),
                    ),
                    bbox_xywh=bbox_xywh,
                )
            )

    return questions


def select_questions(total_count: int, seed: int, pool: list[Question]) -> list[Question]:
    if len(pool) < total_count:
        raise ValueError(
            f"Question pool too small: need {total_count}, got {len(pool)}."
        )
    rng = random.Random(seed)
    shuffled = pool.copy()
    rng.shuffle(shuffled)
    return shuffled[:total_count]


def build_client(base_url: str, request_timeout: float) -> OpenAI:
    _load_dotenv_if_needed()
    api_key = os.getenv("API_KEY", "").strip()
    if not api_key:
        raise ValueError("Environment variable API_KEY is required.")
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=request_timeout,
        max_retries=0,
    )


def _load_dotenv_if_needed(env_path: str = ".env") -> None:
    if os.getenv("API_KEY", "").strip():
        return

    path = Path(env_path)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key == "API_KEY" and key not in os.environ:
            os.environ[key] = value


def extract_message_text(response: Any) -> str:
    try:
        choice = response.choices[0]
        message = choice.message
        content = getattr(message, "content", "")
    except Exception:  # noqa: BLE001
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    chunks.append(str(text))
            else:
                text = getattr(item, "text", None)
                if text:
                    chunks.append(str(text))
        return "".join(chunks)

    return ""


def call_llm_once(
    client: OpenAI,
    model: str,
    question: Question,
    request_timeout: float,
) -> str:
    system_prompt = "\n".join(
        [
            "你将看到一张图片和一个带下划线的句子。请根据图片中红框圈出的目标补全句子，并输出补全后的完整句子。",
            "",
            "任务：",
            "根据图片中红框圈出的目标，补全带下划线的句子，并输出补全后的完整句子。",
            "",
            "观察范围：",
            "只关注红框内的目标；红框外的内容一律忽略，不要被背景或其他物体干扰。",
            "",
            "补全原则：",
            "1. 只根据红框内目标判断下划线应填内容。",
            "2. 如果原句已经包含数量词、量词或名词，补全内容中不要重复这些成分。",
            "",
            "输出要求：",
            "1. 只输出补全后的完整句子。",
            "2. 不要解释，不要分析，不要输出多余文字。",    
        ]
    )
    user_lines = [
        f"待补全句子：{question.prompt}",
        "",
        "请先判断原句已经给出的成分，再补全下划线。",
        "补全规则：",
        "1. 只有当句式为“这是一___。”时，才补“量词+名词”。",
        "2. 若句式类似于“这是一____动物/植物/载具/家具/衣服/建筑/食物。”，下划线只补量词，不补名词。",
        "3. 若句式类似于“这是一个/只/头____。”，下划线不补量词，只补名词。",
        "4. 最终答案必须是补全后的完整句子，而不是只输出下划线部分。",
    ]
    if question.bbox_xywh:
        user_lines.append(f"红框坐标（x,y,w,h）：{question.bbox_xywh}")
    user_text = "\n".join(user_lines)

    if not question.image_local_path:
        raise ValueError(
            f"local_image_missing: no local path for {question.source_file}/{question.vg_object_id}"
        )

    image_data_url = encode_local_image_as_data_url(question.image_local_path)
    user_content: list[dict[str, Any]] = [
        {"type": "text", "text": user_text},
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ]

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
        timeout=request_timeout,
    )
    text = extract_message_text(response)
    return text.strip()

def call_llm_with_retries(
    client: OpenAI,
    model: str,
    question: Question,
    retries: int = 2,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> tuple[str, str | None]:
    last_error: str | None = None
    for attempt in range(retries + 1):
        try:
            text = call_llm_once(
                client,
                model,
                question,
                request_timeout=request_timeout,
            )
            if text:
                return text, None
            else:
                last_error = "empty_response"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)

        if attempt < retries:
            time.sleep(1.0 * (attempt + 1))
    return "", last_error


def preflight_model_connection(
    client: OpenAI, model: str, request_timeout: float
) -> tuple[bool, str | None]:
    """Run a tiny request before experiment to validate model connectivity."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a connection check assistant."},
                {"role": "user", "content": "Reply with OK only."},
            ],
            temperature=0,
            max_tokens=64,
            timeout=request_timeout,
        )
        # For some providers/models, content can be empty while reasoning_content exists.
        # Any successful structured response here is enough to prove connectivity.
        choice = response.choices[0] if getattr(response, "choices", None) else None
        message = getattr(choice, "message", None)
        text = extract_message_text(response).strip()
        reasoning = getattr(message, "reasoning_content", None) if message else None
        if text or reasoning is not None:
            return True, None
        return False, "empty_response"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def first_sentence_unit(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return ""

    normalized = re.sub(r"^(答案|回答|填空|输出)[:：\s]*", "", normalized)
    match = re.search(r"[。！？!?]", normalized)
    if match:
        normalized = normalized[: match.start()]

    return normalized.strip(" 。，！？!?\"'“”‘’（）()[]【】")


def detect_tail_classifier(prefix: str) -> str:
    text = prefix.strip()
    if not text:
        return ""
    match = re.search(
        rf"(?:一|两|二|三|四|五|六|七|八|九|十)?({_CLASSIFIER_ALT})$",
        text,
    )
    if not match:
        return ""
    return match.group(1)


def normalize_fill_text(text: str) -> str:
    value = first_sentence_unit(text).strip(" 。，！？!?\"'“”‘’（）()[]【】")
    while value:
        cleaned = _NOISE_PREFIX_PATTERN.sub("", value).strip()
        if cleaned == value:
            break
        value = cleaned
    return value


def strip_redundant_leading_numeral(prefix: str, fill: str) -> str:
    if not fill:
        return ""
    if not re.search(rf"{_NUMERAL_PATTERN}$", prefix.strip()):
        return fill
    return re.sub(rf"^{_NUMERAL_PATTERN}", "", fill, count=1).strip()


def finalize_sentence(text: str) -> str:
    core = first_sentence_unit(text)
    if not core:
        return ""

    core = core.rstrip("。！？!?").strip()
    if not core:
        return ""
    return core + "。"


def extract_fill_from_candidate(candidate: str, prefix: str, suffix: str) -> str:
    if not candidate:
        return ""
    compact = re.sub(r"\s+", "", candidate)
    raw = first_sentence_unit(candidate)

    suffix_no_period = suffix.rstrip("。").strip()
    value = raw if raw else candidate

    if prefix and suffix_no_period:
        compact_prefix = re.sub(r"\s+", "", prefix)
        compact_suffix = re.sub(r"\s+", "", suffix_no_period)
        middle_match = re.search(
            rf"{re.escape(compact_prefix)}(.*?){re.escape(compact_suffix)}",
            compact,
        )
        if middle_match:
            value = middle_match.group(1)

    value = value.strip(" 。，！？!?\"'“”‘’（）()[]【】")
    if prefix and value.startswith(prefix):
        value = value[len(prefix) :]
    if suffix_no_period and value.endswith(suffix_no_period):
        value = value[: -len(suffix_no_period)]

    return normalize_fill_text(value)


def build_sentence(prompt: str, llm_text: str) -> str:
    if not llm_text.strip():
        return ""

    direct_sentence = finalize_sentence(llm_text)
    if "____" not in prompt:
        return direct_sentence

    prefix, suffix = prompt.split("____", 1)
    prefix = prefix.strip()
    suffix = suffix.strip()

    fill_candidates = [
        extract_fill_from_candidate(llm_text, prefix, suffix),
        extract_fill_from_candidate(direct_sentence, prefix, suffix),
        normalize_fill_text(llm_text),
    ]
    fill = next((item for item in fill_candidates if item), "")
    if prefix and fill.startswith(prefix):
        fill = fill[len(prefix) :].strip()
    suffix_no_period = suffix.rstrip("。").strip()
    if suffix_no_period and fill.endswith(suffix_no_period):
        fill = fill[: -len(suffix_no_period)].strip()

    if not fill:
        return normalize_sentence_by_prompt(direct_sentence, prompt)

    fill = strip_redundant_leading_numeral(prefix, fill)
    tail_classifier = detect_tail_classifier(prefix)
    if tail_classifier and fill:
        fill = re.sub(
            rf"^{_NUMERAL_PATTERN}?{tail_classifier}",
            "",
            fill,
            count=1,
        ).strip()
    if not fill:
        return normalize_sentence_by_prompt(direct_sentence, prompt)
    return normalize_sentence_by_prompt(finalize_sentence(f"{prefix}{fill}{suffix}"), prompt)


def _extract_prompt_blank_parts(prompt: str) -> tuple[str, str]:
    if "____" not in prompt:
        return "", ""
    prefix, suffix = prompt.split("____", 1)
    return prefix.strip(), suffix.strip().rstrip("。！？!?")


def _prompt_classifier_only_suffix(prompt: str) -> str:
    prefix, suffix = _extract_prompt_blank_parts(prompt)
    if prefix != "这是一":
        return ""
    if suffix not in GENERIC_PROMPT_SUFFIXES:
        return ""
    return suffix


def _extract_classifier_from_sentence(sentence: str, prefix: str, suffix: str) -> str:
    core = normalize_fill_text(sentence).rstrip("。！？!?")
    if not core:
        return ""

    remain = core
    if prefix and remain.startswith(prefix):
        remain = remain[len(prefix) :].strip()
    if suffix and remain.endswith(suffix):
        remain = remain[: -len(suffix)].strip()

    if not remain:
        return ""

    match = re.search(
        rf"{_NUMERAL_PATTERN}?({_CLASSIFIER_ALT})",
        remain,
    )
    if not match:
        return ""
    return match.group(1)


def normalize_sentence_by_prompt(sentence: str, prompt: str) -> str:
    text = finalize_sentence(sentence)
    if not text:
        return ""

    prefix, suffix = _extract_prompt_blank_parts(prompt)
    classifier_only_suffix = _prompt_classifier_only_suffix(prompt)
    if classifier_only_suffix and prefix:
        classifier = _extract_classifier_from_sentence(
            sentence=text,
            prefix=prefix,
            suffix=classifier_only_suffix,
        )
        if classifier:
            return finalize_sentence(f"{prefix}{classifier}{classifier_only_suffix}")

    return text


def sentence_has_classifier_and_noun(sentence: str) -> bool:
    core = sentence.strip()
    if not core:
        return False
    core = core.rstrip("。！？!?")
    match = re.search(
        rf"{_NUMERAL_PATTERN}({_CLASSIFIER_ALT})([^，。！？!?\s]+)",
        core,
    )
    if not match:
        return False
    noun = normalize_fill_text(match.group(2))
    return bool(noun)


def sentence_is_fluent(sentence: str) -> bool:
    text = sentence.strip()
    if not text:
        return False
    if not text.startswith("这") or "是" not in text:
        return False
    if "  " in text:
        return False
    if re.search(r"[。！？!?]{2,}", text):
        return False
    return True


def sentence_has_raw_noun_without_classifier(sentence: str) -> bool:
    text = sentence.strip()
    return bool(re.search(rf"这是一(?!{_CLASSIFIER_ALT})[^，。！？!?\s]+。?$", text))


def _prompt_requires_classifier_and_noun(prompt: str) -> bool:
    normalized = re.sub(r"\s+", "", prompt)
    return bool(re.match(r"^这是一_{3,}[。！？!?]?$", normalized))


def check_rules(sentence: str, prompt: str = "") -> list[str]:
    problems: list[str] = []
    first_dot = sentence.find("。")
    if first_dot == -1:
        problems.append("missing_period")
    elif first_dot != len(sentence) - 1:
        problems.append("extra_after_period")
    if sentence.count("。") != 1:
        problems.append("multiple_sentences")
    if ("这" not in sentence) or ("是" not in sentence):
        problems.append("incomplete_structure")
    if not sentence_is_fluent(sentence):
        problems.append("not_fluent")

    if _prompt_requires_classifier_and_noun(prompt):
        if not sentence_has_classifier_and_noun(sentence):
            problems.append("missing_classifier_or_noun")
        if sentence_has_raw_noun_without_classifier(sentence):
            problems.append("missing_specific_classifier")
    return problems


def _build_output_header(run_label: str, total_count: int) -> list[str]:
    return [
        f"学生目录: LLM_temp1_{run_label}",
        f"音频文件数: {total_count}",
        "=" * 60,
        "",
    ]


def _one_line_text(text: str) -> str:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s*\n\s*", r"\\n", normalized).strip()


def _compose_transcript_line(cleaned_sentence: str, raw_output: str) -> str:
    return f"转录: {cleaned_sentence} | 原始输出: {_one_line_text(raw_output)}"


def _split_transcript_payload(payload: str) -> tuple[str, str]:
    for sep in (" | 原始输出:", "| 原始输出:", "｜原始输出:", "｜ 原始输出:"):
        if sep in payload:
            cleaned, raw = payload.split(sep, 1)
            return cleaned.strip(), raw.strip()
    return payload.strip(), ""


def _strip_existing_summary(lines: list[str]) -> list[str]:
    for idx, line in enumerate(lines):
        if line.startswith("统计:"):
            cut = idx
            while cut > 0 and lines[cut - 1] == "":
                cut -= 1
            return lines[:cut]
    return lines


def _parse_existing_progress(
    lines: list[str], total_count: int
) -> tuple[int, int, int, int, set[int]]:
    success_count = 0
    empty_count = 0
    failed_count = 0
    anomaly_set: set[int] = set()
    seen_indices: set[int] = set()

    record_pattern = re.compile(r"^\[(\d+)/(\d+)\] 文件:")
    i = 0
    while i < len(lines):
        match = record_pattern.match(lines[i])
        if not match:
            i += 1
            continue

        index = int(match.group(1))
        seen_indices.add(index)

        sentence = ""
        remark = ""
        i += 1
        while i < len(lines) and lines[i] != "-" * 60:
            if lines[i].startswith("转录:"):
                payload = lines[i][len("转录:") :].strip()
                sentence, _raw_output = _split_transcript_payload(payload)
            elif lines[i].startswith("备注:"):
                remark = lines[i][len("备注:") :].strip()
            i += 1

        if remark:
            if "empty_response" in remark:
                empty_count += 1
            else:
                failed_count += 1
        elif sentence:
            success_count += 1
        else:
            failed_count += 1

        if check_rules(sentence):
            anomaly_set.add(index)

    completed_count = 0
    for idx in range(1, total_count + 1):
        if idx in seen_indices:
            completed_count = idx
        else:
            break

    anomaly_set = {idx for idx in anomaly_set if 1 <= idx <= total_count}
    return completed_count, success_count, empty_count, failed_count, anomaly_set


def run_experiment(
    *,
    run_label: str,
    total_count: int,
    output_filename: str,
    seed: int,
    model: str,
    base_url: str,
    output_dir: str,
    request_timeout: float,
    request_retries: int,
    resume: bool,
) -> int:
    pool = load_question_pool()
    if not pool:
        print("未读取到任何题目，请检查 xlsx 文件路径与内容。")
        return 2

    selected = select_questions(total_count, seed, pool)
    client = build_client(base_url, request_timeout)
    print(f"预检: 正在测试模型连接 (model={model}, base_url={base_url}) ...")
    preflight_ok, preflight_error = preflight_model_connection(
        client, model, request_timeout
    )
    if not preflight_ok:
        print("预检失败: 模型连接不可用，实验已终止。")
        if preflight_error:
            print(f"失败原因: {preflight_error}")
        print("请先检查网络/防火墙/代理，确认连通后再重试。")
        return 3
    print("预检通过: 模型连接正常，开始正式实验。")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    output_file = output_path / output_filename

    if resume and output_file.exists():
        existing_lines = output_file.read_text(encoding="utf-8").splitlines()
        existing_lines = _strip_existing_summary(existing_lines)
        (
            completed_count,
            success_count,
            empty_count,
            failed_count,
            anomaly_set,
        ) = _parse_existing_progress(existing_lines, total_count)
        if existing_lines:
            lines = existing_lines
        else:
            lines = _build_output_header(run_label, total_count)
        print(
            f"检测到已有进度: {completed_count}/{total_count}，将从下一题继续。",
            flush=True,
        )
    else:
        completed_count = 0
        success_count = 0
        empty_count = 0
        failed_count = 0
        anomaly_set: set[int] = set()
        lines = _build_output_header(run_label, total_count)

    for index, question in enumerate(selected, start=1):
        if index <= completed_count:
            continue

        print(
            f"[{index}/{total_count}] {question.source_file} | {question.vg_object_id}",
            flush=True,
        )
        started = time.perf_counter()
        llm_text, error = call_llm_with_retries(
            client,
            model,
            question,
            retries=request_retries,
            request_timeout=request_timeout,
        )
        elapsed = time.perf_counter() - started

        if llm_text:
            success_count += 1
            print(f"  -> OK ({elapsed:.2f}s)", flush=True)
        elif error == "empty_response":
            empty_count += 1
            print(f"  -> EMPTY ({elapsed:.2f}s)", flush=True)
        else:
            failed_count += 1
            print(f"  -> FAIL ({elapsed:.2f}s): {error}", flush=True)

        sentence = build_sentence(question.prompt, llm_text)
        problems = check_rules(sentence, question.prompt)
        if problems:
            anomaly_set.add(index)

        lines.append(f"[{index}/{total_count}] 文件: {question.pseudo_filename(run_label, index)}")
        lines.append(_compose_transcript_line(sentence, llm_text))
        if not sentence:
            reason = error or "模型返回内容无法解析为填空结果"
            lines.append(f"备注: 模型未给出可用填空结果，原因：{reason}")
        lines.append("-" * 60)

        # checkpoint: persist each finished item so runs can resume after interruption
        output_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    anomaly_indices = sorted(anomaly_set)
    compliant = total_count - len(anomaly_indices)
    compliance_rate = (compliant / total_count * 100.0) if total_count else 0.0
    anomaly_text = "无" if not anomaly_indices else ", ".join(map(str, anomaly_indices))

    final_lines = lines.copy()
    final_lines.append("")
    final_lines.append(
        f"统计: 成功 {success_count}，空结果 {empty_count}，失败 {failed_count}，总计 {total_count}"
    )
    final_lines.append(f"规则校验: 合规 {compliant}/{total_count} ({compliance_rate:.2f}%)")
    final_lines.append(f"异常条目编号: {anomaly_text}")

    output_file.write_text("\n".join(final_lines) + "\n", encoding="utf-8")

    print(f"输出文件: {output_file.resolve()}")
    print(f"规则校验: 合规 {compliant}/{total_count} ({compliance_rate:.2f}%)")
    if anomaly_indices:
        print(f"异常条目编号: {anomaly_text}")

    return 0
