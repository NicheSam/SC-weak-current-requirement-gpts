from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def page_header(page: dict[str, Any]) -> str:
    printed = page.get("printed_page_candidate")
    printed_text = str(printed) if printed is not None else "unknown"
    return (
        f"<!-- source_pdf_page: {page['pdf_page']} -->\n"
        f"<!-- printed_page_candidate: {printed_text} -->\n"
        f"# Source PDF page {page['pdf_page']} (printed page candidate: {printed_text})\n"
    )


NOISE_LINE_PATTERNS = (
    re.compile(r"^<!-- image omitted; see Docling JSON provenance -->$"),
    re.compile(r"^Taichung City Government Housing(?: Development Department)?$", re.I),
    re.compile(r"^.*委託專案管理\s*\(\s*含監造\s*\)\s*技術服務案\s*$"),
    re.compile(r"^.*(?:至鋒工程顧問有限公司|吳嘉栩建築師事務所).*$"),
)


def clean_page_markdown(text: str) -> str:
    """Remove extraction scaffolding without rewriting source meaning."""
    cleaned: list[str] = []
    previous_nonempty = ""
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        if any(pattern.match(stripped) for pattern in NOISE_LINE_PATTERNS):
            continue
        if stripped and stripped == previous_nonempty:
            continue
        cleaned.append(line)
        if stripped:
            previous_nonempty = stripped
    result = "\n".join(cleaned)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return result


def text_quality_score(text: str) -> float:
    cleaned = clean_page_markdown(text)
    compact = re.sub(r"\s+", "", cleaned)
    if not compact:
        return float("-inf")
    readable = len(re.findall(r"[0-9A-Za-z\u3400-\u9fff]", compact))
    readable_ratio = readable / len(compact)
    structure = len(re.findall(r"(?m)^(?:#{1,6}\s|[-*]\s|\|)", cleaned))
    sentences = len(re.findall(r"[。；：!?！？]", cleaned))
    garbage_runs = len(re.findall(r"[、，。,.()（）\[\]{}]{4,}", cleaned))
    replacement = cleaned.count("�")
    length_bonus = min(12.0, math.log10(max(readable, 1)) * 4.0)
    return round(
        readable_ratio * 70.0
        + length_bonus
        + min(structure, 20) * 0.25
        + min(sentences, 30) * 0.15
        - garbage_runs * 8.0
        - replacement * 20.0,
        3,
    )


def choose_canonical_page(
    primary: str, alternate: str | None, review_reasons: list[str]
) -> tuple[str, str, dict[str, float | None]]:
    primary_clean = clean_page_markdown(primary)
    alternate_clean = clean_page_markdown(alternate or "")
    primary_score = text_quality_score(primary_clean)
    alternate_score = (
        text_quality_score(alternate_clean) if alternate_clean else None
    )
    metrics: dict[str, float | None] = {
        "pdf_aware_score": primary_score,
        "full_page_score": alternate_score,
    }
    if not alternate_clean:
        return primary_clean, "pdf_aware", metrics
    if not primary_clean:
        return alternate_clean, "full_page", metrics

    primary_size = len(re.sub(r"\s+", "", primary_clean))
    alternate_size = len(re.sub(r"\s+", "", alternate_clean))
    size_ratio = alternate_size / max(primary_size, 1)
    fragment_flagged = "probable_fragment" in review_reasons
    score_gain = alternate_score - primary_score if alternate_score is not None else 0
    prefer_alternate = (
        (score_gain >= 2.0 and size_ratio >= 0.72)
        or (fragment_flagged and score_gain >= 0 and size_ratio >= 0.65)
        or (fragment_flagged and score_gain >= 1.0)
    )
    if prefer_alternate:
        return alternate_clean, "full_page", metrics
    return primary_clean, "pdf_aware", metrics


