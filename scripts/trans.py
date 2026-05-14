from __future__ import annotations

import re
from pathlib import Path

import whisper

RECORDINGS_DIR = Path("recordings")
TRANSLATION_DIR = Path("translation")
MODEL_NAME = "large-v2"
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".webm", ".flac", ".aac"}
STUDENT_DIR_PATTERN = re.compile(r"^(?P<student_id>\d+)_(?P<student_name>[^_]+)")


def extract_student_identity(folder_name: str) -> tuple[str | None, str | None, str]:
    """Extract student id/name from folder name and return safe output filename stem."""
    match = STUDENT_DIR_PATTERN.match(folder_name)
    if match:
        student_id = match.group("student_id")
        student_name = match.group("student_name")
        return student_id, student_name, f"{student_name}_{student_id}"

    safe_name = re.sub(r"[\\/:*?\"<>|]", "_", folder_name).strip(" ._")
    if not safe_name:
        safe_name = "unknown_student"
    return None, None, safe_name


def list_student_dirs(root: Path) -> list[Path]:
    return sorted((path for path in root.iterdir() if path.is_dir()), key=lambda p: p.name)


def list_audio_files(student_dir: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in student_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
        ),
        key=lambda p: p.relative_to(student_dir).as_posix(),
    )


def build_unique_output_file(output_dir: Path, base_stem: str, used_names: set[str]) -> Path:
    """Ensure one folder always maps to one unique output file (avoid overwrite collisions)."""
    safe_stem = re.sub(r"[\\/:*?\"<>|]", "_", base_stem).strip(" ._")
    if not safe_stem:
        safe_stem = "unknown_student"

    candidate = safe_stem
    suffix = 1
    while candidate in used_names:
        suffix += 1
        candidate = f"{safe_stem}__{suffix}"

    used_names.add(candidate)
    return output_dir / f"{candidate}.txt"


def transcribe_student(model: whisper.Whisper, student_dir: Path, output_file: Path) -> tuple[int, int, int, int]:
    audio_files = list_audio_files(student_dir)

    success_count = 0
    empty_count = 0
    failed_count = 0

    with output_file.open("w", encoding="utf-8") as handle:
        handle.write(f"学生目录: {student_dir.name}\n")
        handle.write(f"音频文件数: {len(audio_files)}\n")
        handle.write("=" * 60 + "\n\n")

        for idx, audio_path in enumerate(audio_files, start=1):
            rel_name = audio_path.relative_to(student_dir).as_posix()
            print(f"    [{idx}/{len(audio_files)}] {rel_name}")
            handle.write(f"[{idx}/{len(audio_files)}] 文件: {rel_name}\n")

            try:
                result = model.transcribe(str(audio_path), language="zh")
                text = result.get("text", "").strip()

                if text:
                    success_count += 1
                    handle.write(f"转录: {text}\n")
                    preview = text.replace("\n", " ")
                    if len(preview) > 60:
                        preview = preview[:60] + "..."
                    print(f"      完成: {preview}")
                else:
                    empty_count += 1
                    handle.write("转录: (空结果/可能是静音)\n")
                    print("      空结果: 可能是静音")
            except Exception as exc:
                failed_count += 1
                handle.write(f"错误: {exc}\n")
                print(f"      失败: {exc}")

            handle.write("-" * 60 + "\n")

        handle.write("\n")
        handle.write(
            f"统计: 成功 {success_count}，空结果 {empty_count}，失败 {failed_count}，总计 {len(audio_files)}\n"
        )

    return len(audio_files), success_count, empty_count, failed_count


def main() -> None:
    print("开始批量转录 recordings 下的学生目录...")

    if not RECORDINGS_DIR.exists():
        print("错误: 未找到 recordings 目录")
        return

    student_dirs = list_student_dirs(RECORDINGS_DIR)
    if not student_dirs:
        print("错误: recordings 目录下没有学生子文件夹")
        return

    TRANSLATION_DIR.mkdir(parents=True, exist_ok=True)

    print(f"共找到 {len(student_dirs)} 个学生目录")
    print(f"加载 Whisper 模型: {MODEL_NAME}")
    model = whisper.load_model(MODEL_NAME)

    total_files = 0
    total_success = 0
    total_empty = 0
    total_failed = 0
    used_output_names: set[str] = set()

    for student_index, student_dir in enumerate(student_dirs, start=1):
        student_id, student_name, output_stem = extract_student_identity(student_dir.name)
        output_file = build_unique_output_file(
            output_dir=TRANSLATION_DIR,
            base_stem=output_stem,
            used_names=used_output_names,
        )

        if student_id and student_name:
            student_label = f"{student_name}({student_id})"
        else:
            student_label = student_dir.name

        print(f"\n[{student_index}/{len(student_dirs)}] 正在转录学生: {student_label}")
        print(f"  目录: {student_dir}")
        print(f"  输出: {output_file}")

        file_count, success_count, empty_count, failed_count = transcribe_student(
            model=model,
            student_dir=student_dir,
            output_file=output_file,
        )

        total_files += file_count
        total_success += success_count
        total_empty += empty_count
        total_failed += failed_count

        print(
            f"  完成: 成功 {success_count}，空结果 {empty_count}，失败 {failed_count}，共 {file_count} 个文件"
        )

    print("\n全部学生转录完成")
    print(
        f"总计文件 {total_files} 个 | 成功 {total_success} | 空结果 {total_empty} | 失败 {total_failed}"
    )
    print(f"转录结果已保存到: {TRANSLATION_DIR.resolve()}")


if __name__ == "__main__":
    main()
