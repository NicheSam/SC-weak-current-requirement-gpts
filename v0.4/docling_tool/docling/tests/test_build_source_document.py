import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "build_source_document.py"
SPEC = importlib.util.spec_from_file_location("build_source_document", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SourceDocumentTests(unittest.TestCase):
    def test_choose_canonical_page_prefers_complete_review_over_garbled_primary(self):
        primary = "- 資訊設備不得使用大陸產品。 、、(、、、 綁材料（可相容品）"
        review = (
            "- 弱電系統應不綁密碼、不鎖碼、不綁材料（可相容品），"
            "並提供開放通信協定及操作手冊。本案所有資訊設備不得使用大陸產品。"
        )

        selected, source, metrics = MODULE.choose_canonical_page(
            primary, review, ["probable_fragment"]
        )

        self.assertEqual(source, "full_page")
        self.assertEqual(selected, review)
        self.assertGreater(metrics["full_page_score"], metrics["pdf_aware_score"])

    def test_review_alternative_is_not_duplicated_into_primary_document(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = Path(temporary_directory)
            primary_dir = run_dir / "pages" / "pdf_aware"
            review_dir = run_dir / "pages" / "full_page"
            primary_dir.mkdir(parents=True)
            review_dir.mkdir(parents=True)
            manifest = {
                "source_file": "sample.pdf",
                "source_sha256": "abc123",
                "pages": {
                    "1": {
                        "pdf_page": 1,
                        "printed_page_candidate": 20,
                        "needs_ai_review": True,
                        "review_reasons": ["low_native_text"],
                    }
                },
            }
            (run_dir / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (primary_dir / "page_0001.md").write_text(
                "PRIMARY ONLY", encoding="utf-8"
            )
            (review_dir / "page_0001.md").write_text(
                "REVIEW ONLY", encoding="utf-8"
            )
            source_document = run_dir / "source_document.md"
            review_document = run_dir / "ocr_review_alternatives.md"

            summary = MODULE.build_document(
                run_dir, source_document, review_document
            )

            primary_text = source_document.read_text(encoding="utf-8")
            review_text = review_document.read_text(encoding="utf-8")
            self.assertEqual(
                summary,
                {"complete_pages": 1, "review_pages": 1, "canonical_pages": 1},
            )
            self.assertIn("PRIMARY ONLY", primary_text)
            self.assertNotIn("REVIEW ONLY", primary_text)
            self.assertIn("REVIEW ONLY", review_text)
            self.assertNotIn("PRIMARY ONLY", review_text)

    def test_build_document_creates_clean_canonical_source_and_records_choice(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = Path(temporary_directory)
            primary_dir = run_dir / "pages" / "pdf_aware"
            review_dir = run_dir / "pages" / "full_page"
            primary_dir.mkdir(parents=True)
            review_dir.mkdir(parents=True)
            manifest = {
                "source_file": "sample.pdf",
                "source_sha256": "abc123",
                "pages": {
                    "1": {
                        "pdf_page": 1,
                        "printed_page_candidate": 20,
                        "needs_ai_review": True,
                        "review_reasons": ["probable_fragment"],
                    }
                },
            }
            (run_dir / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (primary_dir / "page_0001.md").write_text(
                "<!-- image omitted; see Docling JSON provenance -->\n"
                "臺中市政府北區中央市場好宅新建工程 委託專案管理(含監造)技術服務案\n"
                "資訊設備不得使用大陸產品。 、、(、、、 綁材料",
                encoding="utf-8",
            )
            review = (
                "臺中市政府北區中央市場好宅新建工程 委託專案管理(含監造)技術服務案\n"
                "弱電系統應不綁密碼、不鎖碼、不綁材料，並提供開放通信協定。"
            )
            (review_dir / "page_0001.md").write_text(review, encoding="utf-8")
            source_document = run_dir / "source_document.md"
            review_document = run_dir / "ocr_review_alternatives.md"
            clean_document = run_dir / "source_document_clean.md"

            summary = MODULE.build_document(
                run_dir, source_document, review_document, clean_document
            )

            clean_text = clean_document.read_text(encoding="utf-8")
            updated_manifest = json.loads(
                (run_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["canonical_pages"], 1)
            self.assertIn("不綁密碼、不鎖碼", clean_text)
            self.assertNotIn("image omitted", clean_text)
            self.assertNotIn("委託專案管理(含監造)技術服務案", clean_text)
            self.assertEqual(
                updated_manifest["pages"]["1"]["canonical_source"], "full_page"
            )


if __name__ == "__main__":
    unittest.main()
