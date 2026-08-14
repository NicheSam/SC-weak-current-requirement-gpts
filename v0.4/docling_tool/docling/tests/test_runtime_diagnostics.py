import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "runtime_diagnostics.py"
SPEC = importlib.util.spec_from_file_location("runtime_diagnostics", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RuntimeDiagnosticsTests(unittest.TestCase):
    def test_torch_winerror_126_is_classified_as_native_runtime_failure(self):
        error = OSError('Error loading "torch_python.dll" or one of its dependencies.')
        error.winerror = 126

        diagnostic = MODULE.classify_exception(error)

        self.assertEqual(diagnostic.code, "E_TORCH_RUNTIME")
        self.assertTrue(diagnostic.fatal)
        self.assertIn("Visual C++", diagnostic.action)

    def test_missing_module_is_classified_as_incomplete_installation(self):
        diagnostic = MODULE.classify_exception(
            ModuleNotFoundError("No module named 'rapidocr'")
        )

        self.assertEqual(diagnostic.code, "E_DEPENDENCY_MISSING")
        self.assertIn("install_docling.cmd", diagnostic.action)

    def test_permission_error_is_classified(self):
        diagnostic = MODULE.classify_exception(PermissionError("access denied"))

        self.assertEqual(diagnostic.code, "E_PERMISSION")

    def test_disk_full_is_classified(self):
        error = OSError("No space left on device")
        error.errno = 28

        diagnostic = MODULE.classify_exception(error)

        self.assertEqual(diagnostic.code, "E_DISK_SPACE")

    def test_path_too_long_is_classified(self):
        error = OSError("The filename or extension is too long")
        error.winerror = 206

        diagnostic = MODULE.classify_exception(error)

        self.assertEqual(diagnostic.code, "E_PATH_TOO_LONG")

    def test_memory_error_is_classified(self):
        diagnostic = MODULE.classify_exception(MemoryError())

        self.assertEqual(diagnostic.code, "E_MEMORY")
        self.assertTrue(MODULE.is_fatal_environment_error(MemoryError()))

    def test_network_error_is_classified(self):
        diagnostic = MODULE.classify_exception(
            RuntimeError("SSL certificate verification timed out")
        )

        self.assertEqual(diagnostic.code, "E_NETWORK")

    def test_invalid_pdf_is_not_an_environment_failure(self):
        error = RuntimeError("Invalid PDF: password protected")
        diagnostic = MODULE.classify_exception(error)

        self.assertEqual(diagnostic.code, "E_PDF_INVALID")
        self.assertFalse(MODULE.is_fatal_environment_error(error))

    def test_unknown_page_error_does_not_stop_all_pages_as_environment_failure(self):
        error = RuntimeError("Unexpected table cell geometry")

        self.assertEqual(MODULE.classify_exception(error).code, "E_RUNTIME")
        self.assertFalse(MODULE.is_fatal_environment_error(error))

    def test_diagnostic_line_round_trip(self):
        diagnostic = MODULE.Diagnostic(
            code="E_TEST",
            message="test message",
            action="test action",
            fatal=True,
        )

        parsed = MODULE.parse_diagnostic_line(diagnostic.to_line())

        self.assertEqual(parsed, diagnostic)


if __name__ == "__main__":
    unittest.main()
