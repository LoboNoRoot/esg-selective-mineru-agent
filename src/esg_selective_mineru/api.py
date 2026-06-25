from __future__ import annotations

import csv
import hashlib
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings, load_settings
from .extractor import extract_report
from .io_utils import read_json, write_json
from .job_store import JobStore
from .pipeline import run_pipeline, scan_only
from .quality import enrich_results, quality_summary
from .report_filter import assess_report_suitability


JobMode = Literal["scan", "extract", "run"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "skipped"]
ReviewStatus = Literal["pending", "approved", "rejected", "edited"]
MAX_UPLOAD_BYTES = 80 * 1024 * 1024


class CreateJobResponse(BaseModel):
    job_id: str
    status: JobStatus
    mode: JobMode
    output_dir: str


class BatchCreateJobResponse(BaseModel):
    jobs: list[CreateJobResponse]


class JobDetail(BaseModel):
    job_id: str
    status: JobStatus
    mode: JobMode
    pdf_path: str
    output_dir: str
    use_llm: bool = True
    created_at: str
    updated_at: str
    error: str = ""
    summary: Dict[str, Any] = Field(default_factory=dict)


class JobListResponse(BaseModel):
    jobs: list[JobDetail]


class ReviewUpdate(BaseModel):
    status: ReviewStatus = "pending"
    value: str | None = None
    unit: str | None = None
    year: str | None = None
    evidence: str | None = None
    reviewer_note: str = ""


class ReviewRecord(ReviewUpdate):
    field_key: str
    updated_at: str


settings = load_settings()


def _database_path() -> Path:
    url = settings.database_url
    if url.startswith("sqlite:///"):
        path = Path(url.removeprefix("sqlite:///"))
        return path if path.is_absolute() else settings.project_root / path
    return settings.project_root / "data" / "esg_jobs.db"


job_store = JobStore(_database_path())
app = FastAPI(
    title="ESG Selective MinerU API",
    version="0.1.0",
    description="Backend API for ESG report scanning, selective MinerU parsing, and 60-field extraction.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
react_dist_dir = settings.project_root / "frontend-react" / "dist"
frontend_dir = react_dist_dir if react_dist_dir.exists() else settings.project_root / "frontend"
if frontend_dir.exists():
    app.mount("/frontend", StaticFiles(directory=frontend_dir), name="frontend")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _storage_root(settings: Settings) -> Path:
    root = settings.project_root
    path = root / "data" / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _api_output_root(settings: Settings) -> Path:
    path = settings.project_root / "output" / "api_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _job_dir(job_id: str) -> Path:
    return _api_output_root(settings) / job_id


def _job_meta_path(job_id: str) -> Path:
    return _job_dir(job_id) / "job.json"


def _review_path(job_id: str) -> Path:
    return _job_dir(job_id) / "reviews.json"


def _write_job(job: Dict[str, Any]) -> None:
    job["updated_at"] = _now()
    write_json(_job_meta_path(job["job_id"]), job)
    job_store.upsert_job(job)


def _write_report_for_job(job: Dict[str, Any], filename: str = "") -> None:
    now = job.get("created_at") or _now()
    pdf_path = str(job.get("pdf_path") or "")
    report_id = str(job.get("report_id") or job.get("file_sha256") or job["job_id"])
    job["report_id"] = report_id
    job_store.upsert_report({
        "report_id": report_id,
        "filename": filename or Path(pdf_path).name,
        "file_sha256": job.get("file_sha256", ""),
        "pdf_path": pdf_path,
        "upload_bytes": job.get("upload_bytes", 0),
        "created_at": now,
        "updated_at": job.get("updated_at") or now,
    })


def _sync_job_artifacts(job: Dict[str, Any]) -> None:
    job_id = str(job["job_id"])
    output_dir = Path(str(job["output_dir"]))
    artifact_specs = {
        "job_meta": ("job.json", "application/json"),
        "skip_report": ("skip_report.json", "application/json"),
        "run_summary": ("run_summary.json", "application/json"),
        "page_scan": ("page_scan.json", "application/json"),
        "parse_plan": ("parse_plan.json", "application/json"),
        "visual_fallback_queue": ("visual_fallback_queue.json", "application/json"),
        "mineru_jobs": ("mineru_jobs.json", "application/json"),
        "rag_chunks": ("rag_chunks.json", "application/json"),
        "field_contexts": ("field_contexts.json", "application/json"),
        "extraction_summary": ("extraction_summary.json", "application/json"),
        "extraction_results_json": ("extraction_results.json", "application/json"),
        "extraction_results_csv": ("extraction_results.csv", "text/csv"),
        "reviewed_extraction_results_csv": ("reviewed_extraction_results.csv", "text/csv"),
    }
    for artifact_type, (filename, mime_type) in artifact_specs.items():
        path = output_dir / filename
        if path.exists():
            job_store.add_artifact(job_id, artifact_type, str(path), mime_type, _now())


def _sync_extraction_results(job: Dict[str, Any]) -> list[Dict[str, Any]]:
    job_id = str(job["job_id"])
    path = Path(str(job["output_dir"])) / "extraction_results.json"
    if not path.exists():
        return []
    rows = read_json(path)
    if not isinstance(rows, list):
        raise HTTPException(status_code=500, detail="invalid_results_format")
    rows = enrich_results(rows, pdf_path=job.get("pdf_path", ""), target_year=settings.target_report_year)
    job_store.upsert_extraction_results(job_id, rows, _now())
    return rows


def _read_job(job_id: str) -> Dict[str, Any]:
    job = job_store.get_job(job_id)
    if job is not None:
        return job
    path = _job_meta_path(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="job_not_found")
    job = read_json(path)
    if isinstance(job, dict):
        _write_report_for_job(job)
        job_store.upsert_job(job)
    return job


def _safe_pdf_name(filename: str) -> str:
    name = Path(filename or "report.pdf").name
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="only_pdf_is_supported")
    return name


