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
        self.assertGreaterEqual(m1_extract_source.TESSERACT_REGION_TIMEOUT_SECONDS, 120)

    def test_low_confidence_psm6_retries_psm11_and_uses_better_text(self) -> None:
        region = {"region_id": "VR-P0028-001", "crop_file": "page28.png", "image_count": 1}
        capability = {"available": True, "executable": "/usr/bin/tesseract"}
        low_tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t0\t0\t20\t10\t42.0\t地下室\n"
        )
        high_tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t0\t0\t20\t10\t91.0\t地下室\n"
            "5\t1\t1\t1\t1\t2\t22\t0\t20\t10\t93.0\t建置5G強波器\n"
        )
        first = type("Completed", (), {"stdout": low_tsv})()
        second = type("Completed", (), {"stdout": high_tsv})()
        with TemporaryDirectory() as directory, patch(
            "m1_extract_source.subprocess.run",
            side_effect=[first, second],
        ) as run:
            payload = m1_extract_source.run_tesseract_regions(Path(directory), [region], capability)
        record = payload["regions"][0]
        self.assertEqual(2, run.call_count)
        self.assertEqual("read", record["status"])
        self.assertEqual("11", record["ocr_psm"])
        self.assertIn("5G強波器", record["text"])

    def test_low_confidence_ocr_stays_pending_with_draft_for_model_review(self) -> None:
        region = {"region_id": "VR-P0028-001", "crop_file": "page28.png", "image_count": 1}
        capability = {"available": True, "executable": "/usr/bin/tesseract"}
        tsv = (
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            "5\t1\t1\t1\t1\t1\t0\t0\t20\t10\t48.0\t地下室\n"
            "5\t1\t1\t1\t1\t2\t22\t0\t20\t10\t52.0\t應設5G強波器\n"
        )
        completed = type("Completed", (), {"stdout": tsv})()
        with TemporaryDirectory() as directory, patch(
            "m1_extract_source.subprocess.run",
            return_value=completed,
        ):
            payload = m1_extract_source.run_tesseract_regions(Path(directory), [region], capability)
        record = payload["regions"][0]
        self.assertEqual("pending", record["status"])
        self.assertIn("5G", record["text"])
        self.assertEqual("low_confidence_ocr", record["review_note"])

    def test_low_confidence_ocr_draft_remains_visible_in_stage1_reading_pack(self) -> None:
        data = {
            "schema_version": "test",
            "workflow_version": "test",
            "source_manifest": [{"name": "sample.pdf", "sha256": "a" * 64, "page_count": 28}],
            "pages": [{
                "page_id": "SRC-001-P0028",
                "source_id": "SRC-001",
                "pdf_page": 28,
                "printed_page": "20",
                "section": "停車空間需求",
                "candidate_ids": [],
                "native_text_present": True,
                "status": "pending",
            }],
            "visual_regions": [{
                "region_id": "VR-P0028-001",
                "page_id": "SRC-001-P0028",
                "pdf_page": 28,
                "image_count": 1,
                "context_heading": "停車空間需求",
                "context_heading_basis": "page_heading",
                "status": "pending",
            }],
            "visual_audit": {"status": "pending", "pending_region_ids": ["VR-P0028-001"]},
            "candidates": [],
            "claims": [],
            "evidence": [],
            "issues": [],
            "document_terms": [],
            "checkpoint": {},
            "recall_audit": {},
            "extraction_summary": {},
        }
        payload = {
            "engine": "tesseract",
            "regions": [{
                "region_id": "VR-P0028-001",
                "status": "pending",
                "text": "全地下室預留電盤及電纜槽架供後續擴充。地下室建置5G強波器。",
                "confidence": "low",
                "mean_confidence": 51.2,
                "review_note": "low_confidence_ocr",
            }],
        }
        merged = m1_extract_source.merge_visual_transcriptions(data, payload)
        merged = m1_extract_source.merge_visual_transcriptions(merged, {
            "engine": "model_vision",
            "regions": [{
                "region_id": "VR-P0028-001",
                "status": "unreadable",
                "text": "",
                "confidence": "low",
                "review_note": "裁切圖文字仍無法可靠確認，保留 OCR 草稿供來源覆核。",
            }],
        })
        view = m1_extract_source.candidate_view(merged)
        dossier = m1_build_source_dossier.build_dossier(view)
        self.assertIn("VR-P0028-001", dossier)
        self.assertIn("PDF 28", dossier)
        self.assertIn("5G強波器", dossier)
        self.assertIn("僅供覆核", dossier)

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
            self.assertEqual(expected, [item["evidence_group_id"] for item in manifest["group_outline"]])
            self.assertTrue(all(item["pdf_pages"] for item in manifest["group_outline"]))
            self.assertTrue(all("section_path" in item for item in manifest["group_outline"]))
            self.assertNotIn("processing_lane", json.dumps(manifest["group_outline"], ensure_ascii=False))

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
                reviewed_pages = ",".join(str(value) for value in batch["pdf_pages"])
                reviewed_groups = ",".join(batch["evidence_group_ids"])
                (output / batch["result_file"]).write_text(
                    f"<!-- screened:{batch['batch_id']} -->\n"
                    f"<!-- reviewed-pages:{reviewed_pages} -->\n"
                    f"<!-- reviewed-groups:{reviewed_groups} -->\n\n"
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

    def test_unknown_source_vocabulary_remains_visible_to_ai(self) -> None:
        text = "會議室應設置智慧媒體牆，支援簡報與活動轉播。"
        score, systems, _ = m1_extract_source.candidate_score(text, "空間需求", set())
        axes = m1_extract_source.business_capability_hints(text)
        self.assertTrue(m1_extract_source.candidate_admitted(text, "空間需求", score, systems, axes))

    def test_unknown_visual_vocabulary_remains_visible_to_ai(self) -> None:
        text = "服務空間應配置旅客服務柱。"
        score, systems, matched = m1_extract_source.candidate_score(text, "空間需求", set())
        axes = m1_extract_source.business_capability_hints(text)
        self.assertTrue(
            m1_extract_source.visual_candidate_admitted(text, "空間需求", score, systems, matched, axes)
        )

    def test_candidate_view_does_not_route_source_by_semantic_lane(self) -> None:
        data = {
            "schema_version": "test",
            "workflow_version": "test",
            "source_manifest": [{"name": "sample.pdf", "sha256": "abc", "page_count": 1}],
            "pages": [{"page_id": "SRC-001-P0001", "pdf_page": 1, "candidate_ids": ["CAND-00001"]}],
            "candidates": [{
                "candidate_id": "CAND-00001",
                "claim_id": "CLM-00001",
                "page_ids": ["SRC-001-P0001"],
                "matched_terms": [],
                "preservation_terms": [],
                "obligation_terms": ["應"],
                "business_axes": [],
                "signal_flags": [],
            }],
            "claims": [{
                "claim_id": "CLM-00001",
                "context_heading": "空間需求",
                "context_heading_basis": "page_heading",
                "system_hints": [],
                "space_hints": ["會議室"],
                "source_shape": "sentence",
                "text_quality_flags": [],
            }],
            "evidence": [{
                "claim_id": "CLM-00001",
                "pdf_page": 1,
                "section": "空間需求",
                "quote": "會議室應設置智慧媒體牆。",
                "origin_kind": "native_text",
                "confidence": "high",
            }],
            "extraction_summary": {},
            "unreadable_pages": [],
        }
        view = m1_extract_source.candidate_view(data)
        self.assertNotIn("processing_lane", json.dumps(view, ensure_ascii=False))

    def test_screening_receipt_proves_page_and_group_review_coverage(self) -> None:
        view = {
            "source_manifest": [{"name": "sample.pdf", "sha256": "abc", "page_count": 2}],
            "extraction_summary": {"batch_count": 1},
            "candidate_count": 2,
            "evidence_groups": [
                {
                    "evidence_group_id": "EGRP-0001",
                    "route_candidate_ids": ["CAND-00001"],
                    "pdf_pages": [1],
                    "section_path": ["第一章"],
                    "segments": [{
                        "candidate_ids": ["CAND-00001"],
                        "pdf_pages": [1],
                        "context_headings": ["第一章"],
                        "quote": "會議室應設置智慧媒體牆。",
                        "space_hints": ["會議室"],
                        "text_quality_flags": [],
                    }],
                },
                {
                    "evidence_group_id": "EGRP-0002",
                    "route_candidate_ids": ["CAND-00002"],
                    "pdf_pages": [2],
                    "section_path": ["第二章"],
                    "segments": [{
                        "candidate_ids": ["CAND-00002"],
                        "pdf_pages": [2],
                        "context_headings": ["第二章"],
                        "quote": "服務空間應配置旅客服務柱。",
                        "space_hints": ["服務空間"],
                        "text_quality_flags": [],
                    }],
                },
            ],
        }
        with TemporaryDirectory() as directory:
            output = Path(directory)
            manifest = m1_build_source_dossier.prepare_screening_batches(view, output)
            batch = manifest["batches"][0]
            self.assertEqual([1, 2], batch["pdf_pages"])
            (output / batch["result_file"]).write_text(
                "\n".join([
                    f"<!-- screened:{batch['batch_id']} -->",
                    "<!-- reviewed-pages:1,2 -->",
                    "<!-- reviewed-groups:EGRP-0001,EGRP-0002 -->",
                    "",
                    "## 保留來源",
                    "- PDF 1；EGRP-0001；CAND-00001：會議室應設置智慧媒體牆。",
                    "",
                    "## 需第二階段判斷的上下文",
                    "- PDF 2；EGRP-0002；CAND-00002：服務空間應配置旅客服務柱。",
                ]),
                encoding="utf-8",
            )
            m1_build_source_dossier.build_weak_current_source(
                output / "screen_manifest.json",
                output / "weak_current_source.md",
            )
            receipt = json.loads((output / "stage1_receipt.json").read_text(encoding="utf-8"))
            self.assertEqual([1, 2], receipt["screened_pdf_pages"])
            self.assertEqual(["EGRP-0001", "EGRP-0002"], receipt["screened_evidence_group_ids"])


if __name__ == "__main__":
    unittest.main()
