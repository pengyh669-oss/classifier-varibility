from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from zai import ZhipuAiClient

DEFAULT_INPUT_DIR = Path("translation") / "extracted"
DEFAULT_OUTPUT_DIR = Path("translation") / "noun_text"
DEFAULT_MODEL = "glm-5"
DEFAULT_TEMPERATURE = 0.1
DEFAULT_CHUNK_SIZE = 40
DEFAULT_RETRIES = 3
DEFAULT_DELAY_SECONDS = 0.5

SYSTEM_PROMPT = """
你是一个只负责抽取中文句子中心名词的助手。

任务要求：
1. 针对每个输入句子，只提取一个最核心的名词或名词短语。
2. 只保留对象本体，不要保留“这是一只/一个/一张/一辆”等数量词、判断词和修饰框架。
3. 如果句子中出现更具体的对象名称，优先保留更具体的名词短语。
4. 如果句子没有清晰的中心名词，返回空字符串。
5. 必须严格按要求输出 JSON，不要输出解释、Markdown、代码块标题或额外文字。
""".strip()

USER_PROMPT_TEMPLATE = """
请根据下面的句子提取中心名词，并严格返回 JSON 对象，格式如下：
{{
  "results": [
    {{"line_no": 1, "noun": "花"}},
    {{"line_no": 2, "noun": "羊"}}
  ]
}}

规则：
1. `results` 的元素数量必须与输入数量完全一致。
2. `line_no` 必须与输入中的 `line_no` 一一对应。
3. `noun` 只填写一个中心名词或名词短语，不要添加句号、解释或其他字段。

输入：
{payload}
""".strip()

KNOWN_PREFIXES = ("转录:", "杞綍:")


def clean_line(line: str) -> str:
    text = line.strip()
    for prefix in KNOWN_PREFIXES:
        if text.startswith(prefix):
            return text.split(":", 1)[1].strip()
    return text


def build_output_name(input_file: Path) -> str:
    stem = input_file.stem
    if stem.endswith("_transcripts_only"):
        stem = stem[: -len("_transcripts_only")]
    return f"{stem}.txt"


def strip_code_fence(text: str) -> str:
    content = text.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    return content


def parse_response_text(content: str) -> list[dict[str, object]]:
    cleaned = strip_code_fence(content)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError(f"模型返回的内容不是有效 JSON: {content}") from None
        data = json.loads(cleaned[start : end + 1])

    if not isinstance(data, dict) or "results" not in data:
        raise ValueError(f"模型返回缺少 results 字段: {content}")

    results = data["results"]
    if not isinstance(results, list):
        raise ValueError(f"模型返回的 results 不是列表: {content}")

    normalized: list[dict[str, object]] = []
    for item in results:
        if not isinstance(item, dict):
            raise ValueError(f"模型返回的元素不是对象: {content}")
        normalized.append(item)
    return normalized


def request_nouns(
    client: ZhipuAiClient,
    items: list[dict[str, object]],
    *,
    model: str,
    temperature: float,
    retries: int,
    retry_delay: float,
) -> list[dict[str, object]]:
    payload = json.dumps(items, ensure_ascii=False, indent=2)
    user_prompt = USER_PROMPT_TEMPLATE.format(payload=payload)

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
            )
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise ValueError("模型返回内容为空")
            return parse_response_text(content)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == retries:
                break
            time.sleep(retry_delay)

    assert last_error is not None
    raise last_error


def validate_results(
    requested_items: list[dict[str, object]],
    results: list[dict[str, object]],
) -> list[tuple[int, str]]:
    if len(results) != len(requested_items):
        raise ValueError(
            f"模型返回条数不匹配，期望 {len(requested_items)} 条，实际 {len(results)} 条"
        )

    expected_line_nos = [int(item["line_no"]) for item in requested_items]
    output_pairs: list[tuple[int, str]] = []

    for expected_line_no, item in zip(expected_line_nos, results, strict=True):
        line_no = item.get("line_no")
        noun = item.get("noun", "")

        if not isinstance(line_no, int):
            raise ValueError(f"模型返回的 line_no 不是整数: {item}")
        if line_no != expected_line_no:
            raise ValueError(
                f"模型返回的 line_no 不匹配，期望 {expected_line_no}，实际 {line_no}"
            )
        if noun is None:
            noun = ""
        if not isinstance(noun, str):
            noun = str(noun)

        output_pairs.append((line_no, noun.strip()))

    return output_pairs


