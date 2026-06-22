from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any, Dict, List

from esg_selective_mineru.config import load_settings
from esg_selective_mineru.dataset import preprocess_pdf, write_manifest_csv


def _read_manifest(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _iter_pdfs(args: argparse.Namespace) -> List[Dict[str, Any]]:
    manifest_rows = _read_manifest(args.manifest) if args.manifest else []
    if manifest_rows:
        rows = []
        for row in manifest_rows:
            pdf = Path(str(row.get("local_pdf") or ""))
            if pdf.exists():
                rows.append({"report_id": row.get("report_id") or pdf.stem, "pdf": pdf})
        return rows
    return [{"report_id": path.stem, "pdf": path} for path in sorted(args.input.glob("*.pdf"))]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preprocess ESG PDFs into normalized dataset artifacts.")
    parser.add_argument("--input", type=Path, default=Path("data/a_share_esg_reports/raw"))
    parser.add_argument("--manifest", type=Path, default=Path("data/a_share_esg_reports/a_share_esg_reports_manifest.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/a_share_esg_reports"))
    parser.add_argument("--limit", type=int, default=0, help="0 means all PDFs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings()
    rows = _iter_pdfs(args)
    if args.limit > 0:
        rows = rows[:args.limit]
    summaries: List[Dict[str, Any]] = []
    seen_hashes = set()
    for index, item in enumerate(rows, start=1):
        pdf = item["pdf"]
        print(f"preprocess {index}/{len(rows)} {pdf}")
        profile = preprocess_pdf(pdf, args.output, settings, report_id=str(item["report_id"]))
        row = profile.__dict__
        row["duplicate_sha256"] = profile.sha256 in seen_hashes
        seen_hashes.add(profile.sha256)
        summaries.append(row)
    write_manifest_csv(args.output / "preprocess_manifest.csv", summaries)
    print(f"processed={len(summaries)} manifest={args.output / 'preprocess_manifest.csv'}")
    if len(summaries) < 100:
        print(f"warning=processed_less_than_100 count={len(summaries)}")


if __name__ == "__main__":
    main()