def _read_reviews(job_id: str) -> Dict[str, Any]:
    reviews = job_store.read_reviews(job_id)
    if reviews:
        return reviews
    path = _review_path(job_id)
    if not path.exists():
        return {}
    data = read_json(path)
    if isinstance(data, dict):
        for field_key, record in data.items():
            if isinstance(record, dict):
                job_store.write_review(job_id, str(field_key), {**record, "updated_at": record.get("updated_at") or _now()})
    return data if isinstance(data, dict) else {}


def _write_reviews(job_id: str, reviews: Dict[str, Any]) -> None:
    write_json(_review_path(job_id), reviews)
    for field_key, record in reviews.items():
        if isinstance(record, dict):
            job_store.write_review(job_id, str(field_key), record)


def _list_jobs() -> list[Dict[str, Any]]:
    stored_jobs = job_store.list_jobs()
    if stored_jobs:
        return stored_jobs
    root = _api_output_root(settings)
    jobs: list[Dict[str, Any]] = []
    for path in root.glob("*/job.json"):
        try:
            job = read_json(path)
            if isinstance(job, dict):
                job_store.upsert_job(job)
                jobs.append(job)
        except Exception:
            continue
    return sorted(jobs, key=lambda item: str(item.get("updated_at") or ""), reverse=True)


def _find_duplicate_job(file_sha256: str) -> Dict[str, Any] | None:
    for job in _list_jobs():
        if file_sha256 and job.get("file_sha256") == file_sha256:
            return job
    return None


