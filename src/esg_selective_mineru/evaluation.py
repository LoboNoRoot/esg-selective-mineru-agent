from __future__ import annotations

import csv
import html
import json
import re
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List

from .io_utils import read_json, write_json


ANNOTATION_COLUMNS = [
    "field_hit_correct",
    "value_correct",
    "evidence_usable",
    "annotator_note",
]

RETRIEVAL_ANNOTATION_COLUMNS = [
    "best_mode",
    "simple_score",
    "local_hybrid_score",
    "embedding_hybrid_score",
    "retrieval_note",
]


def _clean_space(text: Any) -> str:
    text = "" if text is None else str(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _window(text: str, center: int, *, width: int = 360) -> str:
    if len(text) <= width:
        return text
    half = width // 2
    start = max(0, center - half)
    end = min(len(text), start + width)
    start = max(0, end - width)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


def _field_keywords(result: Dict[str, Any]) -> List[str]:
    words: List[str] = []
    for key in ["name_cn", "field_key", "pred_value", "value", "unit", "year"]:
        value = result.get(key)
        if value is not None and str(value).strip():
            words.append(str(value).strip())
    split_words: List[str] = []
    for word in words:
        split_words.extend(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_.%-]{2,}", word))
    return sorted(set(words + split_words), key=len, reverse=True)


def _short_source_text(
    result: Dict[str, Any],
    contexts: List[Dict[str, Any]],
    *,
    chunks_by_id: Dict[str, Dict[str, Any]] | None = None,
    width: int = 360,
) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    source_chunk_id = str(result.get("source_chunk_id") or "")
    if chunks_by_id and source_chunk_id and source_chunk_id in chunks_by_id:
        candidates.append(chunks_by_id[source_chunk_id])
    candidates.extend(context for context in contexts[:3] if context.get("chunk_id") != source_chunk_id)
    if not candidates:
        evidence = _clean_space(result.get("evidence", ""))
        return {"text": _window(evidence, 0, width=width), "page": result.get("source_page", ""), "chunk_id": result.get("source_chunk_id", "")}

    keywords = _field_keywords(result)
    for keyword in keywords:
        if not keyword or keyword == "-":
            continue
        for context in candidates:
            text = _clean_space(context.get("text", ""))
            index = text.find(keyword)
            if index >= 0:
                return {
                    "text": _window(text, index, width=width),
                    "page": context.get("page", ""),
                    "chunk_id": context.get("chunk_id", ""),
                }

    first = candidates[0]
    text = _clean_space(first.get("text", ""))
    return {
        "text": _window(text, 0, width=width),
        "page": first.get("page", ""),
        "chunk_id": first.get("chunk_id", ""),
    }


def _read_optional_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return read_json(path)


def _report_id(run_dir: Path, summary: Dict[str, Any]) -> str:
    pdf = str(summary.get("pdf") or "")
    if pdf:
        return Path(pdf).stem[:80]
    name = run_dir.name
    return name.removesuffix("_full_run").removesuffix("_run")


def _file_time_span_seconds(run_dir: Path) -> float:
    files = [path for path in run_dir.iterdir() if path.is_file()]
    if not files:
        return 0.0
    times = [path.stat().st_mtime for path in files]
    return round(max(times) - min(times), 3)


def _mineru_ratio(run_dir: Path) -> Dict[str, Any]:
    plan = _read_optional_json(run_dir / "parse_plan.json", {})
    page_count = int(plan.get("page_count") or 0)
    mineru_pages = plan.get("mineru_pages") or []
    ratio = round(len(mineru_pages) / page_count, 4) if page_count else 0.0
    return {
        "page_count": page_count,
        "mineru_page_count": len(mineru_pages),
        "mineru_page_ratio": ratio,
    }


def _write_csv(path: Path, rows: List[Dict[str, Any]], columns: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _top_context(contexts: Dict[str, List[Dict[str, Any]]], field_key: str) -> Dict[str, Any]:
    items = contexts.get(field_key) or []
    return items[0] if items else {}


def _context_short(item: Dict[str, Any], *, width: int = 260) -> str:
    return _window(_clean_space(item.get("text", "")), 0, width=width)


def _load_retrieval_annotations(path: Path) -> Dict[tuple[str, str], Dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    return {
        (row.get("report_id", ""), row.get("field_key", "")): row
        for row in rows
    }


def build_retrieval_evaluation_pack(
    simple_dirs: List[Path],
    local_hybrid_dirs: List[Path],
    embedding_hybrid_dirs: List[Path],
    output_dir: Path,
) -> Dict[str, str]:
    if not (len(simple_dirs) == len(local_hybrid_dirs) == len(embedding_hybrid_dirs)):
        raise ValueError("simple/local/embedding 目录数量必须一致，并按同一报告顺序传入。")

    output_dir.mkdir(parents=True, exist_ok=True)
    table_path = output_dir / "retrieval_manual_comparison.csv"
    existing = _load_retrieval_annotations(table_path)
    rows: List[Dict[str, Any]] = []
    report_rows: List[Dict[str, Any]] = []

    for simple_dir, local_dir, embedding_dir in zip(simple_dirs, local_hybrid_dirs, embedding_hybrid_dirs):
        simple_summary = _read_optional_json(simple_dir / "extraction_summary.json", {})
        local_summary = _read_optional_json(local_dir / "extraction_summary.json", {})
        embedding_summary = _read_optional_json(embedding_dir / "extraction_summary.json", {})
        simple_contexts = _read_optional_json(simple_dir / "field_contexts.json", {})
        local_contexts = _read_optional_json(local_dir / "field_contexts.json", {})
        embedding_contexts = _read_optional_json(embedding_dir / "field_contexts.json", {})
        report_id = _report_id(simple_dir, simple_summary)
        field_keys = sorted(set(simple_contexts) | set(local_contexts) | set(embedding_contexts))
        changed_top1 = 0
        changed_embedding_vs_local = 0
        vector_only = 0

        for field_key in field_keys:
            simple_top = _top_context(simple_contexts, field_key)
            local_top = _top_context(local_contexts, field_key)
            embedding_top = _top_context(embedding_contexts, field_key)
            simple_id = simple_top.get("chunk_id", "")
            local_id = local_top.get("chunk_id", "")
            embedding_id = embedding_top.get("chunk_id", "")
            if simple_id != embedding_id:
                changed_top1 += 1
            if local_id != embedding_id:
                changed_embedding_vs_local += 1
            if embedding_top.get("retrieval_source") == "vector":
                vector_only += 1

            row = {
                "report_id": report_id,
                "field_key": field_key,
                "simple_dir": str(simple_dir),
                "local_hybrid_dir": str(local_dir),
                "embedding_hybrid_dir": str(embedding_dir),
                "simple_top1_chunk": simple_id,
                "simple_top1_page": simple_top.get("page", ""),
                "simple_top1_score": simple_top.get("score", ""),
                "simple_top1_text": _context_short(simple_top),
                "local_top1_chunk": local_id,
                "local_top1_page": local_top.get("page", ""),
                "local_top1_score": local_top.get("score", ""),
                "local_vector_rank": local_top.get("vector_rank", ""),
                "local_top1_text": _context_short(local_top),
                "embedding_top1_chunk": embedding_id,
                "embedding_top1_page": embedding_top.get("page", ""),
                "embedding_top1_score": embedding_top.get("score", ""),
                "embedding_bm25_rank": embedding_top.get("bm25_rank", ""),
                "embedding_vector_rank": embedding_top.get("vector_rank", ""),
                "embedding_vector_score": embedding_top.get("vector_score", ""),
                "embedding_vector_backend": embedding_top.get("vector_backend", embedding_summary.get("retriever_vector_backend_actual", "")),
                "embedding_top1_text": _context_short(embedding_top),
                "simple_vs_embedding_changed": int(simple_id != embedding_id),
                "local_vs_embedding_changed": int(local_id != embedding_id),
                "embedding_actual_backend": embedding_summary.get("retriever_vector_backend_actual", ""),
            }
            row.update({column: "" for column in RETRIEVAL_ANNOTATION_COLUMNS})
            saved = existing.get((report_id, field_key), {})
            row.update({column: saved.get(column, row[column]) for column in RETRIEVAL_ANNOTATION_COLUMNS})
            rows.append(row)

        report_rows.append({
            "report_id": report_id,
            "fields": len(field_keys),
            "embedding_vs_simple_top1_changed": changed_top1,
            "embedding_vs_local_top1_changed": changed_embedding_vs_local,
            "embedding_vector_only_top1": vector_only,
            "simple_chunks": simple_summary.get("chunks", ""),
            "local_backend": local_summary.get("retriever_vector_backend_actual", local_summary.get("retriever_vector_backend", "")),
            "embedding_backend": embedding_summary.get("retriever_vector_backend_actual", ""),
            "embedding_model": embedding_summary.get("embedding_model", ""),
        })

    columns = [
        "report_id", "field_key",
        "simple_top1_chunk", "simple_top1_page", "simple_top1_score", "simple_top1_text",
        "local_top1_chunk", "local_top1_page", "local_top1_score", "local_vector_rank", "local_top1_text",
        "embedding_top1_chunk", "embedding_top1_page", "embedding_top1_score",
        "embedding_bm25_rank", "embedding_vector_rank", "embedding_vector_score",
        "embedding_vector_backend", "embedding_top1_text",
        "simple_vs_embedding_changed", "local_vs_embedding_changed", "embedding_actual_backend",
        *RETRIEVAL_ANNOTATION_COLUMNS,
        "simple_dir", "local_hybrid_dir", "embedding_hybrid_dir",
    ]
    _write_csv(table_path, rows, columns)
    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "reports": report_rows,
        "overall": {
            "reports": len(report_rows),
            "fields": len(rows),
            "embedding_vs_simple_top1_changed": sum(int(row["simple_vs_embedding_changed"]) for row in rows),
            "embedding_vs_local_top1_changed": sum(int(row["local_vs_embedding_changed"]) for row in rows),
            "annotation_guide": {
                "best_mode": "人工填写 simple/local/embedding/same。",
                "simple_score": "人工填写 -1/0/1，表示 simple 的 Top1 证据相对是否差/相当/好。",
                "local_hybrid_score": "人工填写 -1/0/1，表示 local hybrid 的 Top1 证据相对是否差/相当/好。",
                "embedding_hybrid_score": "人工填写 -1/0/1，表示 embedding hybrid 的 Top1 证据相对是否差/相当/好。",
                "retrieval_note": "记录判断原因，例如绩效表、目录页、治理制度页、员工发展页等。",
            },
        },
    }
    summary_path = output_dir / "retrieval_comparison_summary.json"
    write_json(summary_path, summary)
    return {"table": str(table_path), "summary": str(summary_path)}


def _truthy(value: Any) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "y", "对", "是", "正确", "可用"}:
        return True
    if text in {"0", "false", "no", "n", "错", "否", "错误", "不可用"}:
        return False
    return None


def _rate(rows: Iterable[Dict[str, Any]], column: str) -> float | None:
    values = [_truthy(row.get(column)) for row in rows]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return round(sum(1 for value in values if value) / len(values), 4)


def _load_existing_annotations(path: Path) -> Dict[tuple[str, str], Dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    return {
        (row.get("report_id", ""), row.get("field_key", "")): row
        for row in rows
    }


def build_evaluation_pack(run_dirs: List[Path], output_dir: Path, *, sample_size: int = 10) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    table_path = output_dir / "manual_evaluation_sample.csv"
    existing = _load_existing_annotations(table_path)
    rows: List[Dict[str, Any]] = []
    report_metrics: List[Dict[str, Any]] = []

    for run_dir in run_dirs:
        summary = _read_optional_json(run_dir / "extraction_summary.json", {})
        results = _read_optional_json(run_dir / "extraction_results.json", [])
        contexts = _read_optional_json(run_dir / "field_contexts.json", {})
        chunks = _read_optional_json(run_dir / "rag_chunks.json", [])
        chunks_by_id = {str(chunk.get("chunk_id")): chunk for chunk in chunks if chunk.get("chunk_id")}
        ratio = _mineru_ratio(run_dir)
        report_id = _report_id(run_dir, summary)
        processing_seconds = _file_time_span_seconds(run_dir)
        selected = sorted(
            results,
            key=lambda row: (not bool(row.get("matched")), str(row.get("field_key") or "")),
        )[:sample_size]
        report_rows: List[Dict[str, Any]] = []
        for result in selected:
            field_key = str(result.get("field_key") or "")
            context_items = contexts.get(field_key) or []
            top_context = context_items[0] if context_items else {}
            short_source = _short_source_text(result, context_items, chunks_by_id=chunks_by_id)
            row = {
                "report_id": report_id,
                "run_dir": str(run_dir),
                "field_key": field_key,
                "name_cn": result.get("name_cn", ""),
                "category": result.get("category", ""),
                "indicator_type": result.get("indicator_type", ""),
                "pred_matched": result.get("matched", ""),
                "pred_value": result.get("value", ""),
                "pred_unit": result.get("unit", ""),
                "pred_year": result.get("year", ""),
                "pred_evidence": result.get("evidence", ""),
                "pred_source_page": result.get("source_page", ""),
                "confidence": result.get("confidence", ""),
                "source_text_short": short_source.get("text", ""),
                "source_text_short_page": short_source.get("page", ""),
                "source_text_short_chunk_id": short_source.get("chunk_id", ""),
                "retrieved_context": top_context.get("text", ""),
                "processing_time_seconds": processing_seconds,
                **ratio,
            }
            row.update({column: "" for column in ANNOTATION_COLUMNS})
            row.update({
                column: existing.get((report_id, field_key), {}).get(column, row[column])
                for column in ANNOTATION_COLUMNS
            })
            rows.append(row)
            report_rows.append(row)

        report_metrics.append({
            "report_id": report_id,
            "sampled_fields": len(report_rows),
            "field_hit_rate": _rate(report_rows, "field_hit_correct"),
            "value_accuracy": _rate(report_rows, "value_correct"),
            "evidence_usable_rate": _rate(report_rows, "evidence_usable"),
            "processing_time_seconds": processing_seconds,
            **ratio,
        })

    columns = [
        "report_id", "run_dir", "field_key", "name_cn", "category", "indicator_type",
        "pred_matched", "pred_value", "pred_unit", "pred_year", "pred_evidence",
        "pred_source_page", "confidence", "source_text_short", "source_text_short_page",
        "source_text_short_chunk_id", "retrieved_context", *ANNOTATION_COLUMNS,
        "processing_time_seconds", "page_count", "mineru_page_count", "mineru_page_ratio",
    ]
    _write_csv(table_path, rows, columns)

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "reports": report_metrics,
        "overall": {
            "sampled_fields": len(rows),
            "field_hit_rate": _rate(rows, "field_hit_correct"),
            "value_accuracy": _rate(rows, "value_correct"),
            "evidence_usable_rate": _rate(rows, "evidence_usable"),
            "average_processing_time_seconds": round(mean([item["processing_time_seconds"] for item in report_metrics]), 3) if report_metrics else 0,
            "average_mineru_page_ratio": round(mean([item["mineru_page_ratio"] for item in report_metrics]), 4) if report_metrics else 0,
        },
        "annotation_guide": {
            "field_hit_correct": "人工填 1/0：字段是否被正确判断为命中或未命中。",
            "value_correct": "人工填 1/0：抽取值、单位、年份是否正确；定性字段可按 summary/value 是否准确判断。",
            "evidence_usable": "人工填 1/0：证据原文和页码是否足够支持该字段。",
        },
    }
    summary_path = output_dir / "evaluation_metrics.json"
    write_json(summary_path, summary)
    return {"table": str(table_path), "summary": str(summary_path)}


def build_review_page(run_dir: Path, output_path: Path) -> None:
    results = _read_optional_json(run_dir / "extraction_results.json", [])
    contexts = _read_optional_json(run_dir / "field_contexts.json", {})
    chunks = _read_optional_json(run_dir / "rag_chunks.json", [])
    chunks_by_id = {str(chunk.get("chunk_id")): chunk for chunk in chunks if chunk.get("chunk_id")}
    summary = _read_optional_json(run_dir / "extraction_summary.json", {})
    ratio = _mineru_ratio(run_dir)
    rows = []
    for row in results:
        row_contexts = contexts.get(row.get("field_key"), [])
        short_source = _short_source_text(row, row_contexts, chunks_by_id=chunks_by_id)
        rows.append({
            **row,
            "source_text_short": short_source.get("text", ""),
            "source_text_short_page": short_source.get("page", ""),
            "source_text_short_chunk_id": short_source.get("chunk_id", ""),
            "contexts": row_contexts[:3],
        })
    payload = {
        "runDir": str(run_dir),
        "summary": summary,
        "mineru": ratio,
        "rows": rows,
    }
    data = html.escape(json.dumps(payload, ensure_ascii=False), quote=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_review_html(data), encoding="utf-8")


def _review_html(escaped_payload: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ESG 抽取复核</title>
  <style>
    :root {{ font-family: Arial, "Microsoft YaHei", sans-serif; color: #17202a; background: #f6f7f9; }}
    body {{ margin: 0; }}
    header {{ padding: 16px 20px; background: #ffffff; border-bottom: 1px solid #d9dee7; display: flex; gap: 16px; align-items: center; justify-content: space-between; }}
    h1 {{ font-size: 18px; margin: 0; }}
    button, select, input {{ font: inherit; }}
    button {{ border: 1px solid #2f6fed; background: #2f6fed; color: #fff; border-radius: 6px; padding: 8px 12px; cursor: pointer; }}
    .meta {{ color: #5c6675; font-size: 13px; }}
    .shell {{ display: grid; grid-template-columns: 280px minmax(300px, 420px) 1fr; height: calc(100vh - 66px); }}
    .panel {{ overflow: auto; border-right: 1px solid #d9dee7; background: #fff; }}
    .fields {{ list-style: none; margin: 0; padding: 0; }}
    .field {{ padding: 10px 12px; border-bottom: 1px solid #edf0f4; cursor: pointer; }}
    .field.active {{ background: #eaf1ff; }}
    .field small {{ display: block; color: #647084; margin-top: 4px; }}
    .value {{ padding: 16px; }}
    .kv {{ margin-bottom: 14px; }}
    .kv label {{ display: block; font-size: 12px; color: #647084; margin-bottom: 5px; }}
    .box {{ background: #fff; border: 1px solid #d9dee7; border-radius: 6px; padding: 10px; min-height: 34px; white-space: pre-wrap; overflow-wrap: anywhere; }}
    .evidence {{ padding: 16px; overflow: auto; }}
    .context {{ background: #fff; border: 1px solid #d9dee7; border-radius: 6px; padding: 12px; margin-bottom: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }}
    .context.primary {{ border-color: #7aa7ff; background: #f7faff; }}
    details {{ margin-top: 12px; }}
    summary {{ cursor: pointer; color: #2f6fed; font-weight: 600; margin-bottom: 10px; }}
    .toolbar {{ display: flex; gap: 8px; align-items: center; }}
    .pill {{ display: inline-block; border-radius: 999px; padding: 2px 8px; background: #eef1f5; color: #384252; font-size: 12px; }}
    @media (max-width: 980px) {{ .shell {{ grid-template-columns: 1fr; height: auto; }} .panel {{ max-height: 340px; }} }}
  </style>
</head>
<body>
<script id="payload" type="application/json">{escaped_payload}</script>
<header>
  <div>
    <h1>ESG 抽取复核</h1>
    <div class="meta" id="meta"></div>
  </div>
  <div class="toolbar">
    <input id="search" placeholder="搜索字段/值/证据">
    <select id="filter">
      <option value="all">全部</option>
      <option value="matched">已命中</option>
      <option value="unmatched">未命中</option>
    </select>
    <button id="export">导出 CSV</button>
  </div>
</header>
<main class="shell">
  <section class="panel"><ul class="fields" id="fields"></ul></section>
  <section class="panel value" id="value"></section>
  <section class="evidence" id="evidence"></section>
</main>
<script>
const payload = JSON.parse(document.getElementById('payload').textContent);
let rows = payload.rows || [];
let active = 0;
const $ = id => document.getElementById(id);
function escapeHtml(value) {{
  return String(value ?? '').replace(/[&<>"']/g, char => ({{'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}}[char]));
}}
function text(value) {{ return value === null || value === undefined || value === '' ? '-' : String(value); }}
function csvCell(value) {{ return '"' + text(value).replaceAll('"', '""') + '"'; }}
function filteredRows() {{
  const q = $('search').value.trim().toLowerCase();
  const f = $('filter').value;
  return rows.filter(row => {{
    if (f === 'matched' && !row.matched) return false;
    if (f === 'unmatched' && row.matched) return false;
    if (!q) return true;
    return [row.field_key, row.name_cn, row.value, row.summary, row.evidence, row.source_text_short].some(v => text(v).toLowerCase().includes(q));
  }});
}}
function renderList() {{
  const list = filteredRows();
  $('fields').innerHTML = list.map((row, i) => `
    <li class="field ${{i === active ? 'active' : ''}}" onclick="active=${{i}};render()">
      <strong>${{escapeHtml(text(row.name_cn))}}</strong>
      <small>${{escapeHtml(text(row.field_key))}} · ${{row.matched ? '已命中' : '未命中'}} · p.${{escapeHtml(text(row.source_page))}}</small>
    </li>`).join('');
}}
function renderDetail(row) {{
  $('value').innerHTML = `
    <div class="kv"><label>字段</label><div class="box">${{escapeHtml(text(row.name_cn))}} <span class="pill">${{escapeHtml(text(row.category))}}</span></div></div>
    <div class="kv"><label>抽取值</label><div class="box">${{escapeHtml(text(row.value))}} ${{escapeHtml(text(row.unit))}} ${{escapeHtml(text(row.year))}}</div></div>
    <div class="kv"><label>摘要</label><div class="box">${{escapeHtml(text(row.summary))}}</div></div>
    <div class="kv"><label>置信度 / 页码</label><div class="box">${{escapeHtml(text(row.confidence))}} / p.${{escapeHtml(text(row.source_page))}}</div></div>
    <div class="kv"><label>原因</label><div class="box">${{escapeHtml(text(row.reason))}}</div></div>`;
  const contexts = row.contexts || [];
  $('evidence').innerHTML = `
    <h2 style="font-size:16px;margin-top:0">证据原文和页码</h2>
    <div class="context primary"><span class="pill">原文短证据 p.${{escapeHtml(text(row.source_text_short_page))}} · ${{escapeHtml(text(row.source_text_short_chunk_id))}}</span><br><br>${{escapeHtml(text(row.source_text_short))}}</div>
    <div class="context"><span class="pill">模型证据 p.${{escapeHtml(text(row.source_page))}}</span><br><br>${{escapeHtml(text(row.evidence))}}</div>
    <details>
      <summary>展开完整召回上下文（${{contexts.length}}）</summary>
      ${{contexts.map(ctx => `<div class="context"><span class="pill">${{escapeHtml(text(ctx.chunk_id))}} · p.${{escapeHtml(text(ctx.page))}} · score ${{escapeHtml(text(ctx.score))}}</span><br><br>${{escapeHtml(text(ctx.text))}}</div>`).join('')}}
    </details>`;
}}
function render() {{
  const list = filteredRows();
  if (active >= list.length) active = 0;
  renderList();
  renderDetail(list[active] || {{}});
  $('meta').textContent = `${{payload.runDir}} · 字段 ${{rows.length}} · MinerU 页面比例 ${{payload.mineru.mineru_page_ratio}}`;
}}
function exportCsv() {{
  const columns = ['field_key','name_cn','category','indicator_type','matched','value','unit','year','source_text_short','source_text_short_page','evidence','source_page','confidence','reason'];
  const lines = [columns.join(',')].concat(rows.map(row => columns.map(col => csvCell(row[col] ?? '')).join(',')));
  const blob = new Blob(['\\ufeff' + lines.join('\\n')], {{type: 'text/csv;charset=utf-8'}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'review_export.csv'; a.click();
  URL.revokeObjectURL(url);
}}
$('search').addEventListener('input', () => {{ active = 0; render(); }});
$('filter').addEventListener('change', () => {{ active = 0; render(); }});
$('export').addEventListener('click', exportCsv);
render();
</script>
</body>
</html>
"""
