import importlib.util
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "docling_web_ui.py"
SPEC = importlib.util.spec_from_file_location("docling_web_ui", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class DoclingWebUiHelperTests(unittest.TestCase):
    def test_parse_diagnostic_log_line(self):
        parsed = MODULE.parse_diagnostic_log_line(
            "DOC_ERR|E_TORCH_RUNTIME|Torch failed|Install Visual C++"
        )

        self.assertEqual(parsed["code"], "E_TORCH_RUNTIME")
        self.assertEqual(parsed["message"], "Torch failed")
        self.assertEqual(parsed["action"], "Install Visual C++")

    def test_safe_stem_removes_path_unsafe_characters(self):
        self.assertEqual(MODULE.safe_stem("中央 市場(測試).pdf"), "pdf_source")

    def test_manifest_progress_counts_completed_and_review_pages(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "manifest.json"
            path.write_text(
                json.dumps(
                    {
                        "source_total_pages": 3,
                        "pages": {
                            "1": {
                                "pdf_aware_status": "complete",
                                "full_page_status": "not_required",
                                "error": None,
                            },
                            "2": {
                                "pdf_aware_status": "complete",
                                "full_page_status": "complete",
                                "error": None,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(MODULE.manifest_progress(path), (2, 3, 1, 0))

    def test_home_page_is_served_locally(self):
        server = MODULE.ThreadingHTTPServer(("127.0.0.1", 0), MODULE.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            with urllib.request.urlopen(f"http://{host}:{port}/", timeout=3) as response:
                text = response.read().decode("utf-8")
            self.assertIn("Docling PDF 來源轉換器", text)
            self.assertIn("開始／續跑", text)
            self.assertIn("source_document_clean.md", MODULE.OUTPUT_FILES)
            self.assertIn("單一正式來源", text)
            self.assertIn("主需求書（必選）", text)
            self.assertIn("審查意見／補充文件（選填，可多選）", text)
            self.assertIn('id="reviews"', text)
            self.assertIn("multiple", text)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
