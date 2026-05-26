import pandas as pd
import numpy as np
from scipy import stats
from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM


# =========================
# 0. 显示设置
# =========================

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 320)
pd.set_option("display.max_colwidth", None)


# =========================
# 1. 读取数据
# =========================

file_path = "转录数据/classifier_2026_彭永恒.xlsx"

sheets = pd.read_excel(file_path, sheet_name=None)

data_sheet_name = None
material_sheet_name = None

for name in sheets.keys():
    lower_name = name.lower()
    if lower_name == "data":
        data_sheet_name = name
    if lower_name == "material":
        material_sheet_name = name

if data_sheet_name is None:
    raise ValueError("没有找到名为 data 的工作表")

if material_sheet_name is None:
    raise ValueError("没有找到名为 Material 的工作表")

data = sheets[data_sheet_name].copy()
material = sheets[material_sheet_name].copy()

print("data 表字段：")
print(data.columns.tolist())
print()

print("Material 表字段：")
print(material.columns.tolist())
print()


# =========================
# 2. 字段设置
# =========================

test_id_col = "test_id"
question_id_col = "question_id"
condition_col = "实验条件"

classifier_content_col = "量词（内容）"
classifier_type_col = "量词类型"
noun_type_col = "名词类型"

animacy_col = "有无生命性"

required_data_cols = [
    test_id_col,
    question_id_col,
    condition_col,
    classifier_content_col,
    classifier_type_col,
    noun_type_col,
]

required_material_cols = [
    question_id_col,
    animacy_col,
]

for col in required_data_cols:
    if col not in data.columns:
        raise ValueError(f"data 表中缺少字段：{col}")

for col in required_material_cols:
    if col not in material.columns:
        raise ValueError(f"Material 表中缺少字段：{col}")


# =========================
# 3. 合并有生命性信息
# =========================

material_small = material[[question_id_col, animacy_col]].drop_duplicates()

df_all = data.merge(
    material_small,
    on=question_id_col,
    how="left"
)

missing_animacy = df_all[animacy_col].isna().sum()
print("合并后有生命性缺失数量：", missing_animacy)

if missing_animacy > 0:
    print("警告：存在 Material 中无法匹配的 question_id")
    print(df_all[df_all[animacy_col].isna()][question_id_col].unique())

print()


# =========================
# 4. 构造通用变量
# =========================

df_all["subject_id"] = df_all[test_id_col].astype(str).str.split("_").str[0]
df_all["item_id"] = df_all[question_id_col].astype(str)

df_all["task_type"] = df_all[condition_col].astype(str).str.strip()
df_all["noun_type"] = df_all[noun_type_col].astype(str).str.strip()
df_all["animacy"] = df_all[animacy_col].astype(str).str.strip()

df_all["classifier_content_clean"] = (
    df_all[classifier_content_col]
    .astype(str)
    .str.strip()
)

df_all["classifier_type_clean"] = (
    df_all[classifier_type_col]
    .astype(str)
    .str.strip()
)

valid_noun_types = ["上位词", "普通词", "下位词"]


# =========================
# 5. 重新编码因变量
# =========================
# is_special_recode:
#   特殊量词 = 1
#   通用量词 = 0
#
# 编码规则：
#   1. “个”总是通用量词
#   2. 有生命图片中的“只”也视为通用量词
#   3. 原始量词类型中标为普通/通用的量词视为通用量词
#   4. 原始量词类型中标为特殊的量词视为特殊量词
#   5. 最后再覆盖“个”和有生命图片中的“只”为 0

df_all["is_special_recode"] = np.nan

df_all.loc[
    df_all["classifier_type_clean"].str.contains("特殊", na=False),
    "is_special_recode"
] = 1

df_all.loc[
    df_all["classifier_type_clean"].str.contains("普通|通用", na=False),
    "is_special_recode"
] = 0

# “个”总是通用量词
df_all.loc[
    df_all["classifier_content_clean"] == "个",
    "is_special_recode"
] = 0

# 有生命图片中的“只”也视为通用量词
df_all.loc[
    (df_all["animacy"] == "有生命性") &
    (df_all["classifier_content_clean"] == "只"),
    "is_special_recode"
] = 0


print("重新编码规则：")
print("特殊量词 = 1")
print("通用量词 = 0")
print("其中：'个' 总是通用量词；有生命性图片中的 '只' 也被视为通用量词。")
print()

print("全数据中重新编码后的因变量分布：")
print(df_all["is_special_recode"].value_counts(dropna=False))
print()

