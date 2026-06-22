from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Dict, Iterable, List

TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> List[str]:
    return [m.group(0).lower() for m in TOKEN_RE.finditer(text or "")]


def _field_terms(field: Dict[str, Any]) -> List[str]:
    terms: List[str] = []
    for key in ["name_cn", "field_key", "topic", "domain_knowledge"]:
        value = field.get(key)
        if value:
            terms.append(str(value))
    for key in ["aliases", "search_terms", "required_any", "expected_units", "unit_examples"]:
        values = field.get(key) or []
        if isinstance(values, list):
            terms.extend(str(item) for item in values if item)
    return terms


class SimpleRetriever:
    def __init__(self, chunks: List[Dict[str, Any]]):
        self.chunks = chunks
        self.doc_tokens = [tokenize(item.get("text", "")) for item in chunks]
        self.doc_freq: Counter[str] = Counter()
        for tokens in self.doc_tokens:
            self.doc_freq.update(set(tokens))
        self.total_docs = max(len(chunks), 1)
        self.avg_len = sum(len(tokens) for tokens in self.doc_tokens) / self.total_docs if chunks else 1.0

    def _idf(self, token: str) -> float:
        return math.log(1 + (self.total_docs - self.doc_freq.get(token, 0) + 0.5) / (self.doc_freq.get(token, 0) + 0.5))

    def search(self, query: str, *, top_k: int = 5) -> List[Dict[str, Any]]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        query_counts = Counter(query_tokens)
        scored: List[Dict[str, Any]] = []
        for chunk, tokens in zip(self.chunks, self.doc_tokens):
            if not tokens:
                continue
            counts = Counter(tokens)
            score = 0.0
            for token, qf in query_counts.items():
                tf = counts.get(token, 0)
                if tf == 0:
                    continue
                denom = tf + 1.5 * (1 - 0.75 + 0.75 * len(tokens) / max(self.avg_len, 1.0))
                score += self._idf(token) * tf * 2.5 / denom * min(qf, 3)
            text = chunk.get("text", "")
            for raw_term in set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9 ]{2,}", query)):
                if raw_term and raw_term in text:
                    score += 2.0
            if score > 0:
                item = dict(chunk)
                item["score"] = round(score, 4)
                scored.append(item)
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def search_field(self, field: Dict[str, Any], *, top_k: int = 5) -> List[Dict[str, Any]]:
        return self.search(" ".join(_field_terms(field)), top_k=top_k)
