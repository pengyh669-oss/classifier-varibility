from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_BASE_DIR = Path("translation")


def extract_right_side_preserve_lines(lines: list[str]) -> list[str]:
    """Extract text on the right side of '->' while preserving line count."""
    extracted: list[str] = []
    for line in lines:
        if "->" in line:
            right = line.split("->", 1)[1].strip()
            extracted.append(right)
        else:
            extracted.append("")
    return extracted


def process_one_file(input_file: Path, output_file: Path) -> int:
    lines = input_file.read_text(encoding="utf-8").splitlines()
    extracted = extract_right_side_preserve_lines(lines)

    output_file.write_text("\n".join(extracted), encoding="utf-8")
    return len(extracted)


def process_directory(input_dir: Path, output_dir: Path, stage_name: str) -> tuple[int, int]:
    if not input_dir.exists():
        raise FileNotFoundError(f"输入目录不存在: {input_dir}")

    txt_files = sorted(input_dir.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(f"在目录中没有找到 txt 文件: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    total_files = 0
    total_lines = 0

    print(f"\n开始处理 {stage_name}")
    print(f"输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")

    for txt_file in txt_files:
        output_file = output_dir / txt_file.name
        line_count = process_one_file(txt_file, output_file)

        total_files += 1
        total_lines += line_count

        print(
            f"已处理: {txt_file.name} -> {output_file.name} | "
            f"输出行数: {line_count}"
        )

    print(f"{stage_name} 完成: 文件数 {total_files} | 总行数 {total_lines}")
    return total_files, total_lines


def run(base_dir: Path) -> None:
    classifier_input = base_dir / "classified_classifer"
    classifier_output = base_dir / "classifer_res"

    nouns_input = base_dir / "classified_nouns"
    nouns_output = base_dir / "nouns_res"

    # Required order: classified_classifer first, then classified_nouns.
    c_files, c_lines = process_directory(
        input_dir=classifier_input,
        output_dir=classifier_output,
        stage_name="classified_classifer",
    )

    n_files, n_lines = process_directory(
        input_dir=nouns_input,
        output_dir=nouns_output,
        stage_name="classified_nouns",
    )

    print("\n全部处理完成")
    print(f"总文件数: {c_files + n_files}")
    print(f"总输出行数: {c_lines + n_lines}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "按顺序提取 classified_classifer 与 classified_nouns 下每个 txt 的 '->' "
            "右侧内容，逐行输出到 classifer_res 与 nouns_res，文件名保持一致。"
        )
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=DEFAULT_BASE_DIR,
        help=f"包含输入输出目录的基准目录，默认: {DEFAULT_BASE_DIR}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run(base_dir=args.base_dir)


if __name__ == "__main__":
    main()
