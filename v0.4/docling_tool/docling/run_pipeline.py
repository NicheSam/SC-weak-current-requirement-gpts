from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_diagnostics import (  # noqa: E402
    EXIT_CODES,
    classify_exception,
    is_fatal_environment_error,
)


os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("DOCLING_INFERENCE_COMPILE_TORCH_MODELS", "false")


@dataclass
class PageRecord:
    pdf_page: int
    printed_page_candidate: int | None
    native_text_chars: int
    pdf_aware_chars: int = 0
    full_page_chars: int = 0
    needs_ai_review: bool = False
    review_reasons: list[str] | None = None
    pdf_aware_status: str = "pending"
    full_page_status: str = "not_required"
    elapsed_seconds: float = 0.0
    error: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def write_json_atomic(path: Path, payload: Any) -> None:
    write_text_atomic(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


def printed_page_candidate(native_text: str) -> int | None:
    for raw_line in native_text.splitlines()[:8]:
        line = raw_line.strip()
        if re.fullmatch(r"\d{1,3}", line):
            return int(line)
    return None


def review_reasons(
    *, native_chars: int, markdown: str, low_native_threshold: int
) -> list[str]:
    reasons: list[str] = []
    if native_chars < low_native_threshold:
        reasons.append("low_native_text")
    if len(markdown.strip()) < 150:
        reasons.append("short_pdf_aware_output")
    if "�" in markdown:
        reasons.append("replacement_character")
    if re.search(r"(?:、\s*){3,}|(?:[，。]\s*){4,}", markdown):
        reasons.append("probable_fragment")
    return reasons


def page_paths(output_dir: Path, page_no: int, mode: str) -> tuple[Path, Path]:
    mode_dir = output_dir / "pages" / mode
    stem = f"page_{page_no:04d}"
    return mode_dir / f"{stem}.md", mode_dir / f"{stem}.json"


def configure_cache(tool_root: Path) -> None:
    cache_root = tool_root / "model_cache"
    os.environ.setdefault("HF_HOME", str(cache_root / "huggingface"))
    os.environ.setdefault("MODELSCOPE_CACHE", str(cache_root / "modelscope"))


def make_converter(mode: str):
    from docling.datamodel.accelerator_options import (
        AcceleratorDevice,
        AcceleratorOptions,
    )
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        OcrMode,
        PdfPipelineOptions,
        RapidOcrOptions,
        TableFormerMode,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    ocr_mode = (
        OcrMode.PDF_AWARE_LAYOUT_REGIONS
        if mode == "pdf_aware"
        else OcrMode.FULL_PAGE
    )
    options = PdfPipelineOptions()
    options.do_ocr = True
    options.ocr_options = RapidOcrOptions(
        lang=["chinese_cht"],
        mode=ocr_mode,
    )
    options.do_table_structure = True
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    options.accelerator_options = AcceleratorOptions(
        num_threads=4,
        device=AcceleratorDevice.CPU,
    )
    options.ocr_batch_size = 1
    options.layout_batch_size = 1
    options.table_batch_size = 1
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )


def convert_page(converter, source: Path, page_no: int) -> tuple[str, dict[str, Any]]:
    result = converter.convert(
        source,
        page_range=(page_no, page_no),
        raises_on_error=True,
    )
    markdown = result.document.export_to_markdown(
        page_no=page_no,
        image_placeholder="<!-- image omitted; see Docling JSON provenance -->",
    )
    return markdown.strip() + "\n", result.document.export_to_dict()