print("全数据中被重新编码为通用量词的有生命性 '只' 的数量：")
n_zhi_animacy_all = (
    (df_all["animacy"] == "有生命性") &
    (df_all["classifier_content_clean"] == "只")
).sum()
print(n_zhi_animacy_all)
print()


# =========================
# 6. 辅助函数：打印固定效应结果
# =========================

def make_fixed_effect_table(model, result):
    fe_names = model.exog_names
    fe_mean = result.fe_mean
    fe_sd = result.fe_sd

    result_table = pd.DataFrame({
        "term": fe_names,
        "Est_coef_logit": fe_mean,
        "SE_or_PostSD": fe_sd
    })

    result_table["z_approx"] = (
        result_table["Est_coef_logit"] /
        result_table["SE_or_PostSD"]
    )

    result_table["p_approx"] = 2 * (
        1 - stats.norm.cdf(np.abs(result_table["z_approx"]))
    )

    result_table["OR"] = np.exp(result_table["Est_coef_logit"])

    result_table["CI_lower"] = np.exp(
        result_table["Est_coef_logit"] -
        1.96 * result_table["SE_or_PostSD"]
    )

    result_table["CI_upper"] = np.exp(
        result_table["Est_coef_logit"] +
        1.96 * result_table["SE_or_PostSD"]
    )

    def format_p(p):
        if p < 0.001:
            return "< .001"
        else:
            return f"{p:.4f}"

    result_table["p_print"] = result_table["p_approx"].apply(format_p)

    return result_table[
        [
            "term",
            "Est_coef_logit",
            "SE_or_PostSD",
            "z_approx",
            "p_approx",
            "p_print",
            "OR",
            "CI_lower",
            "CI_upper"
        ]
    ].copy()


def print_model_outputs(model_name, model, result, fixed_table):
    print("=" * 120)
    print(model_name)
    print("=" * 120)
    print()

    print("模型原始结果：")
    print(result.summary())
    print()

    print("固定效应结果，包括近似 p 值：")
    print(fixed_table.round(4).to_string(index=False))
    print()

    interaction_table = fixed_table[
        fixed_table["term"].str.contains(":", regex=False)
    ].copy()

    print("交互项结果：")
    if len(interaction_table) > 0:
        print(interaction_table.round(4).to_string(index=False))
    else:
        print("没有交互项。")
    print()


# =========================
# 7. 模型 1：自由描述任务内部模型
# =========================

df_free = df_all[
    df_all["task_type"] == "自由描述任务"
].copy()

df_free = df_free[
    df_free["noun_type"].isin(valid_noun_types)
].copy()

df_free = df_free.dropna(
    subset=[
        "is_special_recode",
        "noun_type",
        "animacy",
        "subject_id",
        "item_id"
    ]
).copy()

df_free["is_special_recode"] = df_free["is_special_recode"].astype(int)

print("=" * 120)
print("模型 1 数据概况：自由描述任务")
print("=" * 120)
print("进入模型 1 的数据量：", len(df_free))
print("被试数量：", df_free["subject_id"].nunique())
print("题目数量：", df_free["item_id"].nunique())
print()

print("模型 1 因变量分布：")
print(df_free["is_special_recode"].value_counts().rename(index={0: "通用量词", 1: "特殊量词"}))
print()

print("模型 1 描述统计：自由描述任务中 noun_type × animacy 下的特殊量词比例")
summary_free = (
    df_free
    .groupby(["noun_type", "animacy"])["is_special_recode"]
    .agg(["count", "sum", "mean"])
    .reset_index()
)

summary_free = summary_free.rename(columns={
    "count": "总反应数",
    "sum": "特殊量词次数",
    "mean": "特殊量词比例"
})

summary_free["特殊量词比例"] = summary_free["特殊量词比例"].round(4)

print(summary_free.to_string(index=False))
print()


formula_model1 = "is_special_recode ~ C(noun_type) * C(animacy)"

vc_formulas_model1 = {
    "subject": "0 + C(subject_id)",
    "item": "0 + C(item_id)"
}

print("开始拟合模型 1...")
model1 = BinomialBayesMixedGLM.from_formula(
    formula_model1,
    vc_formulas_model1,
    df_free
)

result1 = model1.fit_vb()

table1 = make_fixed_effect_table(model1, result1)

print_model_outputs(
    model_name="模型 1：自由描述任务内部模型：is_special_recode ~ noun_type * animacy + (1 | subject_id) + (1 | item_id)",
    model=model1,
    result=result1,
    fixed_table=table1
)


# =========================
# 8. 模型 2：量词任务 vs 自由描述任务比较模型
# =========================

df_compare = df_all[
    df_all["task_type"].isin(["量词任务", "自由描述任务"])
].copy()

