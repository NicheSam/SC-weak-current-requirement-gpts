from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Docling checkpoint and source Markdown output.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--source-document", type=Path, required=True)
    parser.add_argument("--review-document", type=Path)
    parser.add_argument("--expect-page-start", type=int, required=True)
    parser.add_argument("--expect-page-end", type=int, required=True)
    args = parser.parse_args()

    manifest = json.loads((args.run_dir / "manifest.json").read_text(encoding="utf-8"))
    expected = set(range(args.expect_page_start, args.expect_page_end + 1))
    actual = {
        int(page_no)
        for page_no, item in manifest["pages"].items()
        if item.get("pdf_aware_status") == "complete"
    }
    missing = sorted(expected - actual)
    text = args.source_document.read_text(encoding="utf-8")
    markers = {int(value) for value in re.findall(r"source_pdf_page: (\d+)", text)}
    missing_markers = sorted(expected - markers)
    replacement_chars = text.count("�")
    review_expected = {
        int(item["pdf_page"])
        for item in manifest["pages"].values()
        if item.get("needs_ai_review") and int(item["pdf_page"]) in expected
    }
    review_missing = []
    review_replacement_chars = 0
    if args.review_document:
        review_text = args.review_document.read_text(encoding="utf-8")
        review_markers = {
            int(value)
            for value in re.findall(r"source_pdf_page: (\d+)", review_text)
        }
        review_missing = sorted(review_expected - review_markers)
        review_replacement_chars = review_text.count("�")
    failures = {
        page_no: item.get("error")
        for page_no, item in manifest["pages"].items()
        if item.get("error")
    }
    report = {
        "expected_pages": len(expected),
        "complete_pages": len(actual & expected),
        "review_pages": len(review_expected),
        "missing_pages": missing,
        "missing_page_markers": missing_markers,
        "missing_review_page_markers": review_missing,
        "replacement_characters": replacement_chars,
        "review_replacement_characters": review_replacement_chars,
        "failures": failures,
        "pass": (
            not missing
            and not missing_markers
            and not review_missing
            and not replacement_chars
            and not review_replacement_chars
            and not failures
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
