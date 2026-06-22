from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Any, Dict

from .config import Settings
from .extractor import extract_report
from .io_utils import write_json
from .mineru_page_judge import review_mineru_pages_with_llm
from .mineru_runner import run_mineru
from .page_scan import scan_pdf
from .parse_plan import build_parse_plan
from .report_filter import assess_report_suitability


class PipelineTimer:
    def __init__(self) -> None:
        self.started_at = perf_counter()
        self.stages: Dict[str, float] = {}

    @contextmanager
    def stage(self, name: str):
        start = perf_counter()
        try:
            yield
        finally:
            self.stages[name] = round(self.stages.get(name, 0.0) + perf_counter() - start, 3)

    def summary(self) -> Dict[str, Any]:
        return {
            "total_seconds": round(perf_counter() - self.started_at, 3),
            "stages": dict(self.stages),
        }


def scan_only(pdf_path: Path, output_dir: Path, settings: Settings) -> Dict[str, Any]:
    timer = PipelineTimer()
    suitability = assess_report_suitability(pdf_path)
    if suitability.get("should_skip"):
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = {"skipped": True, **suitability, "timing": timer.summary()}
        write_json(output_dir / "skip_report.json", summary)
        write_json(output_dir / "run_summary.json", summary)
        return {
            "skipped": True,
            "skip_report": summary,
            "page_scan": [],
            "parse_plan": {"page_count": 0, "mineru_pages": [], "visual_fallback_pages": [], "pages": []},
            "timing": timer.summary(),
        }
    with timer.stage("scan_pdf"):
        scans = scan_pdf(pdf_path)
    llm_review: Dict[str, Any] = {"enabled": settings.mineru_llm_review_enabled}
    if settings.mineru_llm_review_enabled:
        gray_pages = [
            row for row in scans
            if settings.mineru_llm_review_low_threshold <= int(row.get("mineru_score") or 0) < settings.mineru_llm_review_high_threshold
        ]
        gray_pages = sorted(gray_pages, key=lambda row: (row["mineru_score"], row["number_count"]), reverse=True)[:settings.mineru_llm_review_max_pages]
        with timer.stage("llm_review_mineru_pages"):
            llm_review = review_mineru_pages_with_llm(gray_pages, settings)
    llm_review_succeeded = bool(
        settings.mineru_llm_review_enabled
        and llm_review.get("attempted")
        and not llm_review.get("error")
    )
    with timer.stage("build_parse_plan"):
        plan = build_parse_plan(
            scans,
            mineru_score_threshold=settings.selective_mineru_score_threshold,
            max_mineru_pages=settings.selective_mineru_max_pages,
            llm_selected_pages=llm_review.get("selected_pages", []) if llm_review_succeeded else [],
            llm_review_low_threshold=settings.mineru_llm_review_low_threshold if llm_review_succeeded else None,
            llm_review_high_threshold=settings.mineru_llm_review_high_threshold if llm_review_succeeded else None,
            llm_review=llm_review,
        )
    with timer.stage("write_scan_artifacts"):
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "page_scan.json", scans)
        write_json(output_dir / "parse_plan.json", plan)
        write_json(output_dir / "visual_fallback_queue.json", plan["visual_fallback_pages"])
    return {"page_scan": scans, "parse_plan": plan, "timing": timer.summary()}


def run_pipeline(pdf_path: Path, output_dir: Path, settings: Settings, *, extract: bool = False, use_llm: bool = True) -> Dict[str, Any]:
    timer = PipelineTimer()
    with timer.stage("scan"):
        result = scan_only(pdf_path, output_dir, settings)
    if result.get("skipped"):
        return {**result, "mineru": {"attempted": False, "status": "skipped"}, "extraction": None, "summary": result["skip_report"], "timing": result["timing"]}
    plan = result["parse_plan"]

    mineru_result = {"attempted": False, "status": "skipped"}
    with timer.stage("mineru"):
        if settings.mineru_auto_run_enabled and plan["mineru_pages"]:
            mineru_result = run_mineru(
                pdf_path,
                settings.mineru_output_root,
                settings.mineru_command,
                settings.mineru_timeout_seconds,
            )
    with timer.stage("write_mineru_artifacts"):
        write_json(output_dir / "mineru_jobs.json", {"mineru_pages": plan["mineru_pages"], "mineru_result": mineru_result})

    summary = {
        "pdf": str(pdf_path),
        "output_dir": str(output_dir),
        "mineru": mineru_result,
        "parse_plan": {
            "page_count": plan["page_count"],
            "mineru_pages": len(plan["mineru_pages"]),
            "visual_fallback_pages": len(plan["visual_fallback_pages"]),
        },
    }

    extraction = None
    if extract:
        with timer.stage("extract"):
            extraction = extract_report(pdf_path, output_dir, settings, use_llm=use_llm)
        summary["extraction"] = extraction["summary"]

    summary["timing"] = timer.summary()
    summary["timing"]["details"] = {"scan": result.get("timing", {})}
    write_json(output_dir / "run_summary.json", summary)
    return {**result, "mineru": mineru_result, "extraction": extraction, "summary": summary, "timing": summary["timing"]}
