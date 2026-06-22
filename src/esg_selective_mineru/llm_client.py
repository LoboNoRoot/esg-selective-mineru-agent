from __future__ import annotations

import json
from typing import Any, Dict, List

from openai import OpenAI

from .config import Settings


class LLMClient:
    def __init__(self, settings: Settings):
        if not settings.dashscope_api_key:
            raise RuntimeError("缺少 DASHSCOPE_API_KEY，请在新项目 .env 中配置，或从当前 shell 环境注入。")
        self.settings = settings
        self.client = OpenAI(api_key=settings.dashscope_api_key, base_url=settings.openai_base_url)

    def extract_fields(self, fields: List[Dict[str, Any]], contexts: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        prompt = _build_prompt(fields, contexts)
        completion = self.client.chat.completions.create(
            model=self.settings.text_model,
            messages=[
                {"role": "system", "content": "你是严谨的 A 股 ESG 报告结构化抽取助手。只基于给定证据抽取，不要编造。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = completion.choices[0].message.content or "{}"
        data = json.loads(content)
        results = data.get("results", data if isinstance(data, list) else [])
        if not isinstance(results, list):
            raise RuntimeError("模型返回不是 results 数组")
        return results


def _compact_field(field: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "field_key": field.get("field_key"),
        "name_cn": field.get("name_cn"),
        "category": field.get("category"),
        "indicator_type": field.get("indicator_type"),
        "expected_units": field.get("expected_units", []),
        "aliases": field.get("aliases", [])[:6],
        "domain_knowledge": field.get("domain_knowledge", ""),
    }


def _build_prompt(fields: List[Dict[str, Any]], contexts: Dict[str, List[Dict[str, Any]]]) -> str:
    compact_fields = [_compact_field(field) for field in fields]
    compact_contexts: Dict[str, List[Dict[str, Any]]] = {}
    for field in fields:
        key = field["field_key"]
        compact_contexts[key] = [
            {
                "chunk_id": item.get("chunk_id"),
                "source": item.get("source"),
                "page": item.get("page"),
                "score": item.get("score"),
                "text": (item.get("text") or "")[:1200],
            }
            for item in contexts.get(key, [])
        ]
    return (
        "请从给定 ESG 报告证据中抽取这些字段。\n"
        "要求：\n"
        "1. 每个字段必须返回一条结果。\n"
        "2. matched=false 表示未披露或证据不足。\n"
        "3. 定量字段优先抽取 value、unit、year；定性字段给出 summary。\n"
        "4. evidence 必须是证据中的短句，不超过 80 字。\n"
        "5. confidence 取 0-1。\n"
        "6. 只输出 JSON：{\"results\":[...]}。\n\n"
        "结果字段格式：field_key, matched, value, unit, year, summary, evidence, source_chunk_id, source_page, confidence, reason。\n\n"
        f"字段定义：\n{json.dumps(compact_fields, ensure_ascii=False)}\n\n"
        f"证据：\n{json.dumps(compact_contexts, ensure_ascii=False)}"
    )
