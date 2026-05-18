from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_INPUT_DIR = Path("translation") / "extracted"
DEFAULT_OUTPUT_DIR = Path("translation") / "calssifer_text"


def clean_line(line: str) -> str:
    """Normalize one transcript line and strip known prefixes."""
    text = line.strip()
    if text.startswith("转录:"):
        text = text.split(":", 1)[1].strip()
    return text


def get_fourth_char(text: str) -> str:
    """Return the 4th character of a sentence; empty when shorter."""
    if len(text) < 4:
        return ""
    return text[3]


def process_one_file(input_file: Path, output_file: Path) -> tuple[int, int]:
    lines = input_file.read_text(encoding="utf-8").splitlines()

    extracted_chars: list[str] = []
    valid_sentences = 0

    for raw in lines:
        sentence = clean_line(raw)
        if not sentence:
            continue

        valid_sentences += 1
        extracted_chars.append(get_fourth_char(sentence))

    # One character per line is easy to paste into one Excel column.
    output_file.write_text("\n".join(extracted_chars), encoding="utf-8")
    return valid_sentences, len(extracted_chars)


def build_output_name(input_file: Path) -> str:
    stem = input_file.stem
    if stem.endswith("_transcripts_only"):
        stem = stem[: -len("_transcripts_only")]
    return f"{stem}_第四字.txt"


def run(input_dir: Path, output_dir: Path) -> None:
    if not input_dir.exists():
        raise FileNotFoundError(f"输入目录不存在: {input_dir}")

    txt_files = sorted(input_dir.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(f"在目录中没有找到 txt 文件: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    total_files = 0
    total_sentences = 0

    for txt_file in txt_files:
        output_name = build_output_name(txt_file)
        output_file = output_dir / output_name

        sentence_count, written_count = process_one_file(txt_file, output_file)

        total_files += 1
        total_sentences += sentence_count

        print(
            f"已处理: {txt_file.name} -> {output_file.name} | "
            f"句子数: {sentence_count} | 输出行数: {written_count}"
        )

    print("\n处理完成")
    print(f"输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")
    print(f"文件数: {total_files}")
    print(f"总句子数: {total_sentences}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "读取 translation/extracted 下每个 txt，按句提取第4个字，"
            "并保存到 translation/calssifer_text。"
        )
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run(input_dir=args.input_dir, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
