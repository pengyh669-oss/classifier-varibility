from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from openai import OpenAI

# 加载环境变量：优先加载脚本同级目录的 .env，其次加载当前工作目录
_script_dir = Path(__file__).parent
_env_path = _script_dir / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()  # 回退到当前工作目录

# 默认配置
DEFAULT_INPUT_DIR = Path("translation") / "calssifer_text"
DEFAULT_INPUT_DIR_FALLBACK = Path("translation") / "calssifer_text"  # 与默认相同，保留回退结构
DEFAULT_OUTPUT_DIR = Path("translation") / "classified_classifer"
DEFAULT_BASE_URL = "https://api.zhizengzeng.com/v1"
DEFAULT_API_KEY = ""  # 请设置环境变量 OPENAI_API_KEY 或通过 --api-key 传入
DEFAULT_MODEL = "gpt-5.4"
DEFAULT_TEMPERATURE = 0.1
DEFAULT_CHUNK_SIZE = 20  # 初始批处理大小
DEFAULT_RETRIES = 3
DEFAULT_DELAY_SECONDS = 0.5

# 量词分类类型
ClassifierType = Literal["普通量词", "特殊量词"]
VALID_CLASSIFIERS = {"普通量词", "特殊量词"}

SYSTEM_PROMPT = """
你是一个语言学专家，专门分析中文量词。
你需要判断每个量词属于：
1. 普通量词：仅限“个”或“只”
2. 特殊量词：除“个”“只”以外的量词，基本都归为特殊量词

判断标准：
- 若量词是“个”或“只”，返回“普通量词”
- 其余量词统一返回“特殊量词”
只能返回"普通量词"或"特殊量词"两种值之一。
"""

USER_PROMPT_TEMPLATE = """
请分析以下量词的类型，返回JSON格式结果：
{{
  "results": [
        {{"classifier": "个", "type": "普通量词"}},
        {{"classifier": "只", "type": "普通量词"}},
        {{"classifier": "条", "type": "特殊量词"}}
  ]
}}

规则：
1. 每个量词必须有一个对应的分类结果
2. 分类只能是"普通量词"或"特殊量词"
3. 不要添加任何解释性文字
4. 保持JSON格式严格正确

输入量词列表：
{classifiers}
"""




def read_noun_file(file_path: Path) -> list[tuple[int, str]]:
    """
    读取名词文件，返回(行号, 名词)列表

    输入格式：每行"行号→名词"
    输出：[(1, "狗"), (2, "鸡"), ...]
    """
    result = []
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines()

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 解析"行号→名词"格式
            if "→" in line:
                parts = line.split("→", 1)
                if len(parts) == 2:
                    line_no_str = parts[0].strip()
                    noun = parts[1].strip()

                    try:
                        line_no = int(line_no_str)
                        if noun:  # 只添加非空名词
                            result.append((line_no, noun))
                    except ValueError:
                        # 如果行号不是数字，使用行索引
                        if noun:
                            result.append((len(result) + 1, noun))
            else:
                # 如果没有箭头，假设整行是名词
                if line:
                    result.append((len(result) + 1, line))

    except Exception as e:
        print(f"读取文件 {file_path} 时出错: {e}")
        raise

    return result


def strip_code_fence(text: str) -> str:
    """去除JSON响应中的代码块标记"""
    content = text.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    return content


def parse_classification_response(content: str) -> list[dict[str, str]]:
    """解析API返回的分类结果JSON"""
    cleaned = strip_code_fence(content)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # 尝试从文本中提取JSON
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError(f"模型返回的内容不是有效 JSON: {cleaned[:200]}...") from None
        data = json.loads(cleaned[start : end + 1])

    if not isinstance(data, dict) or "results" not in data:
        raise ValueError(f"模型返回缺少 results 字段: {cleaned[:200]}...")

    results = data["results"]
    if not isinstance(results, list):
        raise ValueError(f"模型返回的 results 不是列表: {cleaned[:200]}...")

    normalized: list[dict[str, str]] = []
    for item in results:
        if not isinstance(item, dict):
            raise ValueError(f"模型返回的元素不是对象: {item}")

        classifier = item.get("classifier", "")
        classifier_type = item.get("type", "")

        if not isinstance(classifier, str):
            classifier = str(classifier)
        if not isinstance(classifier_type, str):
            classifier_type = str(classifier_type)

        # 验证分类值是否有效
        if classifier_type not in VALID_CLASSIFIERS:
            raise ValueError(
                f"无效的分类值: '{classifier_type}'，应为: {VALID_CLASSIFIERS}"
            )

        normalized.append({"classifier": classifier.strip(), "type": classifier_type})

    return normalized


