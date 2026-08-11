#!/usr/bin/env python3
"""Split a large PDF into bounded page batches for GPTS tool execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import fitz

from m1_extract_source import candidate_view, source_pack


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_path(manifest_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.exists():
        return path
    return manifest_path.parent / path.name


def valid_completed_batch(path: Path, start: int, end: int) -> bool:
    if not path.is_file():
        return False
    try:
        data = load_json(path)
        pages = [int(item.get("pdf_page", 0)) for item in data.get("pages", []) if isinstance(item, dict)]
        return pages == list(range(start, end + 1))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def batch_record(output_dir: Path, batch_id: str, pdf_path: Path, start: int, end: int) -> dict[str, object]:
    stem = batch_id.lower()
    return {
        "batch_id": batch_id,
        "pdf": str(pdf_path),
        "page_start": start,
        "page_end": end,
        "page_offset": start - 1,
        "candidate_json": str(output_dir / f"{stem}_candidates.json"),
        "source_json": str(output_dir / f"{stem}_source.json"),
        "vision_dir": str(output_dir / f"{stem}_vision"),
        "dossier_md": str(output_dir / f"{stem}_dossier.md"),
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def split_next_batch(manifest_path: Path) -> int:
    if not manifest_path.is_file():
        print(f"FAIL: batch manifest not found: {manifest_path}")
        return 2
    manifest = load_json(manifest_path)
    batches = manifest.get("batches", [])
    for index, batch in enumerate(batches):
        start = int(batch["page_start"])
        end = int(batch["page_end"])
        source_path = resolve_path(manifest_path, str(batch["source_json"]))
        if valid_completed_batch(source_path, start, end):
            continue
        batch_id = str(batch.get("batch_id", f"B{index + 1:02d}"))
        if start >= end:
            print(
                f"FAIL: {batch_id} page={start} is already a single-page batch; "
                "record this page as the exact platform-timeout blocker"
            )
            return 1
        pdf_path = resolve_path(manifest_path, str(batch["pdf"]))
        if not pdf_path.is_file():
            print(f"FAIL: batch PDF not found: {pdf_path}")
            return 2
        midpoint = (start + end) // 2
        ranges = ((start, midpoint, "A"), (midpoint + 1, end, "B"))
        children: list[dict[str, object]] = []
        with fitz.open(pdf_path) as source:
            expected_pages = end - start + 1
            if len(source) != expected_pages:
                print(
                    f"FAIL: {batch_id} PDF page count mismatch: "
                    f"expected={expected_pages} actual={len(source)}"
                )
                return 2
            for child_start, child_end, suffix in ranges:
                child_id = f"{batch_id}{suffix}"
                child_pdf = manifest_path.parent / (
                    f"{child_id.lower()}_p{child_start:04d}-{child_end:04d}.pdf"
                )
                relative_start = child_start - start
                relative_end = child_end - start
                with fitz.open() as child:
                    child.insert_pdf(source, from_page=relative_start, to_page=relative_end)
                    child.save(child_pdf)
                children.append(
                    batch_record(manifest_path.parent, child_id, child_pdf, child_start, child_end)
                )
        batches[index:index + 1] = children
        manifest["batches"] = batches
        manifest["adaptive_split_count"] = int(manifest.get("adaptive_split_count", 0)) + 1
        write_manifest(manifest_path, manifest)
        print(
            f"PASS: split {batch_id} pages={start}-{end} into "
            f"{children[0]['batch_id']} pages={start}-{midpoint} and "
            f"{children[1]['batch_id']} pages={midpoint + 1}-{end}; rerun --run-next"
        )
        return 0
    print("PASS: no incomplete batch requires splitting")
    return 0


def run_next_batch(manifest_path: Path, defer_ocr_to_model_vision: bool = False) -> int:
    if not manifest_path.is_file():
        print(f"FAIL: batch manifest not found: {manifest_path}")
        return 2
    manifest = load_json(manifest_path)
    batches = manifest.get("batches", [])
    for index, batch in enumerate(batches, start=1):
        start = int(batch["page_start"])
        end = int(batch["page_end"])
        source_path = resolve_path(manifest_path, str(batch["source_json"]))
        if valid_completed_batch(source_path, start, end):
            continue
        pdf_path = resolve_path(manifest_path, str(batch["pdf"]))
        candidate_path = resolve_path(manifest_path, str(batch["candidate_json"]))
        vision_dir = resolve_path(manifest_path, str(batch["vision_dir"]))
        if not pdf_path.is_file():
            print(f"FAIL: batch PDF not found: {pdf_path}")
            return 2
        try:
            data = source_pack(
                pdf_path,
                visual_output_dir=vision_dir,
                page_offset=int(batch["page_offset"]),
                defer_ocr_to_model_vision=defer_ocr_to_model_vision,
            )
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            candidate_path.write_text(
                json.dumps(candidate_view(data), ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"FAIL: {batch.get('batch_id', index)} extraction failed: {exc}")
            return 1
        pending = data.get("visual_audit", {}).get("pending_region_ids", [])
        print(
            f"CONTINUE_INTERNAL: completed {batch.get('batch_id', index)} "
            f"pages={start}-{end} candidates={len(data.get('candidates', []))} "
            f"visual_pending={len(pending)} remaining_batches={len(batches) - index} "
            f"ocr_mode={'model_vision_deferred' if defer_ocr_to_model_vision else 'tesseract_primary'}"
        )
        return 0

    pending_batches: list[str] = []
    pending_regions = 0
    for batch in batches:
        data = load_json(resolve_path(manifest_path, str(batch["source_json"])))
        pending = data.get("visual_audit", {}).get("pending_region_ids", [])
        if pending:
            pending_batches.append(str(batch.get("batch_id")))
            pending_regions += len(pending)
    if pending_batches:
        print(
            "BATCHES_COMPLETE_WITH_VISUAL_REVIEW: "
            f"pending_regions={pending_regions} batches={','.join(pending_batches)}"
        )
    else:
        print(f"PASS: all {len(batches)} extraction batches are complete; run canonical merge")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or advance resumable GPTS extraction batches.")
    parser.add_argument("pdf", type=Path, nargs="?")
    parser.add_argument("output_dir", type=Path, nargs="?", default=Path("m1_batches"))
    parser.add_argument("--batch-pages", type=int, default=25)
    parser.add_argument("--run-next", type=Path, metavar="MANIFEST")
    parser.add_argument("--split-next", type=Path, metavar="MANIFEST")
    parser.add_argument("--defer-next-ocr", type=Path, metavar="MANIFEST")
    args = parser.parse_args()
    modes = [args.run_next, args.split_next, args.defer_next_ocr]
    if sum(value is not None for value in modes) > 1:
        print("FAIL: use only one of --run-next, --split-next, or --defer-next-ocr")
        return 2
    if args.run_next is not None:
        return run_next_batch(args.run_next)
    if args.split_next is not None:
        return split_next_batch(args.split_next)
    if args.defer_next_ocr is not None:
        return run_next_batch(args.defer_next_ocr, defer_ocr_to_model_vision=True)
    if args.pdf is None:
        print("FAIL: PDF is required unless a batch-control option is used")
        return 2
    if not args.pdf.is_file():
        print(f"FAIL: PDF not found: {args.pdf}")
        return 2
    if not 5 <= args.batch_pages <= 30:
        print("FAIL: --batch-pages must be between 5 and 30")
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    batches: list[dict[str, object]] = []
    with fitz.open(args.pdf) as source:
        page_count = len(source)
        for index, start in enumerate(range(0, page_count, args.batch_pages), start=1):
            end = min(page_count, start + args.batch_pages)
            batch_path = args.output_dir / f"batch_{index:02d}_p{start + 1:04d}-{end:04d}.pdf"
            with fitz.open() as batch:
                batch.insert_pdf(source, from_page=start, to_page=end - 1)
                batch.save(batch_path)
            batches.append(batch_record(args.output_dir, f"B{index:02d}", batch_path, start + 1, end))

    manifest = {
        "source_name": args.pdf.name,
        "source_sha256": sha256_path(args.pdf),
        "page_count": page_count,
        "batch_pages": args.batch_pages,
        "batches": batches,
    }
    manifest_path = args.output_dir / "batch_manifest.json"
    write_manifest(manifest_path, manifest)
    print(f"PASS: wrote {manifest_path} | pages={page_count} batches={len(batches)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
