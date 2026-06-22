from __future__ import annotations

from typing import Any, Dict, List


def build_parse_plan(
    page_scans: List[Dict[str, Any]],
    *,
    mineru_score_threshold: int,
    max_mineru_pages: int,
    llm_selected_pages: List[int] | None = None,
    llm_review_low_threshold: int | None = None,
    llm_review_high_threshold: int | None = None,
    llm_review: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    high_threshold = llm_review_high_threshold or mineru_score_threshold
    llm_pages = set(llm_selected_pages or [])
    ranked = sorted(page_scans, key=lambda row: (row["mineru_score"], row["number_count"]), reverse=True)
    selected_pages = set()
    decision_sources: Dict[int, str] = {}
    for row in ranked:
        score = int(row.get("mineru_score") or 0)
        page_number = row["page_number"]
        if score >= high_threshold:
            selected_pages.add(page_number)
            decision_sources[page_number] = "rule_high_score"
        elif page_number in llm_pages:
            selected_pages.add(page_number)
            decision_sources[page_number] = "llm_gray_zone"
        if len(selected_pages) >= max_mineru_pages:
            break

    pages = []
    visual_fallback = []
    for row in page_scans:
        page_number = row["page_number"]
        if page_number in selected_pages:
            strategy = "mineru_required"
        else:
            strategy = "pymupdf_only"
        if row.get("scan_quality") == "scanned_or_low_text" and page_number not in selected_pages:
            visual_fallback.append(page_number)
        score = int(row.get("mineru_score") or 0)
        if page_number in decision_sources:
            decision_source = decision_sources[page_number]
        elif llm_review_low_threshold is not None and score < llm_review_low_threshold:
            decision_source = "rule_low_score"
        elif llm_review_low_threshold is not None and score < high_threshold:
            decision_source = "llm_gray_zone_rejected"
        else:
            decision_source = "rule_below_threshold"
        pages.append({**row, "parse_strategy": strategy, "mineru_decision_source": decision_source})

    return {
        "page_count": len(page_scans),
        "mineru_pages": sorted(selected_pages),
        "visual_fallback_pages": visual_fallback,
        "llm_review": llm_review or {"enabled": False},
        "pages": pages,
    }