def classify_batch(
    client: OpenAI,
    classifiers: list[str],
    line_nos: list[int],
    *,
    model: str,
    temperature: float,
    retries: int,
    retry_delay: float,
) -> list[tuple[int, str]]:
    """
    批处理分类函数，返回(行号, 分类结果)

    Args:
        client: OpenAI客户端
        nouns: 名词列表
        line_nos: 对应的行号列表
        model: 模型名称
        temperature: 温度
        retries: 重试次数
        retry_delay: 重试延迟

    Returns:
        [(行号, 分类结果), ...]
    """
    # 构建量词列表字符串
    classifiers_list = "\n".join([f"{i+1}. {c}" for i, c in enumerate(classifiers)])
    user_prompt = USER_PROMPT_TEMPLATE.format(classifiers=classifiers_list)

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

            # 解析响应
            parsed_results = parse_classification_response(content)

            # 验证结果数量匹配
            if len(parsed_results) != len(classifiers):
                raise ValueError(
                    f"模型返回条数不匹配，期望 {len(classifiers)} 条，实际 {len(parsed_results)} 条"
                )

            # 构建(行号, 分类结果)列表
            results = []
            for i, item in enumerate(parsed_results):
                if i < len(line_nos):
                    results.append((line_nos[i], item["type"]))
                else:
                    # 如果行号不足，使用索引
                    results.append((i + 1, item["type"]))

            return results

        except Exception as exc:
            last_error = exc
            print(f"第 {attempt} 次尝试失败: {exc}")
            if attempt == retries:
                break
            time.sleep(retry_delay)

    assert last_error is not None
    raise last_error


