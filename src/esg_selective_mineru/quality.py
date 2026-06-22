from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, Field, validator


YEAR_RE = re.compile(r"20[0-3][0-9]")
NUMBER_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?")

UNIT_ALIASES = {
    "吨": "吨",
    "t": "吨",
    "ton": "吨",
    "tons": "吨",
    "万吨": "万吨",
    "tco2e": "tCO2e",
    "吨co2e": "tCO2e",
    "吨二氧化碳当量": "tCO2e",
    "万吨co2e": "万吨CO2e",
    "万吨二氧化碳当量": "万吨CO2e",
    "千瓦时": "kWh",
    "kwh": "kWh",
    "兆瓦时": "MWh",
    "mwh": "MWh",
    "万元": "万元",
    "亿元": "亿元",
    "%": "%",
    "％": "%",
    "人": "人",
    "小时": "小时",
}


class ExtractionResult(BaseModel):
    field_key: str = ""
    name_cn: str = ""
    category: str = ""
    indicator_type: str = ""
    matched: bool = False
    value: str = ""
    unit: str = ""
    year: str = ""
    summary: str = ""
    evidence: str = ""
    source_chunk_id: str = ""
    source_page: str | int = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""

    @validator("field_key", "name_cn", "category", "indicator_type", "value", "unit", "year", "summary", "evidence", "source_chunk_id", "reason", pre=True)
    def stringify(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @validator("confidence", pre=True)
    def normalize_confidence(cls, value: Any) -> float:
        try:
            numeric = float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
        if numeric > 1:
            numeric = numeric / 100
        return max(0.0, min(1.0, numeric))


def normalize_unit(unit: Any) -> tuple[str, str]:
    raw = str(unit or "").strip()
    if not raw:
        return "", "missing_unit"
    key = raw.lower().replace(" ", "")
    normalized = UNIT_ALIASES.get(key)
    if normalized:
        return normalized, ""
    return raw, "unknown_unit"


def normalize_value(value: Any) -> str:
    text = str(value or "").strip()
    match = NUMBER_RE.search(text.replace(",", ""))
    return match.group(0) if match else ""


def evidence_score(row: Dict[str, Any], *, target_year: str = "") -> int:
    evidence = str(row.get("evidence") or "")
    if not evidence.strip():
        return 0
    score = 20
    if row.get("name_cn") and str(row["name_cn"])[:4] in evidence:
        score += 20
    normalized_value = normalize_value(row.get("value"))
    if normalized_value and normalized_value in evidence.replace(",", ""):
        score += 25
    unit = str(row.get("unit") or "")
    if unit and unit in evidence:
        score += 15
    year = str(row.get("year") or "")
    if target_year and target_year in evidence:
        score += 10
    elif year and year in evidence:
        score += 5
    if row.get("source_page"):
        score += 10
    return min(score, 100)


def validate_year(year: Any, *, target_year: str, matched: bool) -> tuple[str, str]:
    text = str(year or "").strip()
    if not matched:
        return text, ""
    if not text:
        return text, "missing_year"
    years = YEAR_RE.findall(text)
    if target_year and target_year not in years:
        return text, f"year_mismatch:{target_year}"
    return target_year if target_year else text, ""


def validate_and_score_result(row: Dict[str, Any], *, target_year: str = "2024") -> Dict[str, Any]:
    warnings: List[str] = []
    try:
        model = ExtractionResult(**row)
        clean = model.dict()
    except Exception as exc:
        clean = ExtractionResult().dict()
        clean.update({key: "" if value is None else value for key, value in row.items()})
        warnings.append(f"schema_error:{exc}")

    normalized_unit, unit_warning = normalize_unit(clean.get("unit"))
    normalized_value = normalize_value(clean.get("value"))
    if unit_warning and clean.get("matched") and str(clean.get("indicator_type")).lower() in {"quantitative", "定量"}:
        warnings.append(unit_warning)

    checked_year, year_warning = validate_year(clean.get("year"), target_year=target_year, matched=bool(clean.get("matched")))
    clean["year"] = checked_year
    if year_warning:
        warnings.append(year_warning)

    score = evidence_score(clean, target_year=target_year)
    if clean.get("matched") and score < 50:
        warnings.append("weak_evidence")

    return {
        **clean,
        "target_year": target_year,
        "normalized_value": normalized_value,
        "normalized_unit": normalized_unit,
        "unit_warning": unit_warning,
        "year_warning": year_warning,
        "evidence_score": score,
        "quality_warnings": warnings,
    }


def enrich_results(rows: List[Dict[str, Any]], *, pdf_path: str | Path = "", target_year: str = "2024", expected_year: str = "") -> List[Dict[str, Any]]:
    # expected_year is kept for backward compatibility; target_year is the active policy.
    active_year = target_year or expected_year or "2024"
    return [validate_and_score_result(row, target_year=active_year) for row in rows]


def quality_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(rows)
    review_counts: Dict[str, int] = {}
    target_year = ""
    for row in rows:
        review = row.get("review") or {}
        status = str(review.get("status") or "pending")
        review_counts[status] = review_counts.get(status, 0) + 1
        target_year = target_year or str(row.get("target_year") or "")
    return {
        "target_year": target_year,
        "fields": total,
        "matched": sum(1 for row in rows if row.get("matched")),
        "pending_review": review_counts.get("pending", 0) + review_counts.get("edited", 0),
        "review_status_counts": review_counts,
        "low_confidence": sum(1 for row in rows if float(row.get("confidence") or 0) < 0.7),
        "missing_evidence": sum(1 for row in rows if not str(row.get("evidence") or "").strip()),
        "weak_evidence": sum(1 for row in rows if int(row.get("evidence_score") or 0) < 50),
        "year_warnings": sum(1 for row in rows if row.get("year_warning")),
        "unit_warnings": sum(1 for row in rows if row.get("unit_warning") and row.get("unit_warning") != "missing_unit"),
        "schema_warnings": sum(1 for row in rows if any(str(item).startswith("schema_error") for item in row.get("quality_warnings") or [])),
        "average_evidence_score": round(sum(int(row.get("evidence_score") or 0) for row in rows) / total, 2) if total else 0,
    }