def build_document(
    run_dir: Path,
    output_path: Path,
    review_output_path: Path,
    clean_output_path: Path | None = None,
) -> dict[str, int]:
    manifest = load_manifest(run_dir / "manifest.json")
    pages = sorted(manifest["pages"].values(), key=lambda item: item["pdf_page"])
    parts = [
        "# AI-readable source document\n",
        f"- Source file: `{manifest['source_file']}`\n",
        f"- Source SHA-256: `{manifest['source_sha256']}`\n",
        "- Primary extraction: Docling PDF-aware layout regions\n",
        "- Review extraction: Docling full-page OCR only on flagged pages\n",
        f"- OCR review file: `{review_output_path.name}`\n",
        "- Rule: read the review file only for pages marked `needs_ocr_review`; do not merge alternatives blindly.\n",
    ]
    review_parts = [
        "# OCR review alternatives\n",
        f"- Source file: `{manifest['source_file']}`\n",
        "- These are full-page OCR alternatives for flagged pages only.\n",
        "- Compare each alternative with the same page in the primary source document.\n",
        "- Do not concatenate both versions or create duplicate requirements.\n",
    ]
    clean_output_path = clean_output_path or output_path.with_name(
        "source_document_clean.md"
    )
    clean_parts = [
        "# Canonical AI-readable source document\n",
        f"- Source file: `{manifest['source_file']}`\n",
        f"- Source SHA-256: `{manifest['source_sha256']}`\n",
        "- Canonical extraction: one selected reading per PDF page.\n",
        "- Repeated page furniture and extraction placeholders were removed; source wording, tables, page numbers and context were retained.\n",
        "- `manifest.json` and `ocr_review_alternatives.md` are trace files and are not required for normal GPTS analysis.\n",
    ]
    review_count = 0
    complete_count = 0
    canonical_count = 0
    for page in pages:
        page_no = page["pdf_page"]
        primary_path = run_dir / "pages" / "pdf_aware" / f"page_{page_no:04d}.md"
        if not primary_path.exists():
            continue
        complete_count += 1
        parts.extend(["\n---\n", page_header(page)])
        if page.get("needs_ai_review"):
            reasons = ", ".join(page.get("review_reasons") or [])
            parts.append(
                f"\n> `needs_ocr_review`: compare this page with `{review_output_path.name}`. Reasons: `{reasons}`.\n"
            )
        primary_text = primary_path.read_text(encoding="utf-8").strip()
        parts.append("\n## Primary extraction\n\n")
        parts.append(primary_text + "\n")
        alternate_text = ""
        if page.get("needs_ai_review"):
            review_count += 1
            reasons = ", ".join(page.get("review_reasons") or [])
            alternate_path = (
                run_dir / "pages" / "full_page" / f"page_{page_no:04d}.md"
            )
            review_parts.extend(
                [
                    "\n---\n",
                    page_header(page),
                    "\n## Full-page OCR alternative\n\n",
                    f"> Review reasons: `{reasons}`. Compare with the primary extraction; do not concatenate blindly.\n\n",
                ]
            )
            if alternate_path.exists():
                alternate_text = alternate_path.read_text(encoding="utf-8").strip()
                review_parts.append(alternate_text + "\n")
            else:
                review_parts.append("> Full-page OCR alternative is unavailable.\n")
        canonical_text, canonical_source, metrics = choose_canonical_page(
            primary_text,
            alternate_text,
            list(page.get("review_reasons") or []),
        )
        canonical_count += 1
        clean_parts.extend(
            [
                "\n---\n",
                page_header(page),
                f"\n<!-- canonical_source: {canonical_source} -->\n\n",
                canonical_text + "\n",
            ]
        )
        manifest_page = manifest["pages"][str(page_no)]
        manifest_page["canonical_source"] = canonical_source
        manifest_page["canonical_quality"] = metrics
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(parts), encoding="utf-8", newline="\n")
    review_output_path.parent.mkdir(parents=True, exist_ok=True)
    review_output_path.write_text(
        "".join(review_parts), encoding="utf-8", newline="\n"
    )
    clean_output_path.parent.mkdir(parents=True, exist_ok=True)
    clean_output_path.write_text(
        "".join(clean_parts), encoding="utf-8", newline="\n"
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "complete_pages": complete_count,
        "review_pages": review_count,
        "canonical_pages": canonical_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build page-aware Markdown from Docling checkpoints.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-output", type=Path)
    parser.add_argument("--clean-output", type=Path)
    args = parser.parse_args()
    output_path = args.output.resolve()
    review_output_path = (
        args.review_output.resolve()
        if args.review_output
        else output_path.with_name("ocr_review_alternatives.md")
    )
    summary = build_document(
        args.run_dir.resolve(),
        output_path,
        review_output_path,
        args.clean_output.resolve()
        if args.clean_output
        else output_path.with_name("source_document_clean.md"),
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
