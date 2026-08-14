from __future__ import annotations

import argparse
import ctypes
import errno
import os
import platform
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


PREFIX = "DOC_ERR"
EXIT_CODES = {
    "E_PLATFORM": 10,
    "E_ARCH": 11,
    "E_PERMISSION": 12,
    "E_DISK_SPACE": 13,
    "E_PATH_TOO_LONG": 14,
    "E_NETWORK": 15,
    "E_VC_RUNTIME": 20,
    "E_TORCH_RUNTIME": 21,
    "E_DEPENDENCY_MISSING": 22,
    "E_DOCLING_RUNTIME": 23,
    "E_MEMORY": 24,
    "E_PDF_INVALID": 30,
    "E_RUNTIME": 99,
}
FATAL_ENVIRONMENT_CODES = {
    "E_PLATFORM",
    "E_ARCH",
    "E_PERMISSION",
    "E_DISK_SPACE",
    "E_PATH_TOO_LONG",
    "E_NETWORK",
    "E_VC_RUNTIME",
    "E_TORCH_RUNTIME",
    "E_DEPENDENCY_MISSING",
    "E_DOCLING_RUNTIME",
    "E_MEMORY",
}


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    action: str
    fatal: bool = True

    def to_line(self) -> str:
        fields = (self.code, self.message, self.action)
        clean = [str(field).replace("|", "/").replace("\r", " ").replace("\n", " ") for field in fields]
        return "|".join((PREFIX, *clean))


def parse_diagnostic_line(line: str) -> Diagnostic | None:
    parts = line.strip().split("|", 3)
    if len(parts) != 4 or parts[0] != PREFIX:
        return None
    return Diagnostic(code=parts[1], message=parts[2], action=parts[3])


def is_fatal_environment_error(exc: BaseException) -> bool:
    return classify_exception(exc).code in FATAL_ENVIRONMENT_CODES


def classify_exception(exc: BaseException) -> Diagnostic:
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    winerror = getattr(exc, "winerror", None)
    error_number = getattr(exc, "errno", None)

    if isinstance(exc, MemoryError):
        return Diagnostic(
            "E_MEMORY",
            "可用記憶體不足，Docling 無法繼續處理。",
            "關閉其他大型程式後重試；大型掃描 PDF 可拆成較小檔案。",
        )
    if isinstance(exc, PermissionError) or winerror == 5:
        return Diagnostic(
            "E_PERMISSION",
            "工具無法寫入目前資料夾或讀取來源檔案。",
            "將工具解壓縮到使用者可寫入的本機資料夾，並確認 PDF 未被其他程式鎖定。",
        )
    if isinstance(exc, ModuleNotFoundError):
        return Diagnostic(
            "E_DEPENDENCY_MISSING",
            "Docling 執行環境缺少必要套件。",
            "關閉介面後重新執行 install_docling.cmd；不要手動移動 .venv 內容。",
        )
    if winerror in {126, 1114} and any(
        token in lowered for token in ("torch", "c10.dll", "fbgemm", "shm.dll")
    ):
        return Diagnostic(
            "E_TORCH_RUNTIME",
            "PyTorch 原生元件無法載入，通常是 Visual C++ Runtime 缺少、過舊或安裝不完整。",
            "重新執行 install_docling.cmd，允許安裝 Microsoft Visual C++ Runtime；若公司電腦阻擋安裝，請交由資訊人員處理。",
        )
    if winerror == 193:
        return Diagnostic(
            "E_ARCH",
            "執行環境的 32／64 位元架構不相容。",
            "請使用 64 位元 Windows 與本專案提供的安裝器重新建立環境。",
        )
    if winerror == 206 or "path too long" in lowered or "filename or extension is too long" in lowered:
        return Diagnostic(
            "E_PATH_TOO_LONG",
            "工具或案件資料夾路徑過長。",
            "將工具移到較短路徑，例如 C:\\Docling，再重新安裝與處理。",
        )
    if error_number == errno.ENOSPC or "no space left" in lowered or "磁碟空間不足" in text:
        return Diagnostic(
            "E_DISK_SPACE",
            "磁碟空間不足。",
            "至少保留 4 GB 可用空間後，再重新執行安裝或轉換。",
        )
    if any(token in lowered for token in ("ssl", "certificate", "urlopen", "connection", "timed out")):
        return Diagnostic(
            "E_NETWORK",
            "無法下載執行環境、套件或模型。",
            "確認可連線至 Microsoft、GitHub、astral.sh、PyPI 與模型來源；公司網路可能需要代理或白名單。",
        )
    if any(token in lowered for token in ("pdfium", "invalid pdf", "cannot open document", "password")):
        return Diagnostic(
            "E_PDF_INVALID",
            "PDF 無法開啟、已損壞或受到密碼保護。",
            "確認 PDF 可正常開啟且已解除密碼保護，再重新上傳。",
        )
    return Diagnostic(
        "E_RUNTIME",
        "Docling 執行時發生未分類錯誤。",
        "保留畫面中的錯誤代碼與處理紀錄，連同案件頁數回報維護者。",
    )


def check_windows_runtime(tool_root: Path, minimum_free_gb: float = 2.5) -> None:
    if platform.system() != "Windows":
        raise RuntimeError("This package supports Windows only.")
    if sys.maxsize <= 2**32 or platform.machine().lower() not in {"amd64", "x86_64"}:
        error = OSError("64-bit Windows is required")
        error.winerror = 193
        raise error

    free_bytes = shutil.disk_usage(tool_root).free
    if free_bytes < int(minimum_free_gb * 1024**3):
        error = OSError("No space left on device")
        error.errno = errno.ENOSPC
        raise error

    probe_dir = tool_root / "results"
    probe_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=probe_dir, delete=True):
        pass

    for library in ("vcruntime140.dll", "msvcp140.dll", "vcruntime140_1.dll"):
        try:
            ctypes.CDLL(library)
        except OSError as exc:
            raise RuntimeError(f"Missing Microsoft Visual C++ runtime library: {library}") from exc


def verify_python_stack() -> None:
    import torch
    import rapidocr  # noqa: F401
    import pypdfium2  # noqa: F401
    from docling.document_converter import DocumentConverter  # noqa: F401

    if not torch.__version__:
        raise RuntimeError("PyTorch version is unavailable")


def run_preflight(tool_root: Path) -> Diagnostic | None:
    try:
        check_windows_runtime(tool_root)
        verify_python_stack()
    except RuntimeError as exc:
        if "Missing Microsoft Visual C++ runtime library" in str(exc):
            return Diagnostic(
                "E_VC_RUNTIME",
                "缺少 Microsoft Visual C++ 2015–2022 x64 Runtime。",
                "重新執行 install_docling.cmd 並允許安裝 Microsoft 官方 Runtime。",
            )
        return classify_exception(exc.__cause__ or exc)
    except BaseException as exc:
        return classify_exception(exc)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Docling Windows runtime.")
    parser.add_argument("--tool-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    diagnostic = run_preflight(args.tool_root.resolve())
    if diagnostic:
        print(diagnostic.to_line(), file=sys.stderr, flush=True)
        return EXIT_CODES.get(diagnostic.code, 99)
    print("DOC_OK|Docling runtime validation passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
