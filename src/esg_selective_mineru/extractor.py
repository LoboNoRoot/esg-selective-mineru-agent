from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .chunks import build_rag_chunks
from .config import Settings
from .io_utils import write_json
from .llm_client import LLMClient
from .quality import enrich_results
from .retriever import SimpleRetriever
from .schema_loader import load_a_share_schema, schema_summary


def _batches(items: List[Dict[str, Any]], size: int) -> Iterable[List[Dict[str, Any]]]:
    size = max(1, size)
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _empty_result(field: Dict[str, Any], reason: str) -> Dict[str, Any]:
    return {
        "field_key": field.get("field_key"),
        "name_cn": field.get("name_cn"),
        "category": field.get("category"),
        "indicator_type": field.get("indicator_type"),
        "matched": False,
        "value": "",
        "unit": "",
        "year": "",
        "summary": "",
        "evidence": "",
        "source_chunk_id": "",
        "source_page": "",
        "confidence": 0.0,
        "reason": reason,
    }


def _normalize_result(raw: Dict[str, Any], field: Dict[str, Any]) -> Dict[str, Any]:
    result = _empty_result(field, "")
    result.update({key: raw.get(key, result.get(key, "")) for key in result.keys() if key in raw})
    result["field_key"] = field.get("field_key")
    result["name_cn"] = field.get("name_cn")
    result["category"] = field.get("category")
    result["indicator_type"] = field.get("indicator_type")
    result["matched"] = bool(raw.get("matched", False))
    try:
        result["confidence"] = float(raw.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        result["confidence"] = 0.0
    return result


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "field_key", "name_cn", "category", "indicator_type", "matched", "value", "unit", "year",
        "summary", "evidence", "source_chunk_id", "source_page", "confidence", "reason",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def extract_report(pdf_path: Path, output_dir: Path, settings: Settings, *, use_llm: bool = True) -> Dict[str, Any]:
    fields = load_a_share_schema(settings.original_esg_project_root)
    mineru_root = settings.mineru_output_root if settings.mineru_output_root.exists() else None
    chunks = build_rag_chunks(pdf_path, mineru_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "rag_chunks.json", chunks)

    retriever = SimpleRetriever(chunks)
    contexts: Dict[str, List[Dict[str, Any]]] = {}
    for field in fields:
        contexts[field["field_key"]] = retriever.search_field(field, top_k=settings.rag_top_k)
    write_json(output_dir / "field_contexts.json", contexts)

    results: List[Dict[str, Any]] = []
    llm_calls = 0
    llm_errors: List[str] = []
    llm_allowed = use_llm and settings.llm_extraction_enabled
    client = None
    if llm_allowed:
        try:
            client = LLMClient(settings)
        except Exception as exc:
            llm_allowed = False
            llm_errors.append(str(exc))

    if not llm_allowed or client is None:
        results = [_empty_result(field, "llm_disabled_or_not_configured") for field in fields]
    else:
        for batch in _batches(fields, settings.llm_field_batch_size):
            if llm_calls >= settings.llm_max_calls_per_report:
                results.extend(_empty_result(field, "llm_call_budget_exhausted") for field in batch)
                continue
            try:
                raw_results = client.extract_fields(batch, contexts)
                by_key = {item.get("field_key"): item for item in raw_results if isinstance(item, dict)}
                for field in batch:
                    results.append(_normalize_result(by_key.get(field["field_key"], {}), field))
            except Exception as exc:
                llm_errors.append(str(exc))
                results.extend(_empty_result(field, f"llm_error:{exc}") for field in batch)
            llm_calls += 1

    results = enrich_results(results, pdf_path=pdf_path, target_year=settings.target_report_year)
    summary = {
        "pdf": str(pdf_path),
        "target_year": settings.target_report_year,
        "schema": schema_summary(fields),
        "chunks": len(chunks),
        "fields": len(fields),
        "matched": sum(1 for row in results if row.get("matched")),
        "weak_evidence": sum(1 for row in results if int(row.get("evidence_score") or 0) < 50),
        "quality_warnings": sum(len(row.get("quality_warnings") or []) for row in results),
        "llm_enabled": llm_allowed,
        "llm_model": settings.text_model,
        "llm_calls": llm_calls,
        "llm_errors": llm_errors[:5],
    }
    write_json(output_dir / "extraction_results.json", results)
    write_json(output_dir / "extraction_summary.json", summary)
    write_csv(output_dir / "extraction_results.csv", results)
    return {"summary": summary, "results": results, "contexts": contexts}