def chunk_items(items: list[dict[str, object]], chunk_size: int) -> list[list[dict[str, object]]]:
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def process_one_file(
    client: ZhipuAiClient,
    input_file: Path,
    output_file: Path,
    *,
    model: str,
    temperature: float,
    chunk_size: int,
    retries: int,
    retry_delay: float,
    request_delay: float,
) -> tuple[int, int]:
    raw_lines = input_file.read_text(encoding="utf-8").splitlines()
    cleaned_lines = [clean_line(line) for line in raw_lines]
    extracted_nouns = [""] * len(cleaned_lines)

    non_empty_items = [
        {"line_no": index, "text": text}
        for index, text in enumerate(cleaned_lines, start=1)
        if text
    ]

    for batch_index, batch in enumerate(chunk_items(non_empty_items, chunk_size), start=1):
        batch_results = request_nouns(
            client,
            batch,
            model=model,
            temperature=temperature,
            retries=retries,
            retry_delay=retry_delay,
        )
        for line_no, noun in validate_results(batch, batch_results):
            extracted_nouns[line_no - 1] = noun

        print(
            f"  已完成批次 {batch_index}/{(len(non_empty_items) + chunk_size - 1) // chunk_size} "
            f"| {input_file.name}"
        )
        if request_delay > 0:
            time.sleep(request_delay)

    output_file.write_text("\n".join(extracted_nouns), encoding="utf-8")
    return len(cleaned_lines), len(non_empty_items)


def run(
    *,
    api_key: str,
    input_dir: Path,
    output_dir: Path,
    model: str,
    temperature: float,
    chunk_size: int,
    retries: int,
    retry_delay: float,
    request_delay: float,
    overwrite: bool,
    limit: int | None,
) -> None:
    if not input_dir.exists():
        raise FileNotFoundError(f"输入目录不存在: {input_dir}")

    txt_files = sorted(input_dir.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(f"在目录中没有找到 txt 文件: {input_dir}")

    if limit is not None:
        txt_files = txt_files[:limit]

    output_dir.mkdir(parents=True, exist_ok=True)
    client = ZhipuAiClient(api_key=api_key)

    processed_files = 0
    skipped_files = 0
    total_lines = 0
    total_non_empty_lines = 0

    for txt_file in txt_files:
        output_file = output_dir / build_output_name(txt_file)
        if output_file.exists() and not overwrite:
            skipped_files += 1
            print(f"跳过已存在文件: {output_file.name}")
            continue

        print(f"开始处理: {txt_file.name}")
        line_count, non_empty_count = process_one_file(
            client,
            txt_file,
            output_file,
            model=model,
            temperature=temperature,
            chunk_size=chunk_size,
            retries=retries,
            retry_delay=retry_delay,
            request_delay=request_delay,
        )

        processed_files += 1
        total_lines += line_count
        total_non_empty_lines += non_empty_count

        print(
            f"已输出: {output_file.name} | 总行数: {line_count} | 非空行数: {non_empty_count}"
        )

    print("\n处理完成")
    print(f"输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")
    print(f"处理文件数: {processed_files}")
    print(f"跳过文件数: {skipped_files}")
    print(f"总行数: {total_lines}")
    print(f"总非空行数: {total_non_empty_lines}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "读取 translation/extracted 下的 txt 文件，调用 glm-5 提取每行句子的中心名词，"
            "并将结果写入 translation/noun_text。"
        )
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("ZAI_API_KEY"),
        help="智谱 API Key，默认读取环境变量 ZAI_API_KEY",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"输入目录，默认: {DEFAULT_INPUT_DIR}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录，默认: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"模型名称，默认: {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help=f"采样温度，默认: {DEFAULT_TEMPERATURE}",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"每次请求包含的句子数，默认: {DEFAULT_CHUNK_SIZE}",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help=f"单个请求最大重试次数，默认: {DEFAULT_RETRIES}",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=f"请求失败后的重试等待秒数，默认: {DEFAULT_DELAY_SECONDS}",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=f"每个请求之间的等待秒数，默认: {DEFAULT_DELAY_SECONDS}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只处理前 N 个文件，便于小范围试跑",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖已存在的输出文件",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.api_key:
        raise ValueError("缺少 API Key，请设置环境变量 ZAI_API_KEY 或通过 --api-key 传入")
    if args.chunk_size <= 0:
        raise ValueError("--chunk-size 必须大于 0")
    if args.retries <= 0:
        raise ValueError("--retries 必须大于 0")

    run(
        api_key=args.api_key,
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        model=args.model,
        temperature=args.temperature,
        chunk_size=args.chunk_size,
        retries=args.retries,
        retry_delay=args.retry_delay,
        request_delay=args.request_delay,
        overwrite=args.overwrite,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
