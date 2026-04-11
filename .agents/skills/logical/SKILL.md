---
name: logical
description: Detailed code-logic decomposition and structured explanation for user-specified source files. Use when Codex needs to read one or more code files and output a clear, highly readable, and comprehensive logic summary, including architecture, control flow, data flow, function/class responsibilities, key branches, and edge-case behavior.
---

# 逻辑总结（Logical）

## 概览（Overview）

Extract and explain the logic of user-specified code files with a consistent, readable structure.
Prioritize correctness, depth, and traceability to concrete code locations.

## 工作流程（Workflow）

1. 确认范围（Confirm Scope）
- Identify the exact target files the user asked to analyze.
- If the request is ambiguous, infer the smallest reasonable file set and state assumptions.

2. 构建上下文（Build Context）
- Read all target files fully before writing the summary.
- Identify entry points, exported APIs, core classes/functions, shared state, external calls, and config dependencies.

3. 重构逻辑链路（Reconstruct Logic）
- Map runtime flow: initialization -> main path -> branch paths -> termination.
- Map data flow: inputs -> transformations -> outputs and side effects.
- Map control flow: conditions, loops, retries, exception paths, and guard clauses.
- Track cross-file call chains and module boundaries.

4. 生成结构化总结（Produce Structured Summary）
- Follow [references/output-structure.md](references/output-structure.md) unless the user gives a custom structure.
- Keep explanations layered: high-level first, then detailed per component.
- Cite file paths and line numbers when useful for traceability.

5. 输出前质量校验（Run a Quality Pass Before Final Output）
- Do not invent behavior. Mark uncertain points as `Needs confirmation`.
- Ensure key branches, side effects, and error paths are covered.
- Rewrite dense explanations for readability.

## 深度规则（Depth Rules）

- Explain both "what it does" and "why this path exists."
- Include hidden behavior: defaults, fallback logic, shared-object mutation, and implicit contracts.
- For each key function/class, cover responsibility, input/output, important branches, state changes, and error handling.
- If files are large, summarize by subsystem first, then drill into hotspots.
- If the user asks for "very detailed," include step-by-step execution narratives for critical flows.

## 可读性规则（Readability Rules）

- Prefer short headings, flat bullets, and compact paragraphs.
- Use clear domain terms and define non-obvious identifiers once.
- Keep naming consistent with source code.
- Distinguish facts from inferences explicitly.
- End with a `Quick Recap` section in 3-6 lines.

## 输出约定（Output Contract）

- Default output language: match the user's language.
- If the user provides a custom structure, follow it while keeping this skill's depth and readability standards.
- If some files are unavailable, report exactly what is missing and provide a partial summary for readable files.