df_compare = df_compare[
    df_compare["noun_type"].isin(valid_noun_types)
].copy()

df_compare = df_compare.dropna(
    subset=[
        "is_special_recode",
        "task_type",
        "noun_type",
        "animacy",
        "subject_id",
        "item_id"
    ]
).copy()

df_compare["is_special_recode"] = df_compare["is_special_recode"].astype(int)

print("=" * 120)
print("模型 2 数据概况：量词任务 vs 自由描述任务")
print("=" * 120)
print("进入模型 2 的数据量：", len(df_compare))
print("被试数量：", df_compare["subject_id"].nunique())
print("题目数量：", df_compare["item_id"].nunique())
print()

print("模型 2 任务分布：")
print(df_compare["task_type"].value_counts())
print()

print("模型 2 因变量分布：")
print(df_compare["is_special_recode"].value_counts().rename(index={0: "通用量词", 1: "特殊量词"}))
print()

print("模型 2 描述统计：task_type × noun_type × animacy 下的特殊量词比例")
summary_compare = (
    df_compare
    .groupby(["task_type", "noun_type", "animacy"])["is_special_recode"]
    .agg(["count", "sum", "mean"])
    .reset_index()
)

summary_compare = summary_compare.rename(columns={
    "count": "总反应数",
    "sum": "特殊量词次数",
    "mean": "特殊量词比例"
})

summary_compare["特殊量词比例"] = summary_compare["特殊量词比例"].round(4)

print(
    summary_compare
    .sort_values(["task_type", "noun_type", "animacy"])
    .to_string(index=False)
)
print()


formula_model2 = "is_special_recode ~ C(task_type) * C(noun_type) * C(animacy)"

vc_formulas_model2 = {
    "subject": "0 + C(subject_id)",
    "item": "0 + C(item_id)"
}

print("开始拟合模型 2...")
model2 = BinomialBayesMixedGLM.from_formula(
    formula_model2,
    vc_formulas_model2,
    df_compare
)

result2 = model2.fit_vb()

table2 = make_fixed_effect_table(model2, result2)

print_model_outputs(
    model_name="模型 2：任务比较模型：is_special_recode ~ task_type * noun_type * animacy + (1 | subject_id) + (1 | item_id)",
    model=model2,
    result=result2,
    fixed_table=table2
)


# =========================
# 9. 单独打印模型 2 中与任务差异相关的项
# =========================

print("=" * 120)
print("模型 2 中与任务差异相关的固定效应")
print("=" * 120)

task_related = table2[
    table2["term"].str.contains("task_type", regex=False)
].copy()

print(task_related.round(4).to_string(index=False))
print()


print("=" * 120)
print("模型 2 中三阶交互项")
print("=" * 120)

three_way = table2[
    table2["term"].str.count(":") == 2
].copy()

if len(three_way) > 0:
    print(three_way.round(4).to_string(index=False))
else:
    print("没有三阶交互项。")
print()


# =========================
# 10. 打印模型说明
# =========================

print("=" * 120)
print("模型说明")
print("=" * 120)
print()

print("本代码构建两个模型：")
print("模型 1：自由描述任务内部模型")
print("is_special_recode ~ noun_type * animacy + (1 | subject_id) + (1 | item_id)")
print()
print("模型 2：量词任务 vs 自由描述任务比较模型")
print("is_special_recode ~ task_type * noun_type * animacy + (1 | subject_id) + (1 | item_id)")
print()

print("因变量编码：")
print("特殊量词 = 1")
print("通用量词 = 0")
print()

print("重编码规则：")
print("1. '个' 被视为通用量词。")
print("2. 有生命性图片中的 '只' 也被视为通用量词。")
print("3. 其他特殊量词仍被视为特殊量词。")
print()

print("模型 1 解释重点：")
print("看 C(noun_type)、C(animacy)、C(noun_type):C(animacy)。")
print("它回答：自由描述任务中，名词类型和有生命性是否影响量词选择。")
print()

print("模型 2 解释重点：")
print("重点看所有包含 C(task_type) 的项。")
print("尤其是 C(task_type):C(noun_type):C(animacy) 三阶交互。")
print("如果三阶交互显著，说明自由描述任务和量词任务中，名词类型 × 有生命性的作用模式不同。")
print()

print("注意：")
print("这里的 p_approx 是基于 BinomialBayesMixedGLM 后验均值和后验标准差计算的近似 Wald p 值。")
print("如果用于正式论文，建议说明该 p 值为 approximate p-value，或者使用 R 的 glmer 模型进行确认。")
