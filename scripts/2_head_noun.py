import pandas as pd
import numpy as np
from scipy import stats
from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM


# =========================
# 0. 显示设置
# =========================

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 280)
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

classifier_type_col = "量词类型"
noun_type_col = "名词类型"
animacy_col = "有无生命性"

required_data_cols = [
    test_id_col,
    question_id_col,
    condition_col,
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
# 3. 筛选名词任务
# =========================

df = data[data[condition_col] == "名词任务"].copy()

print("名词任务原始数据量：", len(df))
print()


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

print()


# =========================
# 5. 构造模型变量
# =========================

# 从 test_id 中提取被试编号
df["subject_id"] = df[test_id_col].astype(str).str.split("_").str[0]

# 题目编号
df["item_id"] = df[question_id_col].astype(str)

# 量词类型
df["classifier_type"] = df[classifier_type_col].astype(str).str.strip()

# 名词类型
df["noun_type"] = df[noun_type_col].astype(str).str.strip()

# 有生命性
df["animacy"] = df[animacy_col].astype(str).str.strip()

# 只保留三类名词类型
valid_noun_types = ["上位词", "普通词", "下位词"]

df_model_base = df[df["noun_type"].isin(valid_noun_types)].copy()

df_model_base = df_model_base.dropna(
    subset=[
        "noun_type",
        "classifier_type",
        "animacy",
        "subject_id",
        "item_id"
    ]
).copy()

print("进入分析的数据量：", len(df_model_base))
print("被试数量：", df_model_base["subject_id"].nunique())
print("题目数量：", df_model_base["item_id"].nunique())
print()

print("名词类型分布：")
print(df_model_base["noun_type"].value_counts())
print()

print("量词类型分布：")
print(df_model_base["classifier_type"].value_counts())
print()

print("有生命性分布：")
print(df_model_base["animacy"].value_counts())
print()


# =========================
# 6. 描述统计
# =========================

summary_counts = (
    df_model_base
    .groupby(["classifier_type", "animacy", "noun_type"])
    .size()
    .reset_index(name="count")
)

summary_totals = (
    df_model_base
    .groupby(["classifier_type", "animacy"])
    .size()
    .reset_index(name="total")
)

summary = summary_counts.merge(
    summary_totals,
    on=["classifier_type", "animacy"],
    how="left"
)

summary["proportion"] = summary["count"] / summary["total"]

print("描述统计：量词类型 × 有生命性 下各名词类型比例")
print(
    summary
    .sort_values(["classifier_type", "animacy", "noun_type"])
    .round(4)
    .to_string(index=False)
)
print()


# =========================
# 7. 定义函数：拟合二项混合效应 Logistic 模型
# =========================

def fit_binary_mixed_model(
    data,
    positive_noun_type,
    reference_noun_type
):
    """
    比较某一类名词类型 vs 参考名词类型。

    positive_noun_type 编码为 1
    reference_noun_type 编码为 0

    例如：
    positive_noun_type = "普通词", reference_noun_type = "上位词"
    表示普通词 vs 上位词。
    """

    print("=" * 110)
    print(f"模型：{positive_noun_type} vs {reference_noun_type}")
    print("=" * 110)

    # 只保留这两类
    df_pair = data[
        data["noun_type"].isin([positive_noun_type, reference_noun_type])
    ].copy()

    # 因变量编码
    df_pair["y"] = np.where(
        df_pair["noun_type"] == positive_noun_type,
        1,
        0
    )

    print("进入该模型的数据量：", len(df_pair))
    print("因变量编码：")
    print(f"{positive_noun_type} = 1")
    print(f"{reference_noun_type} = 0")
    print()

    print("因变量分布：")
    print(
        df_pair["y"].value_counts()
        .rename(index={0: reference_noun_type, 1: positive_noun_type})
    )
    print()

    # 该二分类模型的描述统计
    pair_summary = (
        df_pair
        .groupby(["classifier_type", "animacy"])["y"]
        .agg(["count", "sum", "mean"])
        .reset_index()
    )

    pair_summary = pair_summary.rename(columns={
        "count": "总反应数",
        "sum": f"{positive_noun_type}次数",
        "mean": f"{positive_noun_type}比例"
    })

    pair_summary[f"{positive_noun_type}比例"] = pair_summary[f"{positive_noun_type}比例"].round(4)

    print("该二分类模型的描述统计：")
    print(pair_summary.to_string(index=False))
    print()

    # 固定效应：量词类型 * 有生命性
    formula = "y ~ C(classifier_type) * C(animacy)"

    # 随机效应：被试随机截距 + 题目随机截距
    vc_formulas = {
        "subject": "0 + C(subject_id)",
        "item": "0 + C(item_id)"
    }

    model = BinomialBayesMixedGLM.from_formula(
        formula,
        vc_formulas,
        df_pair
    )

    print("开始拟合模型...")
    result = model.fit_vb()

    print()
    print("模型原始结果：")
    print(result.summary())
    print()

    # 固定效应结果
    fe_names = model.exog_names
    fe_mean = result.fe_mean
    fe_sd = result.fe_sd

    result_table = pd.DataFrame({
        "term": fe_names,
        "Est_coef_logit": fe_mean,
        "SE_or_PostSD": fe_sd
    })

    # 近似 Wald z 和近似 p
    result_table["z_approx"] = (
        result_table["Est_coef_logit"] /
        result_table["SE_or_PostSD"]
    )

    result_table["p_approx"] = 2 * (
        1 - stats.norm.cdf(np.abs(result_table["z_approx"]))
    )

    # OR 与近似 95% CI
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

    result_table_print = result_table[
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
    print(result_table_print.round(4).to_string(index=False))
    print()

    # 单独打印交互项
    interaction_table = result_table[
        result_table["term"].str.contains(":", regex=False)
    ].copy()

    print("交互项结果：")
    if len(interaction_table) > 0:
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
    else:
        print("没有交互项。")
    print()

    print("模型公式：")
    print(
        f"{positive_noun_type} vs {reference_noun_type}: "
        "y ~ classifier_type * animacy + (1 | subject_id) + (1 | item_id)"
    )
    print()

    return model, result, result_table


# =========================
# 8. 拟合三个模型
# =========================

# 模型 1：普通词 vs 上位词
model_common_vs_super, result_common_vs_super, table_common_vs_super = fit_binary_mixed_model(
    data=df_model_base,
    positive_noun_type="普通词",
    reference_noun_type="上位词"
)

# 模型 2：下位词 vs 上位词
model_sub_vs_super, result_sub_vs_super, table_sub_vs_super = fit_binary_mixed_model(
    data=df_model_base,
    positive_noun_type="下位词",
    reference_noun_type="上位词"
)

# 模型 3：普通词 vs 下位词
model_common_vs_sub, result_common_vs_sub, table_common_vs_sub = fit_binary_mixed_model(
    data=df_model_base,
    positive_noun_type="普通词",
    reference_noun_type="下位词"
)


# =========================
# 9. 汇总三个模型的固定效应结果
# =========================

table_common_vs_super_out = table_common_vs_super.copy()
table_common_vs_super_out["contrast"] = "普通词 vs 上位词"

table_sub_vs_super_out = table_sub_vs_super.copy()
table_sub_vs_super_out["contrast"] = "下位词 vs 上位词"

table_common_vs_sub_out = table_common_vs_sub.copy()
table_common_vs_sub_out["contrast"] = "普通词 vs 下位词"

combined_table = pd.concat(
    [
        table_common_vs_super_out,
        table_sub_vs_super_out,
        table_common_vs_sub_out
    ],
    ignore_index=True
)

combined_table = combined_table[
    [
        "contrast",
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
]

print("=" * 110)
print("三个模型固定效应汇总：")
print("=" * 110)
print(combined_table.round(4).to_string(index=False))
print()


# =========================
# 10. 只汇总三个模型中的交互项
# =========================

interaction_combined = combined_table[
    combined_table["term"].str.contains(":", regex=False)
].copy()

print("=" * 110)
print("三个模型交互项汇总：")
print("=" * 110)
print(interaction_combined.round(4).to_string(index=False))
print()


# =========================
# 11. 分析说明
# =========================

print("分析说明：")
print("本分析针对名词任务。")
print("因变量是被试填写的名词类型，包括：上位词、普通词、下位词。")
print("由于名词类型是三分类变量，而 Python 中混合效应多项 Logistic 模型支持有限，")
print("这里采用三个成对二项混合效应 Logistic 模型进行分析：")
print("1. 普通词 vs 上位词")
print("2. 下位词 vs 上位词")
print("3. 普通词 vs 下位词")
print()

print("每个模型的固定效应：")
print("classifier_type：量词类型")
print("animacy：图片有无生命性")
print("classifier_type:animacy：量词类型与有生命性的交互")
print()

print("每个模型的随机效应：")
print("subject_id：被试随机截距")
print("item_id：题目 / 图片随机截距")
print()

print("解释重点：")
print("在每个二分类模型中，Est_coef_logit > 0 表示更倾向于 positive_noun_type。")
print("Est_coef_logit < 0 表示更倾向于 reference_noun_type。")
print("OR > 1 表示更倾向于 positive_noun_type。")
print("OR < 1 表示更倾向于 reference_noun_type。")
print()

print("注意：")
print("这里的 p_approx 是基于 BinomialBayesMixedGLM 后验均值和后验标准差计算的近似 Wald p 值。")
print("如果用于正式论文，建议说明该 p 值为 approximate p-value，或者使用 R 的多项/二项混合效应模型进行确认。")