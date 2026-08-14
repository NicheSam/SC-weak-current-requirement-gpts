import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "build_source_package.py"
SPEC = importlib.util.spec_from_file_location("build_source_package", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class BuildSourcePackageTests(unittest.TestCase):
    def test_combines_documents_without_losing_roles_or_page_identity(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            documents = []
            for index, (role, name) in enumerate(
                [
                    ("primary_requirements", "統包需求書.pdf"),
                    ("review_comments", "審查意見.pdf"),
                ],
                start=1,
            ):
                run_dir = root / f"run_{index}"
                run_dir.mkdir()
                (run_dir / "manifest.json").write_text(
                    json.dumps(
                        {
                            "source_sha256": f"sha-{index}",
                            "source_total_pages": index,
                        }
                    ),
                    encoding="utf-8",
                )
                for output_name in MODULE.PACKAGE_OUTPUTS:
                    (run_dir / output_name).write_text(
                        f"<!-- source_pdf_page: 1 -->\n# Page 1\n{name} content\n",
                        encoding="utf-8",
                    )
                documents.append(
                    {
                        "id": f"doc-{index}",
                        "role": role,
                        "original_name": name,
                        "run_dir": str(run_dir),
                    }
                )

            package_dir = root / "package"
            plan_path = root / "plan.json"
            plan_path.write_text(
                json.dumps({"documents": documents}, ensure_ascii=False),
                encoding="utf-8",
            )

            summary = MODULE.build_package(package_dir, plan_path)
            clean = (package_dir / "source_document_clean.md").read_text(
                encoding="utf-8"
            )

            self.assertEqual(summary["document_count"], 2)
            self.assertEqual(summary["source_total_pages"], 3)
            self.assertIn("Document role: `primary_requirements`", clean)
            self.assertIn("Document role: `review_comments`", clean)
            self.assertIn("Original filename: `統包需求書.pdf`", clean)
            self.assertIn("Original filename: `審查意見.pdf`", clean)
            self.assertEqual(clean.count("source_pdf_page: 1"), 2)


if __name__ == "__main__":
    unittest.main()
