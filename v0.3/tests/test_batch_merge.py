import json
from pathlib import Path
import tempfile
import unittest

import fitz

from m1_merge_candidate_batches import merge_batches
from m1_extract_source import candidate_view
from m1_build_source_dossier import build_dossier
from m1_prepare_batches import split_next_batch


def batch_pack(page: int, quote: str) -> dict:
    page_id = f"SRC-001-P{page:04d}"
    return {
        "pages": [{
            "page_id": page_id,
            "source_id": "SRC-001",
            "pdf_page": page,
            "status": "candidate",
            "candidate_ids": ["CAND-00001"],
        }],
        "candidates": [{
            "candidate_id": "CAND-00001",
            "claim_id": "CLM-00001",
            "neighbor_candidate_ids": [],
            "matched_terms": [],
            "preservation_terms": [],
            "business_axes": ["signal_transmission"],
            "obligation_terms": ["應"],
        }],
        "claims": [{
            "claim_id": "CLM-00001",
            "context_heading": "弱電需求",
            "context_heading_basis": "preceding_heading",
            "system_hints": ["資訊網路"],
            "space_hints": [],
            "source_shape": "sentence",
            "text_quality_flags": [],
            "evidence_ids": ["EV-00001"],
        }],
        "evidence": [{
            "evidence_id": "EV-00001",
            "claim_id": "CLM-00001",
            "source_id": "SRC-001",
            "pdf_page": page,
            "section": "弱電需求",
            "quote": quote,
            "origin_kind": "source",
        }],
        "visual_regions": [],
        "visual_audit": {"status": "not_required", "pending_region_ids": [], "resolved_region_count": 0},
        "document_terms": [],
        "issues": [],
        "extraction_summary": {"repeated_margin_line_count": 0},
    }


class BatchMergeTests(unittest.TestCase):
    def test_timeout_batch_can_be_split_without_losing_page_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batch_pdf = root / "batch_03_p0011-0015.pdf"
            with fitz.open() as document:
                for _ in range(5):
                    document.new_page()
                document.save(batch_pdf)
            manifest = root / "batch_manifest.json"
            manifest.write_text(json.dumps({
                "source_name": "sample.pdf",
                "source_sha256": "c" * 64,
                "page_count": 5,
                "batch_pages": 5,
                "batches": [{
                    "batch_id": "B03",
                    "pdf": str(batch_pdf),
                    "page_start": 11,
                    "page_end": 15,
                    "page_offset": 10,
                    "candidate_json": str(root / "batch_03_candidates.json"),
                    "source_json": str(root / "batch_03_source.json"),
                    "vision_dir": str(root / "batch_03_vision"),
                    "dossier_md": str(root / "batch_03_dossier.md"),
                }],
            }), encoding="utf-8")

            self.assertEqual(0, split_next_batch(manifest))
            data = json.loads(manifest.read_text(encoding="utf-8"))
            children = data["batches"]
            self.assertEqual(["B03A", "B03B"], [item["batch_id"] for item in children])
            self.assertEqual([(11, 13), (14, 15)], [
                (item["page_start"], item["page_end"]) for item in children
            ])
            self.assertEqual([3, 2], [len(fitz.open(item["pdf"])) for item in children])
            self.assertEqual(1, data["adaptive_split_count"])

    def test_merge_renumbers_ids_and_builds_one_dossier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batches = []
            for page, quote in ((1, "機房應設置資訊機櫃。"), (2, "地下室應預留行動通訊設備空間。")):
                source = root / f"batch_{page:02d}_source.json"
                source.write_text(json.dumps(batch_pack(page, quote), ensure_ascii=False), encoding="utf-8")
                batches.append({
                    "batch_id": f"B{page:02d}",
                    "page_start": page,
                    "page_end": page,
                    "source_json": str(source),
                })
            manifest = root / "batch_manifest.json"
            manifest.write_text(json.dumps({
                "source_name": "sample.pdf",
                "source_sha256": "a" * 64,
                "page_count": 2,
                "batches": batches,
            }), encoding="utf-8")

            merged = merge_batches(manifest)
            self.assertEqual(["CAND-00001", "CAND-00002"], [item["candidate_id"] for item in merged["candidates"]])
            self.assertEqual([1, 2], [item["pdf_page"] for item in merged["pages"]])
            view = candidate_view(merged)
            dossier = build_dossier(view)
            self.assertIn("sample.pdf", dossier)
            self.assertIn("地下室應預留行動通訊設備空間", dossier)

    def test_merge_rejects_missing_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "batch_source.json"
            source.write_text(json.dumps(batch_pack(1, "應設置資訊設備。"), ensure_ascii=False), encoding="utf-8")
            manifest = root / "batch_manifest.json"
            manifest.write_text(json.dumps({
                "source_name": "sample.pdf",
                "source_sha256": "b" * 64,
                "page_count": 2,
                "batches": [{"batch_id": "B01", "page_start": 1, "page_end": 2, "source_json": str(source)}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "page coverage mismatch"):
                merge_batches(manifest)


if __name__ == "__main__":
    unittest.main()