def chunk_items(
    items: list[tuple[int, str]],
    chunk_size: int
) -> list[list[tuple[int, str]]]:
    """将(行号, 名词)列表分块"""
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def process_one_file(
    client: OpenAI,
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
    """
    处理单个文件

    Returns:
        (总行数, 成功处理行数)
    """
    # 读取名词文件
    noun_items = read_noun_file(input_file)
    if not noun_items:
        print(f"文件 {input_file.name} 为空，跳过")
        # 创建空输出文件
        output_file.write_text("", encoding="utf-8")
        return 0, 0

    total_items = len(noun_items)
    print(f"  读取到 {total_items} 个名词")

    # 准备结果列表
    results = [""] * total_items

    # 分批次处理
    chunks = chunk_items(noun_items, chunk_size)
    total_chunks = len(chunks)

    for chunk_idx, chunk in enumerate(chunks, start=1):
        # 提取名词和行号
        line_nos = [item[0] for item in chunk]
        classifiers = [item[1] for item in chunk]

        try:
            batch_results = classify_batch(
                client,
                classifiers,
                line_nos,
                model=model,
                temperature=temperature,
                retries=retries,
                retry_delay=retry_delay,
            )

            # 存储结果
            for line_no, classification_type in batch_results:
                # 找到在原始列表中的位置
                for i, (orig_line_no, _) in enumerate(noun_items):
                    if orig_line_no == line_no:
                        if i < len(results):
                            results[i] = hierarchy
                        break

            print(f"  批次 {chunk_idx}/{total_chunks} 完成 | {input_file.name}")

        except Exception as e:
            print(f"  批次 {chunk_idx}/{total_chunks} 失败: {e}")
            # 标记失败的行
            for line_no, _ in chunk:
                for i, (orig_line_no, _) in enumerate(noun_items):
                    if orig_line_no == line_no and i < len(results):
                        results[i] = "ERROR"
                        break

        # 请求间隔
        if request_delay > 0:
            time.sleep(request_delay)

    # 写入输出文件
    output_lines = []
    for (line_no, noun), hierarchy in zip(noun_items, results, strict=True):
        if hierarchy and hierarchy != "ERROR":
            output_lines.append(f"{noun}->{hierarchy}")
        else:
            # 如果分类失败，保留名词但标记错误
            output_lines.append(f"{noun}->ERROR")

    output_file.write_text("\n".join(output_lines), encoding="utf-8")

    # 统计成功处理的行数
    successful = sum(1 for h in results if h and h != "ERROR")
    return total_items, successful


def run(
    *,
    api_key: str,
    base_url: str,
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
    """主运行函数"""
    if not input_dir.exists() and input_dir == DEFAULT_INPUT_DIR and DEFAULT_INPUT_DIR_FALLBACK.exists():
        print(f"默认目录不存在，自动回退到: {DEFAULT_INPUT_DIR_FALLBACK}")
        input_dir = DEFAULT_INPUT_DIR_FALLBACK

    if not input_dir.exists():
        raise FileNotFoundError(f"输入目录不存在: {input_dir}")

    # 查找所有txt文件
    txt_files = sorted(input_dir.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(f"在目录中没有找到 txt 文件: {input_dir}")

    if limit is not None:
        txt_files = txt_files[:limit]
        print(f"限制处理前 {limit} 个文件")

    # 创建输出目录
    output_dir.mkdir(parents=True, exist_ok=True)

    # 初始化OpenAI客户端
    client = OpenAI(api_key=api_key, base_url=base_url)

    # 统计信息
    processed_files = 0
    skipped_files = 0
    total_lines = 0
    total_successful = 0

    print(f"开始处理 {len(txt_files)} 个文件...")

    for txt_file in txt_files:
        output_file = output_dir / txt_file.name  # 保持相同文件名

        if output_file.exists() and not overwrite:
            skipped_files += 1
            print(f"跳过已存在文件: {output_file.name}")
            continue

        print(f"处理文件: {txt_file.name}")

        try:
            line_count, successful_count = process_one_file(
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
            total_successful += successful_count

            print(f"  完成: {output_file.name} | 总行数: {line_count} | 成功: {successful_count}")

        except Exception as e:
            print(f"  处理文件 {txt_file.name} 时出错: {e}")
            skipped_files += 1

    # 输出统计信息
    print("\n处理完成")
    print(f"输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")
    print(f"处理文件数: {processed_files}")
    print(f"跳过文件数: {skipped_files}")
    print(f"总行数: {total_lines}")
    print(f"成功处理行数: {total_successful}")
    if total_lines > 0:
        success_rate = (total_successful / total_lines) * 100
        print(f"成功率: {success_rate:.1f}%")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "读取 translation/calssifer_text 下的 txt 文件，调用 OpenAI 兼容 API "
            "判断每行量词属于普通量词还是特殊量词，并将结果写入 translation/classified_nouns。"
        )
    )

    parser.add_argument(
        "--api-key",
        default=os.getenv("OPENAI_API_KEY", DEFAULT_API_KEY),
        help="OpenAI API Key，默认优先读取环境变量 OPENAI_API_KEY，否则使用代码内默认值",
    )

    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API基础URL，默认: {DEFAULT_BASE_URL}",
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
        help=f"每次请求包含的量词数，默认: {DEFAULT_CHUNK_SIZE}",
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
        raise ValueError("缺少 API Key，请设置环境变量 OPENAI_API_KEY 或通过 --api-key 传入")

    if args.chunk_size <= 0:
        raise ValueError("--chunk-size 必须大于 0")

    if args.retries <= 0:
        raise ValueError("--retries 必须大于 0")

    run(
        api_key=args.api_key,
        base_url=args.base_url,
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
