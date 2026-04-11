# Output Structure Template

Use this default structure unless the user explicitly asks for another format.

## 1. Scope

- Target files analyzed.
- Assumptions or omitted files.

## 2. System Intent (High-Level)

- 2-5 sentences on what this code is trying to achieve.
- Main runtime path in one paragraph.

## 3. Architecture Map

- Module/component list with one-line responsibilities.
- Key cross-file call chains.
- External dependencies and their role.

## 4. End-to-End Execution Flow

- Numbered sequence from entry point to completion.
- Include branch points, retries, and exits.

## 5. Detailed Logic by Unit

- Organize by class/function/module.
- For each unit, include:
  - Responsibility
  - Input and output
  - Core algorithm/decision logic
  - State mutation or side effects
  - Error and edge-case handling

## 6. Data Flow and State

- Important data structures and field meanings.
- Data lifecycle: where values are created, transformed, validated, and consumed.
- Shared mutable state and synchronization assumptions.

## 7. Branch and Condition Matrix

- Critical conditions and outcomes.
- Explain why each branch exists.
- Mention default and fallback behavior.

## 8. Risks and Hidden Assumptions

- Implicit contracts not enforced by code.
- Potential failure points or brittle areas.
- Concurrency, performance, and maintainability risks (if relevant).

## 9. Quick Recap

- 3-6 concise lines.
- Include "what matters most" for future maintainers.

## Formatting Requirements

- Keep sections in this order unless the user asks otherwise.
- Keep explanations concrete and avoid vague wording.
- Prefer source-aligned naming and terminology.
- Distinguish facts from inferences using labels:
  - `Fact:` directly supported by code.
  - `Inference:` reasonable interpretation from code behavior.
