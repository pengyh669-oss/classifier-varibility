from __future__ import annotations

import argparse
import os
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from openai import OpenAI


DATA_SOURCES = {
    "result_data_upWord": "result_data_upWord.xlsx",
    "result_data_normalWord": "result_data_normalWord.xlsx",
    "result_data_downWord": "result_data_downWord.xlsx",
}

DEFAULT_BASE_URL = "https://api.zhizengzeng.com/v1"
DEFAULT_MODEL = "qwen2.5-vl-72b-instruct"
DEFAULT_SEED = 20260406
DEFAULT_REQUEST_TIMEOUT_SECONDS = 90.0
DEFAULT_REQUEST_RETRIES = 2


@dataclass
class Question:
    unique_key: str
    source_file: str
    vg_object_id: str
    question_id: str
    prompt: str

    def pseudo_filename(self, run_label: str) -> str:
        return f"LLM_{run_label}_{self.source_file}_{self.vg_object_id}_{self.question_id}"


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
        default="LLM_answer_classifer",
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


def load_question_pool() -> list[Question]:
    questions: list[Question] = []

    for source_key, file_name in DATA_SOURCES.items():
        file_path = resolve_data_file(file_name)
        df = pd.read_excel(file_path)

        for row_index, row in df.iterrows():
            prompt = _safe_str(row.get("prompt", ""))
            vg_object_id = _safe_str(row.get("vg_object_id", ""))
            question_id = _safe_str(row.get("question_id", ""))

            if not prompt:
                continue

            unique_key = f"{source_key}_{question_id}_{row_index}"
            questions.append(
                Question(
                    unique_key=unique_key,
                    source_file=source_key,
                    vg_object_id=vg_object_id or str(row_index),
                    question_id=question_id or f"q_{row_index}",
                    prompt=prompt,
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
        if key == "API_KEY":
            os.environ[key] = value


def extract_message_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except Exception:  # noqa: BLE001
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        return "".join(
            str(item["text"] if isinstance(item, dict) else getattr(item, "text", ""))
            for item in content if item
        )

    return ""


def call_llm_once(
    client: OpenAI,
    model: str,
    question: Question,
    request_timeout: float,
) -> str:
    system_prompt = (
        "你将看到一个包含下划线的中文句子。\n"
        "对下划线做最小必要补全，并只输出补全后的完整句子。\n"
        "\n"
        "要求：\n"
        "1. 先判断原句已经给出的成分，再决定下划线需要补什么。\n"
        "2. 只补缺失成分，不重复原句已有成分。\n"
        "4. 不要补充颜色、位置、动作、用途等额外描述，除非原句本身要求。\n"
        "5. 若有多个可能答案，选择最短、最自然、不过度补充的答案。\n"
        "\n"
        "输出要求：\n"
        "只输出补全后的完整句子，不要解释，不要分析，不要输出多余内容。"
    )
    user_text = (
        f"待补全句子：{question.prompt}\n"
        "\n"
        "请按以下规则补全：\n"
        '1. "这是一____动物/植物/载具/家具/衣服/建筑/食物。" → 只补量词。\n'
        "2. 最终只输出补全后的完整句子。"
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
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
            timeout=request_timeout,
        )
        choice = response.choices[0] if getattr(response, "choices", None) else None
        message = getattr(choice, "message", None)
        text = extract_message_text(response).strip()
        reasoning = getattr(message, "reasoning_content", None) if message else None
        if text or reasoning is not None:
            return True, None
        return False, "empty_response"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


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


def _compose_output_line(completed_sentence: str, raw_output: str) -> str:
    return f"补全句子: {completed_sentence} | 原始输出: {_one_line_text(raw_output)}"


def _split_output_payload(payload: str) -> tuple[str, str]:
    parts = re.split(r"\s*[｜|]\s*原始输出:\s*", payload, maxsplit=1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (payload.strip(), "")


def _classify_outcome(sentence: str, reason: str | None) -> str:
    if not sentence:
        return "empty" if reason and "empty_response" in reason else "failed"
    return "success"


def _strip_existing_summary(lines: list[str]) -> list[str]:
    for idx, line in enumerate(lines):
        if line.startswith("统计:"):
            while idx > 0 and lines[idx - 1] == "":
                idx -= 1
            return lines[:idx]
    return lines


def _parse_existing_progress(
    lines: list[str],
    total_count: int,
) -> tuple[int, int, int, int]:
    success_count = 0
    empty_count = 0
    failed_count = 0
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
            if lines[i].startswith("补全句子:"):
                payload = lines[i][len("补全句子:") :].strip()
                sentence, _raw_output = _split_output_payload(payload)
            elif lines[i].startswith("备注:"):
                remark = lines[i][len("备注:") :].strip()
            i += 1

        outcome = _classify_outcome(sentence, remark)
        if outcome == "success":
            success_count += 1
        elif outcome == "empty":
            empty_count += 1
        else:
            failed_count += 1

    completed_count = 0
    for idx in range(1, total_count + 1):
        if idx in seen_indices:
            completed_count = idx
        else:
            break

    return completed_count, success_count, empty_count, failed_count


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
        lines = _build_output_header(run_label, total_count)

    for index, question in enumerate(selected, start=1):
        if index <= completed_count:
            continue

        print(
            f"[{index}/{total_count}] {question.source_file} | {question.question_id}",
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

        sentence = llm_text.strip()
        reason = "" if sentence else (error or "模型返回内容无法解析")
        outcome = _classify_outcome(sentence, reason)
        if outcome == "success":
            success_count += 1
            print(f"  -> OK ({elapsed:.2f}s)", flush=True)
        elif outcome == "empty":
            empty_count += 1
            print(f"  -> EMPTY ({elapsed:.2f}s)", flush=True)
        else:
            failed_count += 1
            print(f"  -> FAIL ({elapsed:.2f}s): {reason}", flush=True)

        lines.append(
            f"[{index}/{total_count}] 文件: {question.pseudo_filename(run_label)}"
        )
        lines.append(_compose_output_line(sentence, llm_text))
        if reason:
            lines.append(f"备注: 模型未给出可用补全结果，原因：{reason}")
        lines.append("-" * 60)

        output_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    final_lines = lines.copy()
    final_lines.append("")
    final_lines.append(
        f"统计: 成功 {success_count}，空结果 {empty_count}，失败 {failed_count}，总计 {total_count}"
    )

    output_file.write_text("\n".join(final_lines) + "\n", encoding="utf-8")

    print(f"输出文件: {output_file.resolve()}")
    print(f"统计: 成功 {success_count}，空结果 {empty_count}，失败 {failed_count}，总计 {total_count}")

    return 0