def load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run page-checkpointed Docling extraction with selective full-page OCR review."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--page-start", type=int, default=1)
    parser.add_argument("--page-end", type=int)
    parser.add_argument("--low-native-threshold", type=int, default=200)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.input.resolve()
    output_dir = args.output.resolve()
    tool_root = Path(__file__).resolve().parents[1]
    configure_cache(tool_root)

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(source)
    total_pages = len(pdf)
    page_end = args.page_end or total_pages
    if args.page_start < 1 or page_end > total_pages or args.page_start > page_end:
        raise ValueError(f"Invalid page range {args.page_start}-{page_end} for {total_pages} pages")

    source_hash = sha256_file(source)
    manifest_path = output_dir / "manifest.json"
    manifest = load_manifest(manifest_path)
    if manifest and manifest.get("source_sha256") != source_hash:
        raise RuntimeError("Existing manifest belongs to a different source PDF")
    if not manifest:
        manifest = {
            "schema_version": 1,
            "source_file": source.name,
            "source_sha256": source_hash,
            "source_total_pages": total_pages,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "settings": {
                "primary_mode": "pdf_aware_layout_regions",
                "review_mode": "full_page",
                "ocr_engine": "rapidocr",
                "ocr_language": "chinese_cht",
                "table_mode": "accurate",
                "low_native_threshold": args.low_native_threshold,
            },
            "pages": {},
        }

    try:
        aware_converter = make_converter("pdf_aware")
    except BaseException as exc:
        diagnostic = classify_exception(exc)
        print(diagnostic.to_line(), file=sys.stderr, flush=True)
        return EXIT_CODES.get(diagnostic.code, 99)
    full_converter = None
    for page_no in range(args.page_start, page_end + 1):
        aware_md_path, aware_json_path = page_paths(output_dir, page_no, "pdf_aware")
        full_md_path, full_json_path = page_paths(output_dir, page_no, "full_page")
        existing = manifest["pages"].get(str(page_no), {})
        if (
            not args.force
            and aware_md_path.exists()
            and aware_json_path.exists()
            and existing.get("pdf_aware_status") == "complete"
            and (
                existing.get("full_page_status") in {"complete", "not_required"}
                or not existing.get("needs_ai_review")
            )
        ):
            print(f"[{page_no}/{page_end}] resume: already complete", flush=True)
            continue

        started = time.perf_counter()
        native_text = pdf[page_no - 1].get_textpage().get_text_range()
        record = PageRecord(
            pdf_page=page_no,
            printed_page_candidate=printed_page_candidate(native_text),
            native_text_chars=len(native_text.strip()),
        )
        try:
            aware_md, aware_json = convert_page(aware_converter, source, page_no)
            write_text_atomic(aware_md_path, aware_md)
            write_json_atomic(aware_json_path, aware_json)
            record.pdf_aware_status = "complete"
            record.pdf_aware_chars = len(aware_md.strip())
            reasons = review_reasons(
                native_chars=record.native_text_chars,
                markdown=aware_md,
                low_native_threshold=args.low_native_threshold,
            )
            record.review_reasons = reasons
            record.needs_ai_review = bool(reasons)

            if record.needs_ai_review:
                if full_converter is None:
                    try:
                        full_converter = make_converter("full_page")
                    except BaseException as exc:
                        diagnostic = classify_exception(exc)
                        print(diagnostic.to_line(), file=sys.stderr, flush=True)
                        return EXIT_CODES.get(diagnostic.code, 99)
                full_md, full_json = convert_page(full_converter, source, page_no)
                write_text_atomic(full_md_path, full_md)
                write_json_atomic(full_json_path, full_json)
                record.full_page_status = "complete"
                record.full_page_chars = len(full_md.strip())
        except Exception as exc:
            if is_fatal_environment_error(exc):
                diagnostic = classify_exception(exc)
                print(diagnostic.to_line(), file=sys.stderr, flush=True)
                return EXIT_CODES.get(diagnostic.code, 99)
            record.error = f"{type(exc).__name__}: {exc}"
            if record.pdf_aware_status != "complete":
                record.pdf_aware_status = "failed"
            elif record.needs_ai_review:
                record.full_page_status = "failed"
        record.elapsed_seconds = round(time.perf_counter() - started, 3)
        manifest["pages"][str(page_no)] = asdict(record)
        manifest["updated_at"] = utc_now()
        write_json_atomic(manifest_path, manifest)
        print(
            f"[{page_no}/{page_end}] aware={record.pdf_aware_status} "
            f"review={record.full_page_status} native={record.native_text_chars} "
            f"seconds={record.elapsed_seconds}",
            flush=True,
        )
        if record.error:
            print(f"  error: {record.error}", file=sys.stderr, flush=True)

    failed = [
        item
        for item in manifest["pages"].values()
        if item.get("pdf_aware_status") == "failed"
        or item.get("full_page_status") == "failed"
    ]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
