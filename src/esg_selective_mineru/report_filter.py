from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

import fitz


ESG_TITLE_TERMS = (
    "ESG",
    "环境、社会",
    "环境社会",
    "环境、社会及治理",
    "环境、社会和公司治理",
    "环境、社会与公司治理",
    "环境、社会及公司治理",
    "可持续发展",
)
LEGACY_SOCIAL_RESPONSIBILITY_TERMS = ("社会责任报告", "企业社会责任报告")
SUPPORTING_DOC_TERMS = ("鉴证声明", "鉴证报告", "审验报告", "独立鉴证", "报告摘要", "摘要")


def _read_first_pages(pdf_path: Path, *, pages: int = 2, max_chars: int = 3000) -> str:
    doc = fitz.open(pdf_path)
    try:
        parts = []
        for index in range(min(pages, len(doc))):
            parts.append(doc[index].get_text("text") or "")
        return "\n".join(parts)[:max_chars]
    finally:
        doc.close()


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def assess_report_suitability(pdf_path: Path) -> Dict[str, Any]:
    filename = pdf_path.name
    try:
        first_text = _read_first_pages(pdf_path)
    except Exception as exc:
        return {
            "should_skip": True,
            "reason_code": "unreadable_pdf",
            "reason": f"PDF 无法打开或解析：{exc}",
            "filename": filename,
        }

    title_window = _compact(filename + "\n" + first_text[:1000])
    has_esg_title_signal = any(term in title_window for term in ESG_TITLE_TERMS)
    has_legacy_social_title = any(term in title_window for term in LEGACY_SOCIAL_RESPONSIBILITY_TERMS)
    support_terms = [term for term in SUPPORTING_DOC_TERMS if term in title_window]

    if support_terms and not has_esg_title_signal:
        return {
            "should_skip": True,
            "reason_code": "supporting_or_summary_document",
            "reason": "文档疑似为鉴证声明、补充说明或摘要文件，不是完整 ESG 报告，已跳过 60 字段抽取流程。",
            "filename": filename,
            "matched_terms": support_terms,
        }

    if has_legacy_social_title and not has_esg_title_signal:
        return {
            "should_skip": True,
            "reason_code": "legacy_social_responsibility_report",
            "reason": "文档标题为传统社会责任报告，且缺少 ESG 或“环境、社会与治理”标题信号，不满足 60 字段 ESG 抽取流程要求，已跳过。",
            "filename": filename,
            "matched_terms": [term for term in LEGACY_SOCIAL_RESPONSIBILITY_TERMS if term in title_window],
        }

    return {
        "should_skip": False,
        "reason_code": "",
        "reason": "",
        "filename": filename,
        "matched_terms": [term for term in ESG_TITLE_TERMS if term in title_window],
    }
