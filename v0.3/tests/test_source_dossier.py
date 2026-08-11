from __future__ import annotations

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import m1_build_source_dossier
import m1_extract_source


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "sandbox" / "md_pipeline_v06" / "input" / "m1_candidates.json"
PDF = ROOT / "tmp" / "pdfs" / "central_market.pdf"


class SourceDossierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not PACK.is_file():
            cls.data = None
            cls.dossier = ""
            return
        cls.data = json.loads(PACK.read_text(encoding="utf-8"))
        cls.dossier = m1_build_source_dossier.build_dossier(cls.data)

    def test_automatic_ocr_cannot_be_disabled(self) -> None:
        with self.assertRaisesRegex(ValueError, "automatic OCR is mandatory"):
            m1_extract_source.source_pack(Path("unused.pdf"), auto_ocr=False)

    def test_tesseract_timeout_is_deferred_to_model_vision(self) -> None:
        region = {"region_id": "VR-P0009-001", "crop_file": "page9.png", "image_count": 1}
        capability = {"available": True, "executable": "/usr/bin/tesseract"}
        error = m1_extract_source.subprocess.TimeoutExpired(
            cmd="tesseract",
            timeout=m1_extract_source.TESSERACT_REGION_TIMEOUT_SECONDS,
        )
        with TemporaryDirectory() as directory, patch(
            "m1_extract_source.subprocess.run",
            side_effect=error,
        ):
            payload = m1_extract_source.run_tesseract_regions(Path(directory), [region], capability)
        self.assertEqual("pending", payload["regions"][0]["status"])
        self.assertEqual("tesseract_region_timeout", payload["regions"][0]["review_note"])
        self.assertLessEqual(m1_extract_source.TESSERACT_REGION_TIMEOUT_SECONDS, 30)

    @unittest.skipUnless(PACK.is_file(), "private candidate-pack fixture is not installed")
    def test_every_evidence_group_is_preserved(self) -> None:
        for group in self.data["evidence_groups"]:
            self.assertIn(f"evidence_group:{group['evidence_group_id']}", self.dossier)

    @unittest.skipUnless(PACK.is_file(), "private candidate-pack fixture is not installed")
    def test_known_mixed_page_evidence_is_present(self) -> None:
        for term in ("5G", "E-TAG", "車牌辨識", "洩波同軸", "讀卡"):
            self.assertIn(term, self.dossier)
        self.assertIn("PDF 28", self.dossier)

    @unittest.skipUnless(PACK.is_file(), "private candidate-pack fixture is not installed")
    def test_dossier_does_not_expose_processing_routes(self) -> None:
        for token in ("processing_lane", "semantic_freeze", "scope_disposition", "claim_kind"):
            self.assertNotIn(token, self.dossier)

    @unittest.skipUnless(PACK.is_file(), "private candidate-pack fixture is not installed")
    def test_pending_visual_region_is_recorded_without_blocking_dossier(self) -> None:
        broken = copy.deepcopy(self.data)
        broken["visual_audit"]["pending_region_ids"] = ["VR-P0028-001"]
        dossier = m1_build_source_dossier.build_dossier(broken)
        self.assertIn("尚待人工判讀的低信心影像區：1", dossier)

    @unittest.skipUnless(PACK.is_file(), "private candidate-pack fixture is not installed")
    def test_screening_batches_cover_every_group_with_bounded_sources(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            manifest = m1_build_source_dossier.prepare_screening_batches(
                self.data,
                output,
                max_groups=8,
                max_chars=18000,
            )
            expected = [group["evidence_group_id"] for group in self.data["evidence_groups"]]
            actual = [
                group_id
                for batch in manifest["batches"]
                for group_id in batch["evidence_group_ids"]
            ]
            self.assertEqual(expected, actual)
            self.assertTrue(all(len(batch["evidence_group_ids"]) <= 8 for batch in manifest["batches"]))
            self.assertTrue(all((output / batch["source_file"]).is_file() for batch in manifest["batches"]))

    @unittest.skipUnless(PACK.is_file(), "private candidate-pack fixture is not installed")
    def test_weak_current_source_rejects_missing_batch_result(self) -> None:
        sample = copy.deepcopy(self.data)
        sample["evidence_groups"] = sample["evidence_groups"][:2]
        with TemporaryDirectory() as directory:
            output = Path(directory)
            m1_build_source_dossier.prepare_screening_batches(sample, output)
            with self.assertRaisesRegex(ValueError, "missing screening result"):
                m1_build_source_dossier.build_weak_current_source(output / "screen_manifest.json")

    @unittest.skipUnless(PACK.is_file(), "private candidate-pack fixture is not installed")
    def test_screening_results_build_weak_current_source(self) -> None:
        sample = copy.deepcopy(self.data)
        sample["evidence_groups"] = sample["evidence_groups"][:2]
        with TemporaryDirectory() as directory:
            output = Path(directory)
            manifest = m1_build_source_dossier.prepare_screening_batches(sample, output)
            for batch in manifest["batches"]:
                (output / batch["result_file"]).write_text(
                    f"<!-- screened:{batch['batch_id']} -->\n\n"
                    "## 弱電相關來源\n\n- PDF 28：地下室應建置 5G 強波器。\n",
                    encoding="utf-8",
                )
            source_path = output / "weak_current_source.md"
            source = m1_build_source_dossier.build_weak_current_source(
                output / "screen_manifest.json", source_path
            )
            receipt_path = output / "stage1_receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertTrue(source_path.is_file())
            self.assertTrue(receipt_path.is_file())
            self.assertIn("# 弱電來源包", source)
            self.assertIn("5G 強波器", source)
            self.assertEqual(manifest["batch_count"], source.count("<!-- screened:SB-"))
            self.assertEqual("weak_current_source_complete", receipt["stage"])
            self.assertEqual(manifest["batch_count"], receipt["screening_batch_count"])
            self.assertEqual(
                m1_build_source_dossier.sha256_text(source),
                receipt["weak_current_source_sha256"],
            )

    def test_visual_region_cannot_be_bulk_skipped_without_real_review(self) -> None:
        data = {
            "visual_regions": [
                {
                    "region_id": "VIS-P0001-01",
                    "page_id": "PAGE-0001",
                    "pdf_page": 1,
                    "image_count": 1,
                    "status": "pending",
                }
            ],
            "pages": [
                {
                    "page_id": "PAGE-0001",
                    "pdf_page": 1,
                    "status": "pending",
                    "native_text_present": True,
                    "candidate_ids": [],
                }
            ],
            "candidates": [],
            "claims": [],
            "evidence": [],
            "issues": [],
            "document_terms": [],
            "checkpoint": {},
            "visual_audit": {},
            "recall_audit": {},
            "extraction_summary": {},
        }
        payload = {
            "engine": "model_visual_duplicate_native_text_audit",
            "regions": [
                {
                    "region_id": "VIS-P0001-01",
                    "status": "skipped_non_text",
                    "text": "",
                    "confidence": "high",
                    "engine": "model_visual_duplicate_native_text_audit",
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "cannot be skipped"):
            m1_extract_source.merge_visual_transcriptions(data, payload)

    @unittest.skipUnless(PDF.is_file(), "private central-market PDF fixture is not installed")
    def test_actual_mixed_page_creates_visual_region(self) -> None:
        pages = m1_extract_source.extract_with_fitz(PDF)
        self.assertTrue(all(len(item.visual_regions) <= 1 for item in pages))
        page = pages[27]
        self.assertTrue(page.blocks)
        self.assertTrue(page.visual_regions)
        bbox = page.visual_regions[0]["bbox"]
        self.assertLess(float(bbox[1]), 100)
        self.assertGreater(float(bbox[3]), 300)

    def test_unseen_technical_obligation_is_admitted_for_ai_review(self) -> None:
        text = "地下設備室應設置量子門柱系統並預留控制介面。"
        score, systems, _ = m1_extract_source.candidate_score(text, "設備規格", set())
        axes = m1_extract_source.business_capability_hints(text)
        self.assertTrue(m1_extract_source.candidate_admitted(text, "設備規格", score, systems, axes))


if __name__ == "__main__":
    unittest.main()