def _review_priority(row: Dict[str, Any], review: Dict[str, Any]) -> int:
    if review.get("status") in {"approved", "rejected"}:
        return 0
    score = 0
    try:
        confidence = float(row.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence <= 0:
        score += 45
    elif confidence < 0.7:
        score += 35
    elif confidence < 0.85:
        score += 15
    if not row.get("matched"):
        score += 25
    if not str(row.get("evidence") or "").strip():
        score += 20
    if not str(row.get("source_page") or "").strip():
        score += 10
    if int(row.get("evidence_score") or 0) < 50:
        score += 15
    if row.get("year_warning"):
        score += 15
    if row.get("unit_warning") and row.get("unit_warning") != "missing_unit":
        score += 10
    if review.get("status") == "edited":
        score += 5
    return min(score, 100)


def _merge_review(row: Dict[str, Any], review: Dict[str, Any]) -> Dict[str, Any]:
    merged = {**row}
    merged["review"] = review
    merged["review_priority"] = _review_priority(row, review)
    return merged


def _load_result_rows(job_id: str) -> list[Dict[str, Any]]:
    job = _read_job(job_id)
    rows = job_store.read_extraction_results(job_id)
    if not rows:
        rows = _sync_extraction_results(job)
    if not rows:
        raise HTTPException(status_code=404, detail="results_not_ready")
    reviews = _read_reviews(job_id)
    return [
        _merge_review(row, reviews.get(str(row.get("field_key") or ""), {"status": "pending"}))
        for row in rows
    ]


def _review_value(row: Dict[str, Any], key: str) -> Any:
    review = row.get("review") or {}
    value = review.get(key)
    return row.get(key, "") if value is None else value


def _write_reviewed_csv(job_id: str, rows: list[Dict[str, Any]]) -> Path:
    path = _job_dir(job_id) / "reviewed_extraction_results.csv"
    columns = [
        "field_key", "name_cn", "category", "indicator_type", "matched",
        "original_value", "original_unit", "original_year", "original_evidence",
        "review_status", "reviewed_value", "reviewed_unit", "reviewed_year",
        "reviewed_evidence", "reviewer_note", "review_priority",
        "target_year", "normalized_value", "normalized_unit", "unit_warning", "year_warning",
        "evidence_score", "quality_warnings",
        "source_chunk_id", "source_page", "confidence", "reason",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            review = row.get("review") or {}
            writer.writerow({
                "field_key": row.get("field_key", ""),
                "name_cn": row.get("name_cn", ""),
                "category": row.get("category", ""),
                "indicator_type": row.get("indicator_type", ""),
                "matched": row.get("matched", ""),
                "original_value": row.get("value", ""),
                "original_unit": row.get("unit", ""),
                "original_year": row.get("year", ""),
                "original_evidence": row.get("evidence", ""),
                "review_status": review.get("status", "pending"),
                "reviewed_value": _review_value(row, "value"),
                "reviewed_unit": _review_value(row, "unit"),
                "reviewed_year": _review_value(row, "year"),
                "reviewed_evidence": _review_value(row, "evidence"),
                "reviewer_note": review.get("reviewer_note", ""),
                "review_priority": row.get("review_priority", 0),
                "target_year": row.get("target_year", ""),
                "normalized_value": row.get("normalized_value", ""),
                "normalized_unit": row.get("normalized_unit", ""),
                "unit_warning": row.get("unit_warning", ""),
                "year_warning": row.get("year_warning", ""),
                "evidence_score": row.get("evidence_score", ""),
                "quality_warnings": ";".join(row.get("quality_warnings") or []),
                "source_chunk_id": row.get("source_chunk_id", ""),
                "source_page": row.get("source_page", ""),
                "confidence": row.get("confidence", ""),
                "reason": row.get("reason", ""),
            })
    return path


async def _save_upload(file: UploadFile, pdf_path: Path) -> tuple[int, str]:
    total = 0
    digest = hashlib.sha256()
    with pdf_path.open("wb") as handle:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                handle.close()
                pdf_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="pdf_too_large")
            digest.update(chunk)
            handle.write(chunk)
    return total, digest.hexdigest()


def _validate_upload(file: UploadFile, request: Request | None = None) -> str:
    filename = _safe_pdf_name(file.filename or "")
    if file.content_type and file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="invalid_pdf_content_type")
    if request is not None:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_UPLOAD_BYTES + 4096:
            raise HTTPException(status_code=413, detail="pdf_too_large")
    return filename


async def _create_job_from_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    *,
    mode: JobMode,
    use_llm: bool,
) -> CreateJobResponse:
    filename = _validate_upload(file)
    job_id = uuid.uuid4().hex
    job_dir = _job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = _storage_root(settings) / f"{job_id}_{filename}"
    upload_bytes, file_sha256 = await _save_upload(file, pdf_path)
    duplicate = _find_duplicate_job(file_sha256)
    if duplicate is not None:
        pdf_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=409,
            detail={
                "code": "duplicate_report",
                "message": "该 ESG 报告已经上传过，请在历史报告列表中查看原任务。",
                "job_id": duplicate.get("job_id"),
                "filename": Path(str(duplicate.get("pdf_path") or "")).name,
                "status": duplicate.get("status"),
            },
        )

    job = {
        "job_id": job_id,
        "report_id": file_sha256 or job_id,
        "status": "queued",
        "mode": mode,
        "pdf_path": str(pdf_path),
        "output_dir": str(job_dir),
        "use_llm": use_llm,
        "created_at": _now(),
        "updated_at": _now(),
        "error": "",
        "summary": {},
        "upload_bytes": upload_bytes,
        "file_sha256": file_sha256,
    }
    _write_report_for_job(job, filename)
    _write_job(job)
    background_tasks.add_task(_run_job, job_id)
    return CreateJobResponse(job_id=job_id, status="queued", mode=mode, output_dir=str(job_dir))


def _run_job(job_id: str) -> None:
    job = _read_job(job_id)
    job["status"] = "running"
    _write_job(job)
    pdf_path = Path(job["pdf_path"])
    output_dir = Path(job["output_dir"])
    try:
        suitability = assess_report_suitability(pdf_path)
        if suitability.get("should_skip"):
            job["status"] = "skipped"
            job["error"] = ""
            job["summary"] = {"skipped": True, **suitability}
            write_json(output_dir / "skip_report.json", job["summary"])
            write_json(output_dir / "run_summary.json", job["summary"])
            _write_job(job)
            _sync_job_artifacts(job)
            return
        mode = job["mode"]
        if mode == "scan":
            result = scan_only(pdf_path, output_dir, settings)
            job["summary"] = {
                "page_count": result["parse_plan"]["page_count"],
                "mineru_pages": len(result["parse_plan"]["mineru_pages"]),
                "visual_fallback_pages": len(result["parse_plan"]["visual_fallback_pages"]),
                "timing": result.get("timing", {}),
            }
        elif mode == "extract":
            result = extract_report(pdf_path, output_dir, settings, use_llm=bool(job["use_llm"]))
            job["summary"] = result["summary"]
        else:
            result = run_pipeline(
                pdf_path,
                output_dir,
                settings,
                extract=True,
                use_llm=bool(job["use_llm"]),
            )
            job["summary"] = result.get("summary", {})
        job["status"] = "succeeded"
        _sync_extraction_results(job)
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
    _write_job(job)
    _sync_job_artifacts(job)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    path = frontend_dir / "index.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="frontend_not_found")
    return FileResponse(path)


