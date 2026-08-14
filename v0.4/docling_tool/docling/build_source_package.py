from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PACKAGE_OUTPUTS = (
    "source_document_clean.md",
    "source_document.md",
    "ocr_review_alternatives.md",
)


def _safe_markdown_text(value: str) -> str:
    return value.replace("`", "'").strip()


def _document_header(index: int, document: dict[str, Any]) -> str:
    name = _safe_markdown_text(str(document["original_name"]))
    role = _safe_markdown_text(str(document["role"]))
    document_id = _safe_markdown_text(str(document["id"]))
    return (
        "\n\n---\n\n"
        f"<!-- source_package_document_start: {document_id} -->\n"
        f"# Source document {index}: {name}\n\n"
        f"- Document role: `{role}`\n"
        f"- Original filename: `{name}`\n"
        f"- Source document ID: `{document_id}`\n\n"
        "> Page numbers below belong to this document only. Preserve the document name "
        "together with every cited page.\n\n"
    )


def build_package(package_dir: Path, plan_path: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    documents = list(plan.get("documents") or [])
    if not documents:
        raise ValueError("Package plan contains no documents.")

    package_dir.mkdir(parents=True, exist_ok=True)
    combined: dict[str, list[str]] = {
        name: [
            "# Canonical AI-readable source package\n\n",
            f"- Document count: {len(documents)}\n",
            "- The `primary_requirements` document is the governing requirement source.\n",
            "- Documents marked `review_comments` are review questions, replies or meeting records; "
            "do not treat them as governing requirements unless the text explicitly changes the requirement.\n",
            "- Always cite both the document name and that document's PDF page.\n",
        ]
        for name in PACKAGE_OUTPUTS
    }
    package_documents: list[dict[str, Any]] = []
    total_pages = 0

    for index, document in enumerate(documents, start=1):
        run_dir = Path(document.get("run_dir") or document["output"]).resolve()
        manifest_path = run_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        page_count = int(manifest.get("source_total_pages") or 0)
        total_pages += page_count

        for output_name in PACKAGE_OUTPUTS:
            source_path = run_dir / output_name
            if not source_path.is_file():
                raise FileNotFoundError(source_path)
            combined[output_name].append(_document_header(index, document))
            combined[output_name].append(source_path.read_text(encoding="utf-8").strip())
            combined[output_name].append(
                f"\n\n<!-- source_package_document_end: {document['id']} -->\n"
            )

        package_documents.append(
            {
                "id": document["id"],
                "role": document["role"],
                "original_name": document["original_name"],
                "source_sha256": manifest.get("source_sha256"),
                "source_total_pages": page_count,
                "manifest": str(manifest_path),
            }
        )

    for output_name, parts in combined.items():
        (package_dir / output_name).write_text(
            "".join(parts).rstrip() + "\n",
            encoding="utf-8",
            newline="\n",
        )

    package_manifest = {
        "package_version": 1,
        "document_count": len(package_documents),
        "source_total_pages": total_pages,
        "documents": package_documents,
        "outputs": list(PACKAGE_OUTPUTS),
    }
    (package_dir / "manifest.json").write_text(
        json.dumps(package_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return package_manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Combine independently converted Docling documents into one GPTS source package."
    )
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    summary = build_package(args.package_dir.resolve(), args.plan.resolve())
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
