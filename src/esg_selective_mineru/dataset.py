from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

import fitz

from .chunks import build_pymupdf_chunks
from .config import Settings
from .io_utils import write_json
from .page_scan import scan_pdf
from .parse_plan import build_parse_plan
from .report_filter import assess_report_suitability


SAFE_NAME_RE = re.compile(r"[\\/:*?\"<>|\s]+")
NUMBER_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?")


@dataclass
class PdfProfile:
    report_id: str
    source_file: str
    normalized_file: str
    sha256: str
    file_size: int
    page_count: int
    text_pages: int
    scanned_or_low_text_pages: int
    table_candidate_pages: int
    should_skip: bool
    skip_reason_code: str
    skip_reason: str


def safe_filename(value: str, *, max_length: int = 120) -> str:
    value = SAFE_NAME_RE.sub("_", value.strip())
    value = value.strip("._")
    return (value or "report")[:max_length]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _table_candidate_from_text(text: str) -> Dict[str, Any]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    table_like_lines = []
    for line in lines:
        numbers = NUMBER_RE.findall(line)
        if len(numbers) >= 2 or ("\t" in line and numbers):
            table_like_lines.append(line[:300])
    return {
        "line_count": len(lines),
        "table_like_line_count": len(table_like_lines),
        "sample_lines": table_like_lines[:12],
    }


def extract_page_texts(pdf_path: Path, output_path: Path) -> List[Dict[str, Any]]:
    doc = fitz.open(pdf_path)
    rows: List[Dict[str, Any]] = []
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            for page_index, page in enumerate(doc, start=1):
                text = page.get_text("text") or ""
                row = {"page": page_index, "text": text}
                rows.append(row)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return rows
    finally:
        doc.close()


def detect_table_candidates(page_texts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for page in page_texts:
        profile = _table_candidate_from_text(str(page.get("text") or ""))
        if profile["table_like_line_count"] > 0:
            candidates.append({"page": page.get("page"), **profile})
    return candidates


def write_manifest_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def preprocess_pdf(
    pdf_path: Path,
    output_root: Path,
    settings: Settings,
    *,
    report_id: str | None = None,
    normalized_pdf_dir: Path | None = None,
) -> PdfProfile:
    sha256 = file_sha256(pdf_path)
    report_id = report_id or safe_filename(pdf_path.stem)
    normalized_pdf_dir = normalized_pdf_dir or output_root / "pdf"
    normalized_pdf_dir.mkdir(parents=True, exist_ok=True)
    normalized_file = normalized_pdf_dir / f"{safe_filename(report_id)}_{sha256[:12]}.pdf"
    if not normalized_file.exists():
        normalized_file.write_bytes(pdf_path.read_bytes())

    report_dir = output_root / "processed" / safe_filename(report_id)
    report_dir.mkdir(parents=True, exist_ok=True)
    page_texts = extract_page_texts(normalized_file, report_dir / "page_texts.jsonl")
    suitability = assess_report_suitability(normalized_file)
    page_scans = scan_pdf(normalized_file)
    parse_plan = build_parse_plan(
        page_scans,
        mineru_score_threshold=settings.selective_mineru_score_threshold,
        max_mineru_pages=settings.selective_mineru_max_pages,
    )
    table_candidates = detect_table_candidates(page_texts)
    chunks = build_pymupdf_chunks(normalized_file)

    write_json(report_dir / "profile.json", {
        "report_id": report_id,
        "source_file": str(pdf_path),
        "normalized_file": str(normalized_file),
        "sha256": sha256,
        "suitability": suitability,
    })
    write_json(report_dir / "page_scan.json", page_scans)
    write_json(report_dir / "parse_plan.json", parse_plan)
    write_json(report_dir / "table_candidates.json", table_candidates)
    write_json(report_dir / "pymupdf_chunks.json", chunks)

    profile = PdfProfile(
        report_id=report_id,
        source_file=str(pdf_path),
        normalized_file=str(normalized_file),
        sha256=sha256,
        file_size=normalized_file.stat().st_size,
        page_count=len(page_texts),
        text_pages=sum(1 for page in page_texts if str(page.get("text") or "").strip()),
        scanned_or_low_text_pages=sum(1 for row in page_scans if row.get("scan_quality") == "scanned_or_low_text"),
        table_candidate_pages=len(table_candidates),
        should_skip=bool(suitability.get("should_skip")),
        skip_reason_code=str(suitability.get("reason_code") or ""),
        skip_reason=str(suitability.get("reason") or ""),
    )
    write_json(report_dir / "preprocess_summary.json", asdict(profile))
    return profile
