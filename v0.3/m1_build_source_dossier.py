#!/usr/bin/env python3
"""Build bounded source-reading batches and one AI-selected weak-current source file."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any


DOSSIER_VERSION = "1.2"
SCREENING_BATCH_VERSION = "1.1"
STAGE1_RECEIPT_VERSION = "1.1"
DEFAULT_SCREENING_MAX_GROUPS = 12
DEFAULT_SCREENING_MAX_CHARS = 28000


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def clean_inline(value: Any) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())


def quote_block(text: Any) -> list[str]:
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return [f"> {line}" if line else ">" for line in lines]


def context_lines(label: str, context: Any, segment_candidate_ids: set[str]) -> list[str]:
    if not context:
        return []
    if isinstance(context, dict):
        raw_ids = [str(value) for value in context.get("candidate_ids", []) if value]
        text = context.get("quote", "")
    else:
        raw_ids = []
        text = str(context)
    suffix = f" | {','.join(raw_ids)}" if raw_ids else ""
    lines = [f"**{label}{suffix}**"]
    if raw_ids and all(value in segment_candidate_ids for value in raw_ids):
        lines.append("> 內容已完整收錄於其他來源片段，依候選 ID 交叉核對。")
    else:
        lines.extend(quote_block(text))
    lines.append("")
    return lines


def validate_candidate_view(data: dict[str, Any]) -> None:
    groups = data.get("evidence_groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("candidate view must contain non-empty evidence_groups")


def render_group(group: dict[str, Any], segment_candidate_ids: set[str]) -> str:
    group_id = clean_inline(group.get("evidence_group_id"))
    pages = [str(value) for value in group.get("pdf_pages", []) if value]
    section_path = [clean_inline(value) for value in group.get("section_path", []) if clean_inline(value)]
    route_ids = [str(value) for value in group.get("route_candidate_ids", []) if value]
    lines = [
        f"## {group_id} | PDF {','.join(pages) or '?'} | {' / '.join(section_path) or '未辨識章節'}",
        "",
        f"<!-- evidence_group:{group_id} pages:{','.join(pages)} candidate_ids:{','.join(route_ids)} -->",
        "",
    ]
    lines.extend(context_lines("前文", group.get("leading_context"), segment_candidate_ids))

    for index, segment in enumerate(group.get("segments", []), start=1):
        candidate_ids = [str(value) for value in segment.get("candidate_ids", []) if value]
        segment_pages = [str(value) for value in segment.get("pdf_pages", []) if value]
        lines.extend([
            f"### {','.join(candidate_ids) or f'{group_id}-S{index:02d}'} | PDF {','.join(segment_pages) or ','.join(pages) or '?'}",
            "",
        ])
        headings = [clean_inline(value) for value in segment.get("context_headings", []) if clean_inline(value)]
        if headings:
            lines.append(f"- 來源脈絡：{' / '.join(headings)}")
        spaces = [clean_inline(value) for value in segment.get("space_hints", []) if clean_inline(value)]
        if spaces:
            lines.append(f"- 來源空間提示：{'、'.join(spaces)}")
        flags = [clean_inline(value) for value in segment.get("text_quality_flags", []) if clean_inline(value)]
        if flags:
            lines.append(f"- 文字狀態：{'、'.join(flags)}")
        origins = [clean_inline(value) for value in segment.get("origin_kinds", []) if clean_inline(value)]
        confidences = [clean_inline(value) for value in segment.get("source_confidences", []) if clean_inline(value)]
        if origins:
            lines.append(f"- 來源形式：{'、'.join(origins)}")
        if confidences and confidences != ["not_applicable"]:
            lines.append(f"- 辨識信心：{'、'.join(confidences)}")
        if headings or spaces or flags or origins or confidences:
            lines.append("")
        lines.extend(quote_block(segment.get("quote", "")))
        lines.append("")

    lines.extend(context_lines("後文", group.get("trailing_context"), segment_candidate_ids))
    lines.extend(["---", ""])
    return "\n".join(lines)


def build_dossier(data: dict[str, Any]) -> str:
    validate_candidate_view(data)
    groups = data["evidence_groups"]
    source_manifest = data.get("source_manifest", [])
    source = source_manifest[0] if source_manifest else {}
    segment_candidate_ids = {
        str(candidate_id)
        for group in groups
        for segment in group.get("segments", [])
        for candidate_id in segment.get("candidate_ids", [])
    }
    total_segments = sum(len(group.get("segments", [])) for group in groups)
    visually_resolved_without_text = [
        str(item.get("pdf_page"))
        for item in data.get("unreadable_pages", [])
        if isinstance(item, dict) and item.get("pdf_page")
    ]
    visual_audit = data.get("visual_audit", {})
    pending_region_count = len(visual_audit.get("pending_region_ids", [])) if isinstance(visual_audit, dict) else 0
    unreadable_page_count = len(data.get("unreadable_pages", []))
    lines = [
        "# 全文來源閱讀包",
        "",
        "> 本檔是第一階段 AI 篩選弱電來源的內部閱讀材料，不是正式需求，也不是交付成果。程式只保存可讀文字、頁碼與上下文，不判斷工程語意。",
        "",
        "## 文件資訊",
        "",
        f"- 卷宗版本：{DOSSIER_VERSION}",
        f"- 來源文件：{clean_inline(source.get('name', 'unknown'))}",
        f"- 來源 SHA-256：`{clean_inline(source.get('sha256', 'unknown'))}`",
        f"- PDF 頁數：{source.get('page_count', 'unknown')}",
        f"- 證據群組：{len(groups)}",
        f"- 來源片段：{total_segments}",
        f"- 尚待人工判讀的低信心影像區：{pending_region_count}",
        f"- 無法可靠讀取頁：{unreadable_page_count}",
        f"- 視覺已覆核但未形成可用文字頁：{','.join(visually_resolved_without_text) or '無'}",
        "",
        "## 轉譯原則",
        "",
        "1. 逐批閱讀全部片段，依頁碼、章節、原文及前後文判斷是否與弱電業務相關。",
        "2. 以電信、資訊、電視、通訊、監視、門禁、停車、廣播、對講、感測、控制、資料與跨系統介面等業務語意判斷，不採封閉關鍵字清單。",
        "3. 只把相關原文、必要上下文、頁碼與候選 ID 寫入 weak_current_source.md；不要在此階段寫正式需求，也不得摘要或合併不同義務。",
        "4. 同一段落或設備規格表若含不同設備、規格、數量、供電／備援、介面、空間、操作或測試要求，逐項保留原文及候選 ID；上下文可以共用，獨立要求不可被系統摘要取代。",
        "5. 可讀 OCR 文字與原生文字同等採用。低信心影像須經模型覆核；已判為不可讀或非文字者不阻斷全案，疑似相關且會影響理解時列為來源待確認。",
        "",
        "---",
        "",
    ]

    for group in groups:
        lines.append(render_group(group, segment_candidate_ids).rstrip())
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def prepare_screening_batches(
    data: dict[str, Any],
    output_dir: Path,
    max_groups: int = DEFAULT_SCREENING_MAX_GROUPS,
    max_chars: int = DEFAULT_SCREENING_MAX_CHARS,
) -> dict[str, Any]:
    """Split source evidence into bounded AI screening units without semantic decisions."""
    validate_candidate_view(data)
    if max_groups < 1 or max_chars < 4000:
        raise ValueError("screening batch limits are too small")
    output_dir.mkdir(parents=True, exist_ok=True)
    groups = data["evidence_groups"]
    segment_candidate_ids = {
        str(candidate_id)
        for group in groups
        for segment in group.get("segments", [])
        for candidate_id in segment.get("candidate_ids", [])
    }
    rendered = [
        (
            clean_inline(group.get("evidence_group_id")),
            render_group(group, segment_candidate_ids),
            sorted({int(value) for value in group.get("pdf_pages", []) if str(value).isdigit()}),
        )
        for group in groups
    ]
    batches: list[list[tuple[str, str, list[int]]]] = []
    current: list[tuple[str, str, list[int]]] = []
    current_chars = 0
    for item in rendered:
        item_chars = len(item[1])
        if current and (len(current) >= max_groups or current_chars + item_chars > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_chars
    if current:
        batches.append(current)

    source = (data.get("source_manifest") or [{}])[0]
    manifest_batches = []
    for index, batch in enumerate(batches, start=1):
        batch_id = f"SB-{index:03d}"
        source_name = f"screen_source_{index:03d}.md"
        result_name = f"screen_result_{index:03d}.md"
        group_ids = [item[0] for item in batch]
        pdf_pages = sorted({page for item in batch for page in item[2]})
        reviewed_pages_marker = ",".join(str(value) for value in pdf_pages)
        reviewed_groups_marker = ",".join(group_ids)
        header = [
            f"# {batch_id} | 弱電來源篩選",
            "",
            "> 完整閱讀本批內容，將與弱電業務相關的原文及必要上下文整理到同編號 result。這一步只抽取來源，不寫正式需求。",
            "",
            "## 作業要求",
            "",
            f"1. result 第一行寫 `<!-- screened:{batch_id} -->`。",
            f"2. result 第二行原樣寫 `<!-- reviewed-pages:{reviewed_pages_marker} -->`。",
            f"3. result 第三行原樣寫 `<!-- reviewed-groups:{reviewed_groups_marker} -->`。",
            "4. 以 `保留來源`、`需第二階段判斷的上下文`、`來源待確認` 三區整理；疑似相關時預設保留，不在第一階段追求乾淨排除。",
            "5. 每個項目包含 PDF 頁碼、證據群組 ID、候選 ID、原文及理解所需前後文。",
            "6. 不改寫成正式需求、不分類成最終系統、不建立正式需求 ID；第二階段再由 AI 整體轉譯。不得摘要或合併不同義務。",
            "7. 段落、清單或設備規格表內的不同設備、規格、數量、供電／備援、材料、協定、操作、介面、空間及測試要求要逐項保留；可共用上下文，但不得用概括句取代細項。",
            "8. 寫入三個 marker 前，重新掃讀本批全部群組一次，特別檢查表格、OCR、特殊空間及跨專業介面是否漏留。",
            "9. 若本批沒有相關內容，仍寫三個 marker 並註明本批未發現弱電相關來源。",
            "",
            "---",
            "",
        ]
        text = "\n".join(header) + "\n".join(item[1] for item in batch)
        (output_dir / source_name).write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")
        manifest_batches.append({
            "batch_id": batch_id,
            "source_file": source_name,
            "result_file": result_name,
            "evidence_group_ids": group_ids,
            "pdf_pages": pdf_pages,
            "source_chars": len(text),
        })

    manifest = {
        "schema_version": SCREENING_BATCH_VERSION,
        "source_name": clean_inline(source.get("name", "unknown")),
        "source_sha256": clean_inline(source.get("sha256", "unknown")),
        "pdf_page_count": int(source.get("page_count", 0) or 0),
        "extraction_batch_count": int(data.get("extraction_summary", {}).get("batch_count", 1) or 1),
        "source_candidate_count": int(data.get("candidate_count", 0) or 0),
        "evidence_group_count": len(groups),
        "covered_pdf_pages": sorted({page for group in groups for page in group.get("pdf_pages", []) if isinstance(page, int)}),
        "group_outline": [
            {
                "evidence_group_id": clean_inline(group.get("evidence_group_id")),
                "pdf_pages": sorted({int(value) for value in group.get("pdf_pages", []) if str(value).isdigit()}),
                "section_path": [clean_inline(value) for value in group.get("section_path", []) if clean_inline(value)],
                "source_shapes": sorted({
                    clean_inline(segment.get("source_shape"))
                    for segment in group.get("segments", [])
                    if clean_inline(segment.get("source_shape"))
                }),
                "origin_kinds": sorted({
                    clean_inline(value)
                    for segment in group.get("segments", [])
                    for value in segment.get("origin_kinds", [])
                    if clean_inline(value)
                }),
            }
            for group in groups
        ],
        "batch_count": len(manifest_batches),
        "max_groups": max_groups,
        "max_chars": max_chars,
        "batches": manifest_batches,
    }
    (output_dir / "screen_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    return manifest


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_stage1_receipt(
    manifest: dict[str, Any],
    source_text: str,
    seen_batches: list[str],
    seen_pages: list[int],
    seen_group_ids: list[str],
) -> dict[str, Any]:
    candidate_ids = sorted(set(re.findall(r"\bCAND-[A-Z0-9-]+\b", source_text)))
    return {
        "schema_version": STAGE1_RECEIPT_VERSION,
        "stage": "weak_current_source_complete",
        "source_name": clean_inline(manifest.get("source_name", "unknown")),
        "source_sha256": clean_inline(manifest.get("source_sha256", "unknown")).lower(),
        "pdf_page_count": int(manifest.get("pdf_page_count", 0) or 0),
        "extraction_batch_count": int(manifest.get("extraction_batch_count", 1) or 1),
        "screening_batch_count": int(manifest.get("batch_count", 0) or 0),
        "screened_batch_ids": seen_batches,
        "screened_pdf_pages": seen_pages,
        "screened_evidence_group_ids": seen_group_ids,
        "screened_evidence_group_count": len(seen_group_ids),
        "retained_candidate_id_count": len(candidate_ids),
        "weak_current_source_sha256": sha256_text(source_text),
    }


def build_weak_current_source(
    manifest_path: Path,
    output_path: Path | None = None,
    receipt_path: Path | None = None,
) -> str:
    manifest = load_json(manifest_path)
    base = manifest_path.parent
    parts: list[str] = []
    seen_batches: list[str] = []
    seen_pages: list[int] = []
    seen_group_ids: list[str] = []
    for batch in manifest.get("batches", []):
        batch_id = str(batch.get("batch_id", ""))
        result_path = base / str(batch.get("result_file", ""))
        if not result_path.is_file():
            raise ValueError(f"missing screening result: {result_path.name}")
        text = result_path.read_text(encoding="utf-8")
        marker = f"<!-- screened:{batch_id} -->"
        if text.count(marker) != 1:
            raise ValueError(f"screening marker missing or duplicated in {result_path.name}: {batch_id}")
        expected_pages = sorted({int(value) for value in batch.get("pdf_pages", [])})
        expected_group_ids = [str(value) for value in batch.get("evidence_group_ids", [])]
        pages_match = re.search(r"<!-- reviewed-pages:([^>]*) -->", text)
        groups_match = re.search(r"<!-- reviewed-groups:([^>]*) -->", text)
        actual_pages = sorted(
            int(value.strip())
            for value in (pages_match.group(1).split(",") if pages_match else [])
            if value.strip().isdigit()
        )
        actual_group_ids = [
            value.strip()
            for value in (groups_match.group(1).split(",") if groups_match else [])
            if value.strip()
        ]
        if actual_pages != expected_pages:
            raise ValueError(f"reviewed page marker mismatch in {result_path.name}: {batch_id}")
        if actual_group_ids != expected_group_ids:
            raise ValueError(f"reviewed group marker mismatch in {result_path.name}: {batch_id}")
        seen_batches.append(batch_id)
        seen_pages.extend(expected_pages)
        seen_group_ids.extend(expected_group_ids)
        parts.append(text.rstrip())
    if len(seen_batches) != int(manifest.get("batch_count", -1)):
        raise ValueError("screen manifest batch count mismatch")
    seen_pages = sorted(set(seen_pages))
    if seen_pages != sorted({int(value) for value in manifest.get("covered_pdf_pages", [])}):
        raise ValueError("screen manifest page coverage mismatch")
    if len(seen_group_ids) != int(manifest.get("evidence_group_count", -1)):
        raise ValueError("screen manifest evidence-group coverage mismatch")
    header = [
        "# 弱電來源包",
        "",
        "> 本檔由 AI 逐批閱讀全文來源後抽取，供第二階段依舊版方式進行工程轉譯。它不是正式需求，也不是原文全文。",
        "",
        "## 文件資訊",
        "",
        f"- 來源文件：{clean_inline(manifest.get('source_name', 'unknown'))}",
        f"- 來源 SHA-256：`{clean_inline(manifest.get('source_sha256', 'unknown'))}`",
        f"- 已閱讀批次：{len(seen_batches)} / {manifest.get('batch_count', 0)}",
        "",
        "## 使用原則",
        "",
        "- 第二階段必須重新理解並轉譯，不得直接把本檔原文當作正式需求。",
        "- 跨頁、跨章的同一義務要合併；不同設備、空間、動作、條件或狀態要拆分。",
        "- 來源包中的獨立設備、規格、數量、供電／備援、材料、協定、操作、介面及測試要求不得被系統摘要取代。",
        "- 保留頁碼、候選 ID、原文、否定、例外、數量及不確定性。",
        "",
        "---",
        "",
    ]
    result = "\n".join(header) + "\n\n---\n\n".join(parts).rstrip() + "\n"
    if output_path is not None:
        output_path.write_text(result, encoding="utf-8", newline="\n")
        receipt_output = receipt_path or output_path.with_name("stage1_receipt.json")
        receipt_output.write_text(
            json.dumps(
                build_stage1_receipt(manifest, result, seen_batches, seen_pages, seen_group_ids),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
            newline="\n",
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a bounded source reading pack from m1_candidates.json")
    parser.add_argument("candidate_view", type=Path, nargs="?")
    parser.add_argument("output", type=Path, nargs="?", default=Path("source_reading_pack.md"))
    parser.add_argument("--screening-dir", type=Path)
    parser.add_argument("--max-screening-groups", type=int, default=DEFAULT_SCREENING_MAX_GROUPS)
    parser.add_argument("--max-screening-chars", type=int, default=DEFAULT_SCREENING_MAX_CHARS)
    parser.add_argument("--build-weak-current-source", type=Path)
    parser.add_argument("--weak-current-output", type=Path)
    parser.add_argument("--stage1-receipt", type=Path)
    args = parser.parse_args()
    try:
        if args.build_weak_current_source:
            output = args.weak_current_output or Path("weak_current_source.md")
            source_text = build_weak_current_source(
                args.build_weak_current_source,
                output,
                args.stage1_receipt,
            )
            receipt = args.stage1_receipt or output.with_name("stage1_receipt.json")
            print(
                f"PASS: weak-current source created | chars={len(source_text)} "
                f"output={output} receipt={receipt}"
            )
            return 0
        if args.candidate_view is None:
            raise ValueError("candidate_view is required")
        data = load_json(args.candidate_view)
        dossier = build_dossier(data)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(dossier, encoding="utf-8", newline="\n")
        batch_count = 0
        if args.screening_dir:
            manifest = prepare_screening_batches(
                data,
                args.screening_dir,
                max_groups=args.max_screening_groups,
                max_chars=args.max_screening_chars,
            )
            batch_count = manifest["batch_count"]
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1
    print(
        f"PASS: wrote {args.output} | chars={len(dossier)} "
        f"groups={len(data.get('evidence_groups', []))} screening_batches={batch_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
