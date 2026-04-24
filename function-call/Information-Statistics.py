from __future__ import annotations

import argparse
import math
import random
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

HUMAN_QUANTIFIER_LABELS = ["普通量词", "特殊量词"]
HUMAN_NOUN_LABELS = ["上位词", "下位词", "普通词"]

HUMAN_ITEM_PATTERN = re.compile(
    r"result[-_]data(?:[-_](?:upWord|downWord|free|special|normalWord))?[-_](\d+)_",
    re.IGNORECASE,
)
LLM_ITEM_PATTERN = re.compile(
    r"LLM_formal_result_data(?:_(?:upWord|downWord|free|special|normalWord))?_(\d+)_",
    re.IGNORECASE,
)


def normalize_student_id(value: object) -> str | None:
    if pd.isna(value):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer():
            return str(int(value))
        return str(value).strip()
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def normalize_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def extract_item_id(filename: object, is_llm: bool) -> str | None:
    text = normalize_text(filename)
    if not text:
        return None
    pattern = LLM_ITEM_PATTERN if is_llm else HUMAN_ITEM_PATTERN
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1)


def load_data(human_path: Path, llm_path: Path, human_sheet: str, llm_sheet: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    human = pd.read_excel(human_path, sheet_name=human_sheet)
    llm = pd.read_excel(llm_path, sheet_name=llm_sheet)

    human = human.copy()
    llm = llm.copy()

    human["学号_标准"] = human["学号"].map(normalize_student_id)
    human["题号ID"] = human["文件名"].map(lambda x: extract_item_id(x, is_llm=False))

    llm["模型名字"] = llm["模型名字"].map(normalize_text)
    llm["题号ID"] = llm["文件名"].map(lambda x: extract_item_id(x, is_llm=True))

    for col in ["回答文本", "量词类型", "名词类型", "文件名"]:
        human[col] = human[col].map(normalize_text)
        llm[col] = llm[col].map(normalize_text)

    return human, llm


def choose_students(student_ids: list[str], sample_size: int, seed: int | None) -> list[str]:
    if len(student_ids) < sample_size:
        raise ValueError(f"可抽样被试数量不足: 需要 {sample_size}, 实际 {len(student_ids)}")
    rng: random.Random | random.SystemRandom
    if seed is None:
        rng = random.SystemRandom()
    else:
        rng = random.Random(seed)
    return rng.sample(student_ids, sample_size)


def type_counts(series: pd.Series, labels: list[str]) -> dict[str, int]:
    cleaned = series.map(normalize_text)
    counts = {label: int((cleaned == label).sum()) for label in labels}
    counts["其他"] = int(((cleaned != "") & (~cleaned.isin(labels))).sum())
    counts["缺失"] = int((cleaned == "").sum())
    counts["总记录"] = int(len(cleaned))
    return counts


def check_common_questions(sample_df: pd.DataFrame, sampled_students: list[str], common_item_ids: list[str]) -> bool:
    common_set = set(common_item_ids)
    for sid in sampled_students:
        sid_set = set(sample_df.loc[sample_df["学号_标准"] == sid, "题号ID"])
        if not common_set.issubset(sid_set):
            return False
    return True


def build_type_lines(title: str, quant_counts: dict[str, int], noun_counts: dict[str, int]) -> list[str]:
    lines = [title]
    lines.append(
        f"  量词类型: 普通量词={quant_counts['普通量词']}, 特殊量词={quant_counts['特殊量词']}, "
        f"其他={quant_counts['其他']}, 缺失={quant_counts['缺失']}, 总记录={quant_counts['总记录']}"
    )
    lines.append(
        f"  名词类型: 上位词={noun_counts['上位词']}, 下位词={noun_counts['下位词']}, 普通词={noun_counts['普通词']}, "
        f"其他={noun_counts['其他']}, 缺失={noun_counts['缺失']}, 总记录={noun_counts['总记录']}"
    )
    return lines


def build_human_common_section(human_common: pd.DataFrame, common_item_ids: list[str]) -> list[str]:
    lines = ["====================", "2) 人类-共同题统计", "===================="]
    if not common_item_ids:
        lines.append("共同题为空，无法输出该分节。")
        return lines

    for item_id in common_item_ids:
        lines.append(f"题号ID: {item_id}")
        subset = human_common.loc[human_common["题号ID"] == item_id].copy()
        subset = subset.sort_values(["学号_标准", "文件名"], kind="stable")
        lines.append(f"  记录数: {len(subset)}")
        lines.append("  回答文本(逐条原文):")
        for _, row in subset.iterrows():
            lines.append(
                f"    - [学号 {row['学号_标准']}] {row['回答文本']} "
                f"(量词类型={row['量词类型'] or '缺失'}, 名词类型={row['名词类型'] or '缺失'}, 文件名={row['文件名']})"
            )

        q_counts = type_counts(subset["量词类型"], HUMAN_QUANTIFIER_LABELS)
        n_counts = type_counts(subset["名词类型"], HUMAN_NOUN_LABELS)
        lines.extend(build_type_lines("  类型计数:", q_counts, n_counts))
        lines.append("")

    total_q = type_counts(human_common["量词类型"], HUMAN_QUANTIFIER_LABELS)
    total_n = type_counts(human_common["名词类型"], HUMAN_NOUN_LABELS)
    lines.extend(build_type_lines("共同题总体类型计数:", total_q, total_n))
    return lines


def build_llm_common_section(llm_common: pd.DataFrame, common_item_ids: list[str]) -> list[str]:
    lines = ["====================", "3) LLM-共同题统计", "===================="]
    if not common_item_ids:
        lines.append("共同题为空，无法输出该分节。")
        return lines

    for item_id in common_item_ids:
        lines.append(f"题号ID: {item_id}")
        subset = llm_common.loc[llm_common["题号ID"] == item_id].copy()
        subset = subset.sort_values(["模型名字", "文件名"], kind="stable")
        lines.append(f"  记录数: {len(subset)}")
        lines.append("  回答文本(逐条原文):")
        for _, row in subset.iterrows():
            lines.append(
                f"    - [模型 {row['模型名字']}] {row['回答文本']} "
                f"(量词类型={row['量词类型'] or '缺失'}, 名词类型={row['名词类型'] or '缺失'}, 文件名={row['文件名']})"
            )

        q_counts = type_counts(subset["量词类型"], HUMAN_QUANTIFIER_LABELS)
        n_counts = type_counts(subset["名词类型"], HUMAN_NOUN_LABELS)
        lines.extend(build_type_lines("  类型计数:", q_counts, n_counts))
        lines.append("")

    total_q = type_counts(llm_common["量词类型"], HUMAN_QUANTIFIER_LABELS)
    total_n = type_counts(llm_common["名词类型"], HUMAN_NOUN_LABELS)
    lines.extend(build_type_lines("共同题总体类型计数:", total_q, total_n))
    return lines


def build_human_all_section(human_sample_all: pd.DataFrame, sample_size: int) -> list[str]:
    lines = ["====================", f"4) 人类-{sample_size}人全量(仅类型计数)", "===================="]
    total_q = type_counts(human_sample_all["量词类型"], HUMAN_QUANTIFIER_LABELS)
    total_n = type_counts(human_sample_all["名词类型"], HUMAN_NOUN_LABELS)
    lines.extend(build_type_lines(f"{sample_size}人全量总体类型计数:", total_q, total_n))
    return lines


def build_llm_all_section(llm_all: pd.DataFrame) -> list[str]:
    lines = ["====================", "5) LLM-5模型全量(仅类型计数)", "===================="]

    total_q = type_counts(llm_all["量词类型"], HUMAN_QUANTIFIER_LABELS)
    total_n = type_counts(llm_all["名词类型"], HUMAN_NOUN_LABELS)
    lines.extend(build_type_lines("5模型全量总体类型计数:", total_q, total_n))
    lines.append("")
    lines.append("按模型分组计数:")

    for model_name, group in llm_all.groupby("模型名字", sort=True):
        q_counts = type_counts(group["量词类型"], HUMAN_QUANTIFIER_LABELS)
        n_counts = type_counts(group["名词类型"], HUMAN_NOUN_LABELS)
        lines.extend(build_type_lines(f"  模型={model_name}", q_counts, n_counts))

    return lines


def build_validation_section(
    sampled_students: list[str],
    common_item_ids: list[str],
    human_sample_all: pd.DataFrame,
    human_common: pd.DataFrame,
    llm_all: pd.DataFrame,
) -> list[str]:
    lines = ["", "====================", "校验结果", "===================="]
    common_ok = check_common_questions(human_sample_all, sampled_students, common_item_ids)
    lines.append(f"共同题正确性: {'通过' if common_ok else '失败'}")

    human_common_q = type_counts(human_common["量词类型"], HUMAN_QUANTIFIER_LABELS)
    human_common_n = type_counts(human_common["名词类型"], HUMAN_NOUN_LABELS)
    llm_all_q = type_counts(llm_all["量词类型"], HUMAN_QUANTIFIER_LABELS)

    lines.append(
        "共同题计数一致性(人类): "
        f"量词总记录={human_common_q['总记录']}, 名词总记录={human_common_n['总记录']}"
    )

    by_model_q = Counter()
    for _, group in llm_all.groupby("模型名字"):
        group_counts = type_counts(group["量词类型"], HUMAN_QUANTIFIER_LABELS)
        by_model_q["普通量词"] += group_counts["普通量词"]
        by_model_q["特殊量词"] += group_counts["特殊量词"]
        by_model_q["其他"] += group_counts["其他"]
        by_model_q["缺失"] += group_counts["缺失"]
        by_model_q["总记录"] += group_counts["总记录"]
    llm_sum_ok = (
        by_model_q["普通量词"] == llm_all_q["普通量词"]
        and by_model_q["特殊量词"] == llm_all_q["特殊量词"]
        and by_model_q["其他"] == llm_all_q["其他"]
        and by_model_q["缺失"] == llm_all_q["缺失"]
        and by_model_q["总记录"] == llm_all_q["总记录"]
    )
    lines.append(f"LLM分模型求和=总体: {'通过' if llm_sum_ok else '失败'}")
    return lines


def run(args: argparse.Namespace) -> Path:
    base_dir = Path(args.base_dir).resolve()
    human_path = (base_dir / args.human_file).resolve()
    llm_path = (base_dir / args.llm_file).resolve()
    output_path = (base_dir / args.output_file).resolve()

    human, llm = load_data(human_path, llm_path, args.human_sheet, args.llm_sheet)

    human_valid = human.loc[(human["学号_标准"] != "") & human["学号_标准"].notna() & human["题号ID"].notna()].copy()
    llm_valid = llm.loc[(llm["模型名字"] != "") & llm["题号ID"].notna()].copy()

    student_ids = sorted(human_valid["学号_标准"].unique().tolist())
    sampled_students = choose_students(student_ids, args.sample_size, args.seed)

    human_sample_all = human_valid.loc[human_valid["学号_标准"].isin(sampled_students)].copy()

    student_item_sets = [
        set(human_sample_all.loc[human_sample_all["学号_标准"] == sid, "题号ID"]) for sid in sampled_students
    ]
    common_item_ids = sorted(set.intersection(*student_item_sets), key=lambda x: int(x))

    human_common = human_sample_all.loc[human_sample_all["题号ID"].isin(common_item_ids)].copy()
    llm_common = llm_valid.loc[llm_valid["题号ID"].isin(common_item_ids)].copy()

    lines: list[str] = []
    lines.append("信息统计结果")
    lines.append("====================")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"人类数据文件: {human_path}")
    lines.append(f"LLM数据文件: {llm_path}")
    lines.append(f"抽样人数: {args.sample_size}")
    lines.append(f"随机种子: {args.seed if args.seed is not None else '无(每次随机)'}")
    lines.append(f"抽样学号: {', '.join(sampled_students)}")
    lines.append(f"共同题号数量: {len(common_item_ids)}")
    lines.append(f"共同题号列表: {', '.join(common_item_ids) if common_item_ids else '无'}")
    lines.append("")
    lines.extend(build_human_common_section(human_common, common_item_ids))
    lines.append("")
    lines.extend(build_llm_common_section(llm_common, common_item_ids))
    lines.append("")
    lines.extend(build_human_all_section(human_sample_all, args.sample_size))
    lines.append("")
    lines.extend(build_llm_all_section(llm_valid))
    lines.extend(build_validation_section(sampled_students, common_item_ids, human_sample_all, human_common, llm_valid))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="统计转录数据共同题与全量类型信息")
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--human-file", default="转录数据/语音转录.xlsx")
    parser.add_argument("--llm-file", default="转录数据/LLM转录.xlsx")
    parser.add_argument("--output-file", default="转录数据/信息统计.txt")
    parser.add_argument("--human-sheet", default="Sheet1")
    parser.add_argument("--llm-sheet", default="Sheet1")
    parser.add_argument("--sample-size", type=int, default=10)
    parser.add_argument("--seed", type=int, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = parse_args()
    out_path = run(cli_args)
    print(f"统计完成: {out_path}")
