from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


@dataclass(frozen=True)
class Settings:
    project_root: Path
    pdf_parser_backend: str
    mineru_auto_run_enabled: bool
    mineru_command: str
    mineru_output_root: Path
    mineru_timeout_seconds: int
    selective_mineru_max_pages: int
    selective_mineru_score_threshold: int
    mineru_llm_review_enabled: bool
    mineru_llm_review_low_threshold: int
    mineru_llm_review_high_threshold: int
    mineru_llm_review_max_pages: int
    original_esg_project_root: Path
    dashscope_api_key: str
    openai_base_url: str
    text_model: str
    vlm_model: str
    schema_judge_model: str
    schema_judge_fallback_model: str
    llm_extraction_enabled: bool
    llm_max_calls_per_report: int
    llm_field_batch_size: int
    rag_top_k: int
    target_report_year: str


def _bool_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "y", "on"}


def load_settings(start: Path | None = None) -> Settings:
    root = Path(start or Path.cwd()).resolve()
    load_dotenv(root / "configs" / ".env")
    load_dotenv(root / ".env", override=True)
    original_root = Path(os.getenv(
        "ORIGINAL_ESG_PROJECT_ROOT",
        r"C:\Users\18130\PycharmProjects\爬虫\esg-multimodal-extraction-agent",
    ))
    original_values = dotenv_values(original_root / ".env")
    for key, value in original_values.items():
        if value and not os.getenv(key):
            os.environ[key] = value
    load_dotenv(root / ".env", override=True)
    return Settings(
        project_root=root,
        pdf_parser_backend=os.getenv("PDF_PARSER_BACKEND", "auto").lower(),
        mineru_auto_run_enabled=_bool_env("MINERU_AUTO_RUN_ENABLED"),
        mineru_command=os.getenv("MINERU_COMMAND", ""),
        mineru_output_root=Path(os.getenv("MINERU_OUTPUT_ROOT", "output/mineru_cache")),
        mineru_timeout_seconds=int(os.getenv("MINERU_TIMEOUT_SECONDS", "1800")),
        selective_mineru_max_pages=int(os.getenv("SELECTIVE_MINERU_MAX_PAGES", "12")),
        selective_mineru_score_threshold=int(os.getenv("SELECTIVE_MINERU_SCORE_THRESHOLD", "35")),
        mineru_llm_review_enabled=_bool_env("MINERU_LLM_REVIEW_ENABLED"),
        mineru_llm_review_low_threshold=int(os.getenv("MINERU_LLM_REVIEW_LOW_THRESHOLD", "25")),
        mineru_llm_review_high_threshold=int(os.getenv("MINERU_LLM_REVIEW_HIGH_THRESHOLD", "45")),
        mineru_llm_review_max_pages=int(os.getenv("MINERU_LLM_REVIEW_MAX_PAGES", "20")),
        original_esg_project_root=original_root,
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY", "") or str(original_values.get("DASHSCOPE_API_KEY") or ""),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        text_model=os.getenv("TEXT_MODEL", "qwen-plus-2025-09-11"),
        vlm_model=os.getenv("VLM_MODEL", "qwen-vl-plus"),
        schema_judge_model=os.getenv("SCHEMA_JUDGE_MODEL", "qwen3.6-flash"),
        schema_judge_fallback_model=os.getenv("SCHEMA_JUDGE_FALLBACK_MODEL", "qwen3.6-plus"),
        llm_extraction_enabled=_bool_env("LLM_EXTRACTION_ENABLED", "true"),
        llm_max_calls_per_report=int(os.getenv("LLM_MAX_CALLS_PER_REPORT", "12")),
        llm_field_batch_size=int(os.getenv("LLM_FIELD_BATCH_SIZE", "6")),
        rag_top_k=int(os.getenv("RAG_TOP_K", "3")),
        target_report_year=os.getenv("TARGET_REPORT_YEAR", "2024").strip(),
    )


