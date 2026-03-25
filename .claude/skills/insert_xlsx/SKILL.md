---
name: insert_xlsx
description: '将程序转录文本写入Excel/XLSX指定列。自动处理 translation 下全部由 trans.py 生成的 txt，按录音文件名匹配 xlsx 对应行后写入转录文本。触发词：insert xlsx、translation txt 入表、按录音文件名匹配、批量 txt 写入。'
argument-hint: 'column=<单个列名> file=<.xlsx路径可选,未提供需确认> sheet=<可选> create_column=true|false'
user-invocable: true
---

# insert_xlsx

## 目标
将 translation 下全部 trans.py 转录 txt 中的文本，按录音文件名匹配到 xlsx 对应行，并写入你指定的单个列。

## 核心约束
- 每次调用只写入一列，不做多列同时写入。
- 仅处理 .xlsx 文件。
- 固定使用 translation 目录下全部 .txt 文件作为写入来源。
- 所有写入均在原文件内就地保存，不生成任何新文件或副本。
- 即使某条转录文本为空，也必须保留并写入对应行的空单元格。
- 所有待写入文本在落表前必须先转换为简体中文。
- 行匹配固定基于 xlsx 第2列（B列）中的录音文件名。
- 每次处理某个 txt 之前，必须先告知用户当前将要处理的 txt 文件名。
- 当未提供 file 参数时，必须先让用户明确确认目标 xlsx 文件，禁止根据上下文自动猜测。

## 何时使用
- 你希望从 trans.py 的 txt 自动提取转录文本并回填到 xlsx。
- 你希望按录音文件名自动匹配到正确行，而不是手动指定行号。
- 你希望一次处理多个 txt 文件。

## 输入约定
- 必填
1. column: 目标列名，例如 转录文本、摘要、关键词。
- 选填
1. file: 目标xlsx路径。未提供时，必须先让用户从候选xlsx中明确确认目标文件。
2. create_column: true 或 false，默认 true。
3. sheet: 工作表名，可选；未提供时使用第一个工作表。

## 多 txt 处理规则
- 固定扫描 translation 目录下全部 .txt 并按文件名排序后依次处理。
- 在开始处理每个 txt 前，必须先向用户告知当前即将处理的 txt 文件名。
- 每个 txt 内可提取多个 文件名-转录文本 对。
- 多个 txt 出现同一录音文件名时，默认 first-win（首次出现优先），后续同名记录跳过并计入冲突报告。

## trans.py 转录 txt 识别规则
- 采用成对解析：
- 文件名行：匹配 ^\[\d+/\d+\]\s*文件:\s*(.*)$，得到 recording_name。
- 转录行：匹配 ^转录:\s*(.*)$，得到 transcript。
- 一条有效记录由最近一次 recording_name 与其后的 transcript 组成。
- 空值规则：
- transcript 为空字符串时，保留为空字符串。
- transcript 为 (空结果/可能是静音) 时，转换为空字符串。
- 忽略其它非转录业务行，如 学生目录:、音频文件数:、错误:、统计:、分隔线。

## 简体转换规则
- 在写入 xlsx 前，对每一条文本执行繁体到简体转换（t2s）。
- 推荐转换方式：OpenCC（t2s）。
- 转换时保留原有换行与标点，不做额外语义改写。
- 空字符串在转换后仍为空字符串，并照常写入对应行。

## 文件名匹配规则
- 在 xlsx 第2列（B列）中，从第2行开始读取录音文件名并建立 行号索引。
- 文件名匹配默认使用精确匹配。
- 匹配前进行规范化：
- 路径分隔符统一为 /。
- 去除首尾空白。
- 文件扩展名大小写不敏感。
- 若同一录音文件名在 xlsx 中出现多次，默认命中第一行并在 note 中提示重复行。

