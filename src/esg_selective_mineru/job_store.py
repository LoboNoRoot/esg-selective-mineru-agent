from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class JobStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    report_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    file_sha256 TEXT NOT NULL DEFAULT '',
                    pdf_path TEXT NOT NULL,
                    upload_bytes INTEGER NOT NULL DEFAULT 0,
                    company_name TEXT NOT NULL DEFAULT '',
                    stock_code TEXT NOT NULL DEFAULT '',
                    report_year TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    report_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    pdf_path TEXT NOT NULL,
                    output_dir TEXT NOT NULL,
                    use_llm INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    upload_bytes INTEGER NOT NULL DEFAULT 0,
                    file_sha256 TEXT NOT NULL DEFAULT '',
                    retry_count INTEGER NOT NULL DEFAULT 0
                )
            """)
            self._ensure_column(conn, "jobs", "report_id", "TEXT NOT NULL DEFAULT ''")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reviews (
                    job_id TEXT NOT NULL,
                    field_key TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    value TEXT,
                    unit TEXT,
                    year TEXT,
                    evidence TEXT,
                    reviewer_note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (job_id, field_key),
                    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS extraction_results (
                    job_id TEXT NOT NULL,
                    field_key TEXT NOT NULL,
                    name_cn TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    indicator_type TEXT NOT NULL DEFAULT '',
                    matched INTEGER NOT NULL DEFAULT 0,
                    value TEXT,
                    unit TEXT,
                    year TEXT,
                    summary TEXT,
                    evidence TEXT,
                    source_chunk_id TEXT,
                    source_page TEXT,
                    confidence REAL NOT NULL DEFAULT 0,
                    normalized_value TEXT,
                    normalized_unit TEXT,
                    quality_warnings_json TEXT NOT NULL DEFAULT '[]',
                    row_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (job_id, field_key),
                    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE (job_id, artifact_type, path),
                    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_file_sha256 ON reports(file_sha256)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON jobs(updated_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_report_id ON jobs(report_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_file_sha256 ON jobs(file_sha256)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_extraction_results_field_key ON extraction_results(field_key)")

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
        job = dict(row)
        job["use_llm"] = bool(job.get("use_llm"))
        job["summary"] = json.loads(str(job.pop("summary_json") or "{}"))
        return job

    def upsert_report(self, report: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reports (
                    report_id, filename, file_sha256, pdf_path, upload_bytes,
                    company_name, stock_code, report_year, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_id) DO UPDATE SET
                    filename=excluded.filename,
                    file_sha256=excluded.file_sha256,
                    pdf_path=excluded.pdf_path,
                    upload_bytes=excluded.upload_bytes,
                    company_name=excluded.company_name,
                    stock_code=excluded.stock_code,
                    report_year=excluded.report_year,
                    updated_at=excluded.updated_at
                """,
                (
                    report["report_id"],
                    report.get("filename", ""),
                    report.get("file_sha256", ""),
                    report.get("pdf_path", ""),
                    int(report.get("upload_bytes") or 0),
                    report.get("company_name", ""),
                    report.get("stock_code", ""),
                    report.get("report_year", ""),
                    report.get("created_at", ""),
                    report.get("updated_at", report.get("created_at", "")),
                ),
            )

    def upsert_job(self, job: dict[str, Any]) -> None:
        summary_json = json.dumps(job.get("summary") or {}, ensure_ascii=False)
        report_id = str(job.get("report_id") or job.get("file_sha256") or job["job_id"])
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, report_id, status, mode, pdf_path, output_dir, use_llm,
                    created_at, updated_at, error, summary_json,
                    upload_bytes, file_sha256, retry_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    report_id=excluded.report_id,
                    status=excluded.status,
                    mode=excluded.mode,
                    pdf_path=excluded.pdf_path,
                    output_dir=excluded.output_dir,
                    use_llm=excluded.use_llm,
                    updated_at=excluded.updated_at,
                    error=excluded.error,
                    summary_json=excluded.summary_json,
                    upload_bytes=excluded.upload_bytes,
                    file_sha256=excluded.file_sha256,
                    retry_count=excluded.retry_count
                """,
                (
                    job["job_id"],
                    report_id,
                    job["status"],
                    job["mode"],
                    job["pdf_path"],
                    job["output_dir"],
                    1 if job.get("use_llm", True) else 0,
                    job["created_at"],
                    job["updated_at"],
                    job.get("error", ""),
                    summary_json,
                    int(job.get("upload_bytes") or 0),
                    job.get("file_sha256", ""),
                    int(job.get("retry_count") or 0),
                ),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY updated_at DESC").fetchall()
        return [self._row_to_job(row) for row in rows]

    def delete_job(self, job_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM artifacts WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM extraction_results WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM reviews WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))

    def read_reviews(self, job_id: str) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM reviews WHERE job_id = ?", (job_id,)).fetchall()
        return {str(row["field_key"]): dict(row) for row in rows}

    def write_review(self, job_id: str, field_key: str, record: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reviews (
                    job_id, field_key, status, value, unit, year,
                    evidence, reviewer_note, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, field_key) DO UPDATE SET
                    status=excluded.status,
                    value=excluded.value,
                    unit=excluded.unit,
                    year=excluded.year,
                    evidence=excluded.evidence,
                    reviewer_note=excluded.reviewer_note,
                    updated_at=excluded.updated_at
                """,
                (
                    job_id,
                    field_key,
                    record.get("status", "pending"),
                    record.get("value"),
                    record.get("unit"),
                    record.get("year"),
                    record.get("evidence"),
                    record.get("reviewer_note", ""),
                    record["updated_at"],
                ),
            )

    def upsert_extraction_results(self, job_id: str, rows: list[dict[str, Any]], updated_at: str) -> None:
        with self._connect() as conn:
            for row in rows:
                field_key = str(row.get("field_key") or "")
                if not field_key:
                    continue
                conn.execute(
                    """
                    INSERT INTO extraction_results (
                        job_id, field_key, name_cn, category, indicator_type, matched,
                        value, unit, year, summary, evidence, source_chunk_id, source_page,
                        confidence, normalized_value, normalized_unit,
                        quality_warnings_json, row_json, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id, field_key) DO UPDATE SET
                        name_cn=excluded.name_cn,
                        category=excluded.category,
                        indicator_type=excluded.indicator_type,
                        matched=excluded.matched,
                        value=excluded.value,
                        unit=excluded.unit,
                        year=excluded.year,
                        summary=excluded.summary,
                        evidence=excluded.evidence,
                        source_chunk_id=excluded.source_chunk_id,
                        source_page=excluded.source_page,
                        confidence=excluded.confidence,
                        normalized_value=excluded.normalized_value,
                        normalized_unit=excluded.normalized_unit,
                        quality_warnings_json=excluded.quality_warnings_json,
                        row_json=excluded.row_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        job_id,
                        field_key,
                        str(row.get("name_cn") or ""),
                        str(row.get("category") or ""),
                        str(row.get("indicator_type") or ""),
                        1 if row.get("matched") else 0,
                        row.get("value"),
                        row.get("unit"),
                        row.get("year"),
                        row.get("summary"),
                        row.get("evidence"),
                        row.get("source_chunk_id"),
                        str(row.get("source_page") or ""),
                        float(row.get("confidence") or 0),
                        row.get("normalized_value"),
                        row.get("normalized_unit"),
                        json.dumps(row.get("quality_warnings") or [], ensure_ascii=False),
                        json.dumps(row, ensure_ascii=False),
                        updated_at,
                    ),
                )

    def read_extraction_results(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT row_json FROM extraction_results WHERE job_id = ? ORDER BY rowid",
                (job_id,),
            ).fetchall()
        return [json.loads(str(row["row_json"])) for row in rows]

    def add_artifact(self, job_id: str, artifact_type: str, path: str, mime_type: str, created_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO artifacts (job_id, artifact_type, path, mime_type, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, artifact_type, path, mime_type, created_at),
            )

    def list_artifacts(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, job_id, artifact_type, path, mime_type, created_at FROM artifacts WHERE job_id = ? ORDER BY id",
                (job_id,),
            ).fetchall()
        return [dict(row) for row in rows]
