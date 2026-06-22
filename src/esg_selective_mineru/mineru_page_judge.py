from __future__ import annotations

import json
from typing import Any, Dict, List

from openai import OpenAI

from .config import Settings


def review_mineru_pages_with_llm(page_scans: List[Dict[str, Any]], settings: Settings) -> Dict[str, Any]:
    if not page_scans:
        return {"enabled": True, "attempted": False, "selected_pages": [], "decisions": [], "error": ""}
    if not settings.dashscope_api_key:
        return {
            "enabled": True,
            "attempted": False,
            "selected_pages": [],
            "decisions": [],
            "error": "missing_dashscope_api_key",
        }

    client = OpenAI(api_key=settings.dashscope_api_key, base_url=settings.openai_base_url)
    prompt = _build_prompt(page_scans)
    try:
        completion = client.chat.completions.create(
            model=settings.schema_judge_model or settings.text_model,
            messages=[
                {
                    "role": "system",
                    "content": "你是 ESG 报告解析路由器，只判断页面是否值得调用 MinerU 深度解析。请严格输出 JSON。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = completion.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception as exc:
        return {
            "enabled": True,
            "attempted": True,
            "selected_pages": [],
            "decisions": [],
            "error": str(exc),
        }

    decisions = data.get("decisions", [])
    if not isinstance(decisions, list):
        decisions = []
    selected_pages = []
    normalized = []
    candidate_pages = {int(row["page_number"]) for row in page_scans}
    for item in decisions:
        if not isinstance(item, dict):
            continue
        try:
            page_number = int(item.get("page_number"))
        except (TypeError, ValueError):
            continue
        if page_number not in candidate_pages:
            continue
        needs_mineru = bool(item.get("needs_mineru"))
        if needs_mineru:
            selected_pages.append(page_number)
        normalized.append({
            "page_number": page_number,
            "needs_mineru": needs_mineru,
            "reason": str(item.get("reason") or "")[:300],
        })
    return {
        "enabled": True,
        "attempted": True,
        "model": settings.schema_judge_model or settings.text_model,
        "selected_pages": sorted(set(selected_pages)),
        "decisions": normalized,
        "error": "",
    }


def _build_prompt(page_scans: List[Dict[str, Any]]) -> str:
    compact_pages = []
    for row in page_scans:
        compact_pages.append({
            "page_number": row.get("page_number"),
            "text_length": row.get("text_length"),
            "number_count": row.get("number_count"),
            "year_hits": row.get("year_hits", []),
            "esg_hits": row.get("esg_hits", []),
            "table_hits": row.get("table_hits", []),
            "index_hits": row.get("index_hits", []),
            "table_like_lines": row.get("table_like_lines"),
            "scan_quality": row.get("scan_quality"),
            "mineru_score": row.get("mineru_score"),
            "reasons": row.get("reasons", []),
        })
    return (
        "请判断这些 ESG 报告页面是否值得调用 MinerU 深度解析。\n"
        "应选择的页面通常包含：ESG 数据表、关键绩效表、指标表、环境/员工/治理量化数据、"
        "图文混排导致 PyMuPDF 可能漏读的关键信息、扫描或低文本层页面。\n"
        "不应选择的页面通常是：封面、目录、章节标题页、致辞、纯宣传案例、附录问卷、低价值索引页。\n"
        "请只输出 JSON，格式为：\n"
        "{\"decisions\":[{\"page_number\":1,\"needs_mineru\":true,\"reason\":\"...\"}]}\n\n"
        f"页面特征：\n{json.dumps(compact_pages, ensure_ascii=False)}"
    )