## 执行流程
1. 解析参数并确认目标文件
- 若 file 提供，使用该路径。
- 若未提供 file，必须列出候选 xlsx 并请求用户明确确认目标文件；未确认则终止。
- 若文件不存在，终止并提示可用文件列表。
- 若文件扩展名不是 .xlsx，终止并提示仅支持 .xlsx。
- 校验必须且仅能写入一个列名参数 column。
- 禁止另存为新文件（不支持 output、save_as、new_file 等参数）。
- 扫描 translation 目录下全部 .txt 文件列表。
- 若未发现任何 .txt，终止并提示 translation 目录下无可处理 txt。

2. 解析 txt 并提取记录
- 逐个 txt 处理：每处理一个 txt 前先告知用户当前文件名。
- 从扫描到的 txt 提取 文件名-转录文本 记录。
- 合并多 txt 记录并处理同名冲突（first-win）。
- 若最终没有任何可处理记录，终止并提示检查 txt 内容。

3. 文本规范化（写入前）
- 对每条转录文本执行简体转换（t2s）。
- 空字符串保持为空字符串。

4. 定位工作表、目标列、文件名列
- 读取首行作为表头。
- 仅使用精确匹配定位 column。
- 若未找到且 create_column=true，则在最后一列新建该表头。
- 若未找到且 create_column=false，终止并返回可选列名。
- 在第2列（B列）从第2行起建立 录音文件名 -> 行号 的索引。

5. 按录音文件名匹配并写入
- 对每条记录，用 recording_name 在索引中查找目标行。
- 命中时：将 transcript 写入该行的目标列。
- 未命中时：记录为 unmatched，不自动新增行。
- transcript 为空字符串时：在目标单元格写入空值（清空或保持空白）。

6. 写入与保存
- 执行写入，保持其它列不变。
- 仅保存到原文件（in-place），不创建新文件名。
- 返回结果摘要：文件、sheet、列名、命中写入数、未命中数、冲突数、写入字符数。

## 质量检查
- 列名命中结果明确：已命中或已创建。
- 每条写入记录都有 文件名 -> 行号 的匹配依据。
- 未改动非目标列数据。
- 写入后可抽样核对：xlsx 文件名列 与 txt 文件名 一致时，对应行转录文本一致。

## 异常处理
- 列名重复：默认使用从左到右第一个同名列，并在结果中提示存在重复列。
- translation 目录下无 .txt：拒绝并提示先生成或放入 trans.py 转录 txt。
- 未提供 file 且用户未明确确认目标 xlsx：拒绝处理并提示先确认目标文件。
- txt 中未识别到任何有效 文件: + 转录: 记录：拒绝并提示检查 trans.py 输出文件内容。
- 简体转换组件不可用：拒绝写入并提示先安装或启用 t2s 转换能力（如 OpenCC）。
- xlsx 中第2列（B列）缺少录音文件名内容：拒绝并提示检查文件结构。
- txt 文件名记录在 xlsx 中未命中：不报错中断，计入 unmatched 列表并在结果中返回。
- 非 xlsx 文件：拒绝处理并提示转换为 .xlsx。
- 请求生成新文件或副本：拒绝并提示该技能只支持原文件就地写入。
- 文件被占用：提示关闭Excel后重试。

## 输出格式
每次执行后返回以下信息：
1. file: 实际写入文件路径
2. sheet: 实际工作表
3. column: 目标列名
4. filename_column: 固定为 2（B列）
5. rows_written: 成功写入条数
6. unmatched_count: 未匹配到 xlsx 行的条数
7. duplicate_source_count: 多 txt 同名冲突条数
8. chars: 写入文本总长度
9. note: 是否创建新列、是否检测到重复列
10. write_mode: 固定为 in-place
11. source: 固定为 translation_all_txt
12. source_files: 实际读取的 txt 文件列表（translation 下全部 .txt）
13. normalize: 固定为 t2s（繁转简）
14. unmatched_files: 未命中的录音文件名列表
15. confirmed_file: 用户最终确认的 xlsx 文件路径
16. announced_files: 已在处理前告知用户的 txt 文件列表

## 示例调用
- /insert_xlsx column=转录文本 file=result_data.xlsx
- /insert_xlsx column=转录文本 file=result_data.xlsx sheet=Sheet1
- /insert_xlsx column=转录文本
