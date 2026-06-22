from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List

import fitz

ESG_TERMS = (
    "ESG", "环境", "社会", "治理", "可持续", "碳", "温室气体", "能耗", "用水", "废弃物",
    "员工", "供应商", "安全", "反腐", "董事会", "绩效", "指标", "数据表"
)
TABLE_TERMS = ("关键绩效", "绩效表", "指标表", "ESG数据", "环境绩效", "社会绩效", "治理绩效", "单位", "2024")
INDEX_TERMS = ("目录", "索引", "指标索引", "GRI", "披露索引")
NUMBER_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?")
YEAR_RE = re.compile(r"20[0-3][0-9]")


@dataclass
class PageScan:
    page_number: int
    text_length: int
    number_count: int
    year_hits: List[str]
    esg_hits: List[str]
    table_hits: List[str]
    index_hits: List[str]
    table_like_lines: int
    scan_quality: str
    mineru_score: int
    reasons: List[str]


def _table_like_lines(text: str) -> int:
    count = 0
    for line in text.splitlines():
        numbers = NUMBER_RE.findall(line)
        if len(numbers) >= 2 or ("\t" in line and numbers):
            count += 1
    return count


def score_page(page_number: int, text: str) -> PageScan:
    normalized = text.replace(" ", "")
    esg_hits = [term for term in ESG_TERMS if term in normalized]
    table_hits = [term for term in TABLE_TERMS if term in normalized]
    index_hits = [term for term in INDEX_TERMS if term in normalized]
    years = sorted(set(YEAR_RE.findall(text)))
    number_count = len(NUMBER_RE.findall(text))
    table_lines = _table_like_lines(text)
    score = 0
    reasons: List[str] = []

    if len(text.strip()) < 80:
        score += 30
        reasons.append("low_text_layer")
    if table_hits:
        score += min(len(table_hits), 6) * 8
        reasons.append("table_terms")
    if len(esg_hits) >= 3:
        score += min(len(esg_hits), 8) * 3
        reasons.append("esg_terms")
    if number_count >= 20:
        score += min(number_count // 10, 8) * 3
        reasons.append("number_dense")
    if table_lines >= 3:
        score += min(table_lines, 10) * 4
        reasons.append("table_like_lines")
    if years:
        score += min(len(years), 3) * 3
        reasons.append("year_hits")
    if index_hits and number_count < 20:
        score -= 15
        reasons.append("index_penalty")

    quality = "scanned_or_low_text" if len(text.strip()) < 80 else "text_layer_ok"
    return PageScan(
        page_number=page_number,
        text_length=len(text),
        number_count=number_count,
        year_hits=years,
        esg_hits=esg_hits,
        table_hits=table_hits,
        index_hits=index_hits,
        table_like_lines=table_lines,
        scan_quality=quality,
        mineru_score=max(score, 0),
        reasons=reasons,
    )


def scan_pdf(pdf_path: Path) -> List[Dict[str, Any]]:
    doc = fitz.open(pdf_path)
    try:
        scans = []
        for index, page in enumerate(doc, start=1):
            scans.append(asdict(score_page(index, page.get_text("text") or "")))
        return scans
    finally:
        doc.close()