@app.post("/reports", response_model=CreateJobResponse, status_code=202)
async def create_report_job(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    mode: JobMode = "run",
    use_llm: bool = True,
) -> CreateJobResponse:
    _validate_upload(file, request)
    return await _create_job_from_upload(background_tasks, file, mode=mode, use_llm=use_llm)


@app.post("/reports/batch", response_model=BatchCreateJobResponse, status_code=202)
async def create_report_jobs_batch(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    mode: JobMode = "run",
    use_llm: bool = True,
) -> Dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="no_files")
    if len(files) > 100:
        raise HTTPException(status_code=400, detail="too_many_files")
    jobs = [
        await _create_job_from_upload(background_tasks, file, mode=mode, use_llm=use_llm)
        for file in files
    ]
    return {"jobs": jobs}


@app.get("/jobs", response_model=JobListResponse)
def list_jobs() -> Dict[str, Any]:
    return {"jobs": _list_jobs()}


@app.get("/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: str) -> Dict[str, Any]:
    return _read_job(job_id)


@app.post("/jobs/{job_id}/retry", response_model=CreateJobResponse, status_code=202)
def retry_job(job_id: str, background_tasks: BackgroundTasks) -> CreateJobResponse:
    job = _read_job(job_id)
    if job["status"] == "running":
        raise HTTPException(status_code=409, detail="job_is_running")
    job["status"] = "queued"
    job["error"] = ""
    job["summary"] = {}
    job["retry_count"] = int(job.get("retry_count") or 0) + 1
    _write_job(job)
    background_tasks.add_task(_run_job, job_id)
    return CreateJobResponse(job_id=job_id, status="queued", mode=job["mode"], output_dir=job["output_dir"])


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> Dict[str, Any]:
    job = _read_job(job_id)
    if job.get("status") == "running":
        raise HTTPException(status_code=409, detail="job_is_running")
    pdf_path = Path(str(job.get("pdf_path") or ""))
    if pdf_path.exists() and _storage_root(settings) in pdf_path.resolve().parents:
        pdf_path.unlink(missing_ok=True)
    job_dir = _job_dir(job_id)
    if job_dir.exists():
        shutil.rmtree(job_dir)
    job_store.delete_job(job_id)
    return {"deleted": True, "job_id": job_id}


@app.get("/jobs/{job_id}/results")
def get_job_results(job_id: str) -> Any:
    return _load_result_rows(job_id)


@app.get("/jobs/{job_id}/quality")
def get_job_quality(job_id: str) -> Dict[str, Any]:
    rows = _load_result_rows(job_id)
    return quality_summary(rows)


@app.get("/jobs/{job_id}/reviews")
def get_job_reviews(job_id: str) -> Dict[str, Any]:
    _read_job(job_id)
    return _read_reviews(job_id)


@app.put("/jobs/{job_id}/reviews/{field_key}", response_model=ReviewRecord)
def update_job_review(job_id: str, field_key: str, review: ReviewUpdate) -> Dict[str, Any]:
    _read_job(job_id)
    reviews = _read_reviews(job_id)
    record = review.model_dump() if hasattr(review, "model_dump") else review.dict()
    record["field_key"] = field_key
    record["updated_at"] = _now()
    reviews[field_key] = record
    _write_reviews(job_id, reviews)
    return record


@app.get("/jobs/{job_id}/summary")
def get_job_summary(job_id: str) -> Any:
    job = _read_job(job_id)
    if job.get("summary"):
        return job["summary"]
    path = Path(job["output_dir"]) / "extraction_summary.json"
    if path.exists():
        return read_json(path)
    return {}


@app.get("/jobs/{job_id}/export.csv")
def export_job_csv(job_id: str) -> FileResponse:
    rows = _load_result_rows(job_id)
    path = _write_reviewed_csv(job_id, rows)
    job_store.add_artifact(job_id, "reviewed_extraction_results_csv", str(path), "text/csv", _now())
    return FileResponse(path, media_type="text/csv", filename=f"{job_id}_reviewed_extraction_results.csv")


@app.get("/jobs/{job_id}/artifacts")
def get_job_artifacts(job_id: str) -> Dict[str, Any]:
    _read_job(job_id)
    return {"artifacts": job_store.list_artifacts(job_id)}
