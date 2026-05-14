import pandas as pd
import numpy as np
from scipy import stats
from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM


# =========================
# 0. 显示设置
# =========================

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 240)
pd.set_option("display.max_colwidth", None)


# =========================
# 1. 读取数据
# =========================

file_path = "classifier_2026.xlsx"

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
# 3. 筛选量词任务
# =========================

df = data[data[condition_col] == "量词任务"].copy()

print("量词任务原始数据量：", len(df))


# =========================
# 4. 合并有生命性信息
# =========================

material_small = material[[question_id_col, animacy_col]].drop_duplicates()

df = df.merge(
    material_small,
    on=question_id_col,
    how="left"
)

missing_animacy = df[animacy_col].isna().sum()
print("合并后有生命性缺失数量：", missing_animacy)

if missing_animacy > 0:
    print("警告：存在 Material 中无法匹配的 question_id")
    print(df[df[animacy_col].isna()][question_id_col].unique())


# =========================
# 5. 构造模型变量
# =========================

# 从 test_id 中提取被试编号
df["subject_id"] = df[test_id_col].astype(str).str.split("_").str[0]

# 题目编号
df["item_id"] = df[question_id_col].astype(str)

# 名词类型
df["noun_type"] = df[noun_type_col].astype(str)

# 有生命性
df["animacy"] = df[animacy_col].astype(str)

# 清理量词内容
df["classifier_content_clean"] = (
    df[classifier_content_col]
    .astype(str)
    .str.strip()
)

# =========================
# 6. 重新编码因变量
# =========================
# 原逻辑：
#   普通量词 = 0
#   特殊量词 = 1
#
# 新逻辑：
#   “个” = 通用量词 = 0
#   有生命性中的“只” = 通用量词 = 0
#   其他特殊量词 = 1

df["is_special_recode"] = np.nan

# 先根据原来的量词类型编码
df.loc[
    df[classifier_type_col].astype(str).str.contains("特殊", na=False),
    "is_special_recode"
] = 1

df.loc[
    df[classifier_type_col].astype(str).str.contains("普通|通用", na=False),
    "is_special_recode"
] = 0

# 明确把“个”当作通用量词
df.loc[
    df["classifier_content_clean"] == "个",
    "is_special_recode"
] = 0

# 关键修改：有生命性图片中的“只”也当作通用量词
df.loc[
    (df["animacy"] == "有生命性") &
    (df["classifier_content_clean"] == "只"),
    "is_special_recode"
] = 0


# =========================
# 7. 检查重新编码情况
# =========================

print()
print("重新编码规则：")
print("特殊量词 = 1")
print("通用量词 = 0")
print("其中：'个' 总是通用量词；有生命性图片中的 '只' 也被视为通用量词。")
print()

print("重新编码后的因变量分布：")
print(df["is_special_recode"].value_counts(dropna=False))
print()

print("被重新编码为通用量词的有生命性 '只' 的数量：")
n_zhi_animacy = (
    (df["animacy"] == "有生命性") &
    (df["classifier_content_clean"] == "只")
).sum()
print(n_zhi_animacy)
print()

print("按有生命性和量词内容查看 '只' 的分布：")
print(
    df[df["classifier_content_clean"] == "只"]
    .groupby(["animacy", "classifier_content_clean"])
    .size()
    .reset_index(name="count")
    .to_string(index=False)
)
print()


# =========================
# 8. 清理进入模型的数据
# =========================

df_model = df.dropna(
    subset=[
        "is_special_recode",
        "noun_type",
        "animacy",
        "subject_id",
        "item_id"
    ]
).copy()

df_model["is_special_recode"] = df_model["is_special_recode"].astype(int)

print("进入模型的数据量：", len(df_model))
print("被试数量：", df_model["subject_id"].nunique())
print("题目数量：", df_model["item_id"].nunique())
print()


# =========================
# 9. 描述统计
# =========================

summary = (
    df_model
    .groupby(["noun_type", "animacy"])["is_special_recode"]
    .agg(["count", "sum", "mean"])
    .reset_index()
)

summary = summary.rename(columns={
    "count": "总反应数",
    "sum": "特殊量词次数_重编码",
    "mean": "特殊量词比例_重编码"
})

summary["特殊量词比例_重编码"] = summary["特殊量词比例_重编码"].round(4)

print("描述统计：")
print(summary.to_string(index=False))
print()


# =========================
# 10. 构建二项混合效应 Logistic 模型
# =========================

formula = "is_special_recode ~ C(noun_type) * C(animacy)"

vc_formulas = {
    "subject": "0 + C(subject_id)",
    "item": "0 + C(item_id)"
}

model = BinomialBayesMixedGLM.from_formula(
    formula,
    vc_formulas,
    df_model
)

print("开始拟合模型...")
result = model.fit_vb()

print()
print("模型结果：")
print(result.summary())
print()


# =========================
# 11. 计算并打印固定效应结果
# =========================

fe_names = model.exog_names
fe_mean = result.fe_mean
fe_sd = result.fe_sd

or_table = pd.DataFrame({
    "term": fe_names,
    "Est_coef_logit": fe_mean,
    "SE_or_PostSD": fe_sd
})

or_table["z_approx"] = or_table["Est_coef_logit"] / or_table["SE_or_PostSD"]
or_table["p_approx"] = 2 * (1 - stats.norm.cdf(np.abs(or_table["z_approx"])))

or_table["OR"] = np.exp(or_table["Est_coef_logit"])
or_table["CI_lower"] = np.exp(or_table["Est_coef_logit"] - 1.96 * or_table["SE_or_PostSD"])
or_table["CI_upper"] = np.exp(or_table["Est_coef_logit"] + 1.96 * or_table["SE_or_PostSD"])

def format_p(p):
    if p < 0.001:
        return "< .001"
    else:
        return f"{p:.4f}"

or_table["p_print"] = or_table["p_approx"].apply(format_p)

or_table_print = or_table[
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

print("固定效应结果，包括近似 p 值：")
print(or_table_print.round(4).to_string(index=False))
print()


# =========================
# 12. 单独打印交互项
# =========================

interaction_table = or_table[
    or_table["term"].str.contains(":", regex=False)
].copy()

print("交互项结果：")
print(
    interaction_table[
        [
            "term",
            "Est_coef_logit",
            "SE_or_PostSD",
            "z_approx",
            "p_print",
            "OR",
            "CI_lower",
            "CI_upper"
        ]
    ].round(4).to_string(index=False)
)
print()


# =========================
# 13. 打印模型说明
# =========================

print("模型公式：")
print("is_special_recode ~ noun_type * animacy + (1 | subject_id) + (1 | item_id)")
print()

print("因变量编码：")
print("特殊量词 = 1")
print("通用量词 = 0")
print()

print("本次重编码规则：")
print("1. '个' 被视为通用量词。")
print("2. 有生命性图片中的 '只' 也被视为通用量词。")
print("3. 其他特殊量词仍被视为特殊量词。")
print()

print("固定效应：")
print("noun_type：名词类型")
print("animacy：图片有无生命性")
print("noun_type:animacy：名词类型与有生命性的交互")
print()

print("随机效应：")
print("subject_id：被试随机截距")
print("item_id：题目 / 图片随机截距")
print()

print("注意：")
print("这里的 p_approx 是基于 BinomialBayesMixedGLM 后验均值和后验标准差计算的近似 Wald p 值。")
print("如果用于正式论文，建议说明该 p 值为 approximate p-value，或者使用 R 的 lme4::glmer 获得传统频率学 p 值。")