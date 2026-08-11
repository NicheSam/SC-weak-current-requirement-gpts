#!/usr/bin/env python3
"""Merge deterministic page-batch checkpoints into one canonical M1 source pack."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from m1_build_source_dossier import build_dossier, prepare_screening_batches
from m1_extract_source import candidate_view


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_batch_path(manifest_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_file():
        return path
    candidate = manifest_path.parent / path.name
    if candidate.is_file():
        return candidate
    return path


def canonical_id(prefix: str, serial: int) -> str:
    return f"{prefix}-{serial:05d}"


def merge_batches(manifest_path: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    batches = manifest.get("batches", [])
    if not isinstance(batches, list) or not batches:
        raise ValueError("batch manifest has no batches")

    merged_pages: list[dict[str, Any]] = []
    merged_regions: list[dict[str, Any]] = []
    merged_candidates: list[dict[str, Any]] = []
    merged_claims: list[dict[str, Any]] = []
    merged_evidence: list[dict[str, Any]] = []
    merged_issues: list[dict[str, Any]] = []
    term_pages: dict[str, set[str]] = {}
    expected_pages: list[int] = []
    pending_region_ids: list[str] = []
    resolved_regions = 0
    repeated_margin_lines = 0

    for batch_index, batch in enumerate(batches, start=1):
        source_path = resolve_batch_path(manifest_path, str(batch.get("source_json", "")))
        if not source_path.is_file():
            raise FileNotFoundError(f"missing batch source checkpoint: {source_path}")
        data = load_json(source_path)
        start = int(batch["page_start"])
        end = int(batch["page_end"])
        expected_pages.extend(range(start, end + 1))
        batch_pages = [item for item in data.get("pages", []) if isinstance(item, dict)]
        actual_pages = [int(item.get("pdf_page", 0)) for item in batch_pages]
        if actual_pages != list(range(start, end + 1)):
            raise ValueError(
                f"{batch.get('batch_id', batch_index)} page coverage mismatch: "
                f"expected {start}-{end}, got {actual_pages[:1]}-{actual_pages[-1:] or []}"
            )

        batch_candidates = [item for item in data.get("candidates", []) if isinstance(item, dict)]
        batch_claims = {
            str(item.get("claim_id")): item
            for item in data.get("claims", [])
            if isinstance(item, dict) and item.get("claim_id")
        }
        batch_evidence = {
            str(item.get("claim_id")): item
            for item in data.get("evidence", [])
            if isinstance(item, dict) and item.get("claim_id")
        }
        id_map: dict[str, str] = {}
        claim_map: dict[str, str] = {}
        evidence_map: dict[str, str] = {}
        for candidate in batch_candidates:
            serial = len(merged_candidates) + len(id_map) + 1
            old_candidate_id = str(candidate.get("candidate_id", ""))
            old_claim_id = str(candidate.get("claim_id", ""))
            if not old_candidate_id or old_claim_id not in batch_claims or old_claim_id not in batch_evidence:
                raise ValueError(f"incomplete candidate chain in {source_path}: {old_candidate_id or '?'}")
            id_map[old_candidate_id] = canonical_id("CAND", serial)
            claim_map[old_claim_id] = canonical_id("CLM", serial)
            old_evidence_id = str(batch_evidence[old_claim_id].get("evidence_id", ""))
            evidence_map[old_evidence_id] = canonical_id("EV", serial)

        for page in batch_pages:
            record = dict(page)
            record["source_id"] = "SRC-001"
            record["candidate_ids"] = [id_map[str(value)] for value in page.get("candidate_ids", [])]
            merged_pages.append(record)

        for candidate in batch_candidates:
            old_candidate_id = str(candidate["candidate_id"])
            old_claim_id = str(candidate["claim_id"])
            record = dict(candidate)
            record["candidate_id"] = id_map[old_candidate_id]
            record["claim_id"] = claim_map[old_claim_id]
            record["neighbor_candidate_ids"] = [
                id_map[str(value)]
                for value in candidate.get("neighbor_candidate_ids", [])
                if str(value) in id_map
            ]
            merged_candidates.append(record)

            claim = dict(batch_claims[old_claim_id])
            claim["claim_id"] = claim_map[old_claim_id]
            claim["evidence_ids"] = [
                evidence_map[str(value)]
                for value in claim.get("evidence_ids", [])
                if str(value) in evidence_map
            ]
            merged_claims.append(claim)

            evidence = dict(batch_evidence[old_claim_id])
            evidence["evidence_id"] = evidence_map[str(evidence["evidence_id"])]
            evidence["claim_id"] = claim_map[old_claim_id]
            evidence["source_id"] = "SRC-001"
            merged_evidence.append(evidence)

        for region in data.get("visual_regions", []):
            if isinstance(region, dict):
                merged_regions.append(dict(region))
        audit = data.get("visual_audit", {})
        if isinstance(audit, dict):
            pending_region_ids.extend(str(value) for value in audit.get("pending_region_ids", []))
            resolved_regions += int(audit.get("resolved_region_count", 0) or 0)
        summary = data.get("extraction_summary", {})
        if isinstance(summary, dict):
            repeated_margin_lines += int(summary.get("repeated_margin_line_count", 0) or 0)
        for term in data.get("document_terms", []):
            if isinstance(term, dict) and term.get("term"):
                term_pages.setdefault(str(term["term"]), set()).update(
                    str(value) for value in term.get("source_page_ids", [])
                )
        for issue in data.get("issues", []):
            if isinstance(issue, dict):
                record = dict(issue)
                record["issue_id"] = f"ISSUE-B{batch_index:02d}-{len(merged_issues) + 1:05d}"
                merged_issues.append(record)

    actual_coverage = [int(item["pdf_page"]) for item in merged_pages]
    page_count = int(manifest["page_count"])
    if actual_coverage != expected_pages or expected_pages != list(range(1, page_count + 1)):
        raise ValueError("merged page coverage is not exactly 1..page_count")
    if len({item["candidate_id"] for item in merged_candidates}) != len(merged_candidates):
        raise ValueError("candidate IDs are not unique after merge")

    now = datetime.now(timezone.utc).isoformat()
    all_candidate_ids = [str(item["candidate_id"]) for item in merged_candidates]
    pending_page_ids = [
        str(page["page_id"])
        for page in merged_pages
        if str(page.get("status")) == "pending"
    ]
    visual_status = "pending" if pending_region_ids else ("complete" if merged_regions else "not_required")
    document_terms = [
        {
            "term_id": f"TERM-{index:04d}",
            "term": term,
            "source_page_ids": sorted(page_ids),
            "relation_hint": "document_dynamic_term",
        }
        for index, (term, page_ids) in enumerate(sorted(term_pages.items()), start=1)
    ]
    return {
        "schema_version": "1.0",
        "workflow_version": "0.7",
        "checkpoint": {
            "checkpoint_id": f"CP-{hashlib.sha256((str(manifest['source_sha256']) + now).encode('utf-8')).hexdigest()[:12].upper()}",
            "sequence": 1,
            "state": "stage1_visual_pending" if pending_region_ids else "stage1_auditing",
            "last_passed_gate": "index",
            "next_action": "transcribe_visual_regions" if pending_region_ids else "run_semantic_translation",
            "pending_page_ids": pending_page_ids,
            "pending_candidate_ids": all_candidate_ids,
            "continue_count": 0,
            "user_step": "extract",
            "created_at": now,
            "updated_at": now,
        },
        "source_manifest": [{
            "source_id": "SRC-001",
            "name": manifest["source_name"],
            "role": "requirements",
            "sha256": manifest["source_sha256"],
            "page_count": page_count,
            "extraction_engine": "pymupdf+tesseract_batched",
        }],
        "pages": merged_pages,
        "visual_regions": merged_regions,
        "visual_audit": {
            "status": visual_status,
            "engine": "tesseract_primary" if merged_regions else "none",
            "region_count": len(merged_regions),
            "resolved_region_count": resolved_regions,
            "pending_region_ids": list(dict.fromkeys(pending_region_ids)),
            "manifest_path": str(manifest_path),
        },
        "document_terms": document_terms,
        "candidates": merged_candidates,
        "claims": merged_claims,
        "evidence": merged_evidence,
        "issues": merged_issues,
        "recall_audit": {
            "audit_round": 0,
            "excluded_pages_rechecked": 0,
            "context_pages_rechecked": 0,
            "empty_sections_rechecked": 0,
            "dynamic_terms_searched": len(document_terms),
            "new_candidate_ids": [],
            "processed_candidate_ids": [],
            "unprocessed_candidate_ids": all_candidate_ids,
            "settled": False,
            "stop_reason": "canonical_batch_merge_ready_for_single_semantic_pass",
        },
        "extraction_summary": {
            "engine": "pymupdf+tesseract_batched",
            "page_count": page_count,
            "candidate_page_count": sum(1 for item in merged_pages if item.get("status") == "candidate"),
            "candidate_count": len(merged_candidates),
            "unreadable_page_count": sum(1 for item in merged_pages if item.get("status") == "unreadable"),
            "repeated_margin_line_count": repeated_margin_lines,
            "visual_region_count": len(merged_regions),
            "visual_pending_page_count": len(pending_page_ids),
            "batch_count": len(batches),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge M1 batch checkpoints into one canonical source pack.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path, nargs="?", default=Path("source_index.json"))
    parser.add_argument("candidate_view", type=Path, nargs="?", default=Path("m1_candidates.json"))
    parser.add_argument("reading_pack", type=Path, nargs="?", default=Path("source_reading_pack.md"))
    parser.add_argument("--screening-dir", type=Path)
    args = parser.parse_args()
    try:
        data = merge_batches(args.manifest)
        view = candidate_view(data)
        reading_pack = build_dossier(view)
        args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        args.candidate_view.write_text(json.dumps(view, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        args.reading_pack.write_text(reading_pack, encoding="utf-8", newline="\n")
        screening_batches = 0
        if args.screening_dir:
            screening_manifest = prepare_screening_batches(view, args.screening_dir)
            screening_batches = screening_manifest["batch_count"]
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1
    print(
        "PASS: canonical source pack created | "
        f"pages={data['extraction_summary']['page_count']} "
        f"candidates={data['extraction_summary']['candidate_count']} "
        f"visual_pending={data['extraction_summary']['visual_pending_page_count']} "
        f"reading_pack={args.reading_pack} screening_batches={screening_batches}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
