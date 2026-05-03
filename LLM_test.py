from __future__ import annotations

import sys

from llm_experiment_core import build_common_arg_parser, run_experiment


FORMAL_COUNT = 360
FORMAL_OUTPUT_FILE = "LLM_qwen2.5-vl-72b-instruct.txt"


def main() -> None:
    parser = build_common_arg_parser(
        "Formal LLM experiment script (full 360 questions)."
    )
    args = parser.parse_args()

    try:
        code = run_experiment(
            run_label="formal",
            total_count=FORMAL_COUNT,
            output_filename=FORMAL_OUTPUT_FILE,
            seed=args.seed,
            model=args.model,
            base_url=args.base_url,
            output_dir=args.output_dir,
            request_timeout=args.request_timeout,
            request_retries=args.request_retries,
            resume=args.resume,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"运行失败: {exc}")
        code = 1

    sys.exit(code)


if __name__ == "__main__":
    main()
