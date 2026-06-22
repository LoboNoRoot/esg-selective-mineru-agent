from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_settings
from .evaluation import build_evaluation_pack, build_review_page
from .extractor import extract_report
from .pipeline import run_pipeline, scan_only


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Selective MinerU ESG extraction pipeline.")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_cmd = sub.add_parser("scan")
    scan_cmd.add_argument("pdf", type=Path)
    scan_cmd.add_argument("--output", type=Path, required=True)

    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("pdf", type=Path)
    run_cmd.add_argument("--output", type=Path, required=True)
    run_cmd.add_argument("--extract", action="store_true", help="run schema extraction after parsing")
    run_cmd.add_argument("--no-llm", action="store_true", help="build chunks/contexts only, skip LLM calls")

    extract_cmd = sub.add_parser("extract")
    extract_cmd.add_argument("pdf", type=Path)
    extract_cmd.add_argument("--output", type=Path, required=True)
    extract_cmd.add_argument("--no-llm", action="store_true", help="build chunks/contexts only, skip LLM calls")

    review_cmd = sub.add_parser("review", help="build a static HTML review page for one run output")
    review_cmd.add_argument("--run-dir", type=Path, required=True)
    review_cmd.add_argument("--output", type=Path, required=True)

    eval_cmd = sub.add_parser("eval", help="build or summarize a small manual evaluation table")
    eval_cmd.add_argument("--run-dir", type=Path, action="append", required=True, help="repeat for each report run dir")
    eval_cmd.add_argument("--output", type=Path, required=True)
    eval_cmd.add_argument("--sample-size", type=int, default=10)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings()
    if args.command == "scan":
        result = scan_only(args.pdf, args.output, settings)
        if result.get("skipped"):
            skip = result["skip_report"]
            print(f"skipped=true reason_code={skip['reason_code']} reason={skip['reason']}")
            return
        plan = result["parse_plan"]
        print(f"pages={plan['page_count']} mineru_pages={len(plan['mineru_pages'])} visual_fallback={len(plan['visual_fallback_pages'])}")
    elif args.command == "run":
        result = run_pipeline(args.pdf, args.output, settings, extract=args.extract, use_llm=not args.no_llm)
        if result.get("skipped"):
            skip = result["skip_report"]
            print(f"skipped=true reason_code={skip['reason_code']} reason={skip['reason']}")
            return
        plan = result["parse_plan"]
        print(f"pages={plan['page_count']} mineru_pages={len(plan['mineru_pages'])} visual_fallback={len(plan['visual_fallback_pages'])}")
        if result.get("extraction"):
            summary = result["extraction"]["summary"]
            print(f"fields={summary['fields']} matched={summary['matched']} llm_calls={summary['llm_calls']} model={summary['llm_model']}")
    else:
        if args.command == "extract":
            result = extract_report(args.pdf, args.output, settings, use_llm=not args.no_llm)
            summary = result["summary"]
            print(f"fields={summary['fields']} matched={summary['matched']} chunks={summary['chunks']} llm_calls={summary['llm_calls']} model={summary['llm_model']}")
        elif args.command == "review":
            build_review_page(args.run_dir, args.output)
            print(f"review_page={args.output}")
        else:
            result = build_evaluation_pack(args.run_dir, args.output, sample_size=args.sample_size)
            print(f"evaluation_table={result['table']}")
            print(f"metrics_summary={result['summary']}")


if __name__ == "__main__":
    main()
