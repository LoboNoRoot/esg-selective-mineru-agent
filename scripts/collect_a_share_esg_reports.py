from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List


CNINFO_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STATIC_ROOT = "http://static.cninfo.com.cn/"
DEFAULT_KEYWORDS = ["ESG报告", "环境、社会和公司治理报告", "社会责任报告", "可持续发展报告"]
SAFE_NAME_RE = re.compile(r"[\\/:*?\"<>|\s]+")


def _post_form(url: str, data: Dict[str, str], *, timeout: int = 30) -> Dict[str, Any]:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "Mozilla/5.0 ESG dataset collector",
            "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _download(url: str, path: Path, *, timeout: int = 60) -> int:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 ESG dataset collector",
            "Referer": "http://www.cninfo.com.cn/",
        },
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=timeout) as response, path.open("wb") as handle:
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            handle.write(chunk)
    return total


def _safe_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"</?em>", "", text, flags=re.IGNORECASE)
    text = SAFE_NAME_RE.sub("_", text)
    return text.strip("._")


def _announcement_pdf_url(row: Dict[str, Any]) -> str:
    adjunct_url = str(row.get("adjunctUrl") or "").lstrip("/")
    if adjunct_url.startswith("http"):
        return adjunct_url
    return urllib.parse.urljoin(CNINFO_STATIC_ROOT, adjunct_url)


def search_cninfo(keyword: str, *, page: int, page_size: int, se_date: str) -> List[Dict[str, Any]]:
    payload = {
        "pageNum": str(page),
        "pageSize": str(page_size),
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": "",
        "searchkey": keyword,
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": se_date,
        "sortName": "time",
        "sortType": "desc",
        "isHLtitle": "true",
    }
    data = _post_form(CNINFO_QUERY_URL, payload)
    announcements = data.get("announcements") or []
    return [row for row in announcements if isinstance(row, dict)]


def iter_announcements(keywords: Iterable[str], *, pages: int, page_size: int, se_date: str, sleep_seconds: float) -> Iterable[Dict[str, Any]]:
    seen = set()
    for keyword in keywords:
        for page in range(1, pages + 1):
            rows = search_cninfo(keyword, page=page, page_size=page_size, se_date=se_date)
            if not rows:
                break
            for row in rows:
                adjunct_url = str(row.get("adjunctUrl") or "")
                title = str(row.get("announcementTitle") or "")
                key = adjunct_url or f"{row.get('secCode')}:{title}:{row.get('announcementTime')}"
                if key in seen or not adjunct_url.lower().endswith(".pdf"):
                    continue
                seen.add(key)
                row["search_keyword"] = keyword
                yield row
            time.sleep(sleep_seconds)


def write_manifest(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "report_id", "sec_code", "sec_name", "org_id", "title", "announcement_time",
        "search_keyword", "pdf_url", "local_pdf", "download_bytes",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def collect_reports(args: argparse.Namespace) -> List[Dict[str, Any]]:
    raw_dir = args.output / "raw"
    manifest_rows: List[Dict[str, Any]] = []
    for row in iter_announcements(
        args.keyword,
        pages=args.pages,
        page_size=args.page_size,
        se_date=args.se_date,
        sleep_seconds=args.sleep,
    ):
        sec_code = _safe_text(row.get("secCode"))
        sec_name = _safe_text(row.get("secName"))
        title = _safe_text(row.get("announcementTitle"))
        announcement_time = str(row.get("announcementTime") or "")
        year = announcement_time[:4] if announcement_time else "unknown"
        report_id = f"{sec_code}_{sec_name}_{year}_{len(manifest_rows) + 1:03d}"
        pdf_url = _announcement_pdf_url(row)
        local_pdf = raw_dir / f"{report_id}_{title[:80]}.pdf"
        try:
            download_bytes = _download(pdf_url, local_pdf)
        except Exception as exc:
            print(f"download_failed sec={sec_code} title={title} error={exc}")
            continue
        manifest_rows.append({
            "report_id": report_id,
            "sec_code": sec_code,
            "sec_name": sec_name,
            "org_id": row.get("orgId", ""),
            "title": title,
            "announcement_time": announcement_time,
            "search_keyword": row.get("search_keyword", ""),
            "pdf_url": pdf_url,
            "local_pdf": str(local_pdf),
            "download_bytes": download_bytes,
        })
        print(f"downloaded {len(manifest_rows)}/{args.limit}: {local_pdf.name}")
        if len(manifest_rows) >= args.limit:
            break
        time.sleep(args.sleep)
    write_manifest(args.output / "a_share_esg_reports_manifest.csv", manifest_rows)
    (args.output / "a_share_esg_reports_manifest.json").write_text(
        json.dumps(manifest_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect A-share ESG PDF reports from CNINFO.")
    parser.add_argument("--output", type=Path, default=Path("data/a_share_esg_reports"))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--keyword", action="append", default=None, help="repeatable search keyword")
    parser.add_argument("--se-date", default="2023-01-01~2026-12-31", help="CNINFO date range")
    parser.add_argument("--pages", type=int, default=20)
    parser.add_argument("--page-size", type=int, default=30)
    parser.add_argument("--sleep", type=float, default=0.8)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.keyword = args.keyword or DEFAULT_KEYWORDS
    rows = collect_reports(args)
    print(f"collected={len(rows)} manifest={args.output / 'a_share_esg_reports_manifest.csv'}")
    if len(rows) < args.limit:
        raise SystemExit(f"only_collected_{len(rows)}_reports")


if __name__ == "__main__":
    main()
