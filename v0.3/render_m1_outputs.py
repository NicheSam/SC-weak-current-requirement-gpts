#!/usr/bin/env python3
"""Render the three M1 deliverables from one human-readable requirements master."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
import hashlib
import html
import json
import math
from pathlib import Path
import re
import zipfile

REQ_RE = re.compile(r"^- \[(REQ-M1-\d{4})\]\s+(.+)$")
REV_RE = re.compile(r"^- \[(REV-M1-\d{4})\]\s+(.+)$")
CTX_RE = re.compile(r"^- \[(CTX-M1-\d{4})\]\s+(.+)$")
META_RE = re.compile(r"^\s{2,}- ([^：:]+)[：:]\s*(.*)$")
TOP_META_RE = re.compile(r"^- ([^：:]+)[：:]\s*(.*)$")
PDF_PAGE_RE = re.compile(r"PDF\s*(\d+)", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"\{\{.+?\}\}|<待填|TODO", re.IGNORECASE)
BAD_BOILERPLATE = (
    "依來源規格納入",
    "未辨識出明示跨系統協作",
    "統包商應確認涵蓋範圍、供電及介面責任",
)


@dataclass
class Requirement:
    requirement_id: str
    text: str
    system: str
    group: str
    space: str = ""
    status: str = ""
    source: str = ""
    quote: str = ""

    @property
    def pdf_pages(self) -> list[int]:
        return [int(value) for value in PDF_PAGE_RE.findall(self.source)]


@dataclass
class Review:
    review_id: str
    question: str
    impact: str = ""
    reviewer: str = ""
    source: str = ""
    quote: str = ""


@dataclass
class ContextItem:
    context_id: str
    text: str
    reason: str = ""
    source: str = ""


@dataclass
class SystemGuidance:
    summary: str = ""
    design_focus: str = ""
    interfaces: str = ""
    deliverables: str = ""


@dataclass
class TopicGuidance:
    summary: str = ""
    design_focus: str = ""
    deliverables: str = ""


@dataclass
class MasterDocument:
    project_name: str = "弱電需求圖譜"
    source_file: str = ""
    source_sha256: str = ""
    generated_date: str = ""
    summary: list[str] = field(default_factory=list)
    requirements: list[Requirement] = field(default_factory=list)
    reviews: list[Review] = field(default_factory=list)
    context_items: list[ContextItem] = field(default_factory=list)
    system_guidance: dict[str, SystemGuidance] = field(default_factory=dict)
    topic_guidance: dict[tuple[str, str], TopicGuidance] = field(default_factory=dict)


def clean(value: str) -> str:
    return " ".join(value.strip().split())


def parse_master(markdown: str) -> MasterDocument:
    document = MasterDocument()
    section = ""
    system = ""
    group = ""
    current: Requirement | Review | ContextItem | None = None
    for raw in markdown.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# ") and not stripped.startswith("## "):
            document.project_name = clean(stripped[2:].split("|", 1)[0])
            continue
        if stripped.startswith("## "):
            section = clean(stripped[3:])
            system = ""
            group = ""
            current = None
            continue
        if section == "需求樹" and stripped.startswith("### ") and not stripped.startswith("#### "):
            system = clean(stripped[4:])
            group = ""
            current = None
            document.system_guidance.setdefault(system, SystemGuidance())
            continue
        if section == "需求樹" and stripped.startswith("#### "):
            group = clean(stripped[5:])
            current = None
            document.topic_guidance.setdefault((system, group), TopicGuidance())
            continue

        tree_meta = TOP_META_RE.match(stripped)
        if section == "需求樹" and current is None and tree_meta:
            label, value = clean(tree_meta.group(1)), clean(tree_meta.group(2))
            if group:
                guidance = document.topic_guidance.setdefault((system, group), TopicGuidance())
                mapping = {
                    "主題說明": "summary",
                    "主題設計重點": "design_focus",
                    "主題圖說／文件": "deliverables",
                }
            else:
                guidance = document.system_guidance.setdefault(system, SystemGuidance())
                mapping = {
                    "系統摘要": "summary",
                    "系統設計重點": "design_focus",
                    "主要介面": "interfaces",
                    "主要圖說／文件": "deliverables",
                }
            if label in mapping:
                setattr(guidance, mapping[label], value)
                continue

        req_match = REQ_RE.match(stripped)
        if section == "需求樹" and req_match:
            current = Requirement(req_match.group(1), clean(req_match.group(2)), system, group)
            document.requirements.append(current)
            continue
        rev_match = REV_RE.match(stripped)
        if section == "需要人工確認" and rev_match:
            current = Review(rev_match.group(1), clean(rev_match.group(2)))
            document.reviews.append(current)
            continue
        ctx_match = CTX_RE.match(stripped)
        if section == "背景與排除紀錄" and ctx_match:
            current = ContextItem(ctx_match.group(1), clean(ctx_match.group(2)))
            document.context_items.append(current)
            continue

        meta_match = META_RE.match(line)
        if meta_match and current is not None:
            label, value = clean(meta_match.group(1)), clean(meta_match.group(2))
            if isinstance(current, Requirement):
                mapping = {"空間": "space", "狀態": "status", "來源": "source", "原文": "quote"}
            elif isinstance(current, Review):
                mapping = {"影響": "impact", "建議確認": "reviewer", "來源": "source", "原文": "quote"}
            else:
                mapping = {"理由": "reason", "來源": "source"}
            if label in mapping:
                setattr(current, mapping[label], value)
            continue

        top_match = TOP_META_RE.match(stripped)
        if top_match and section == "":
            label, value = clean(top_match.group(1)), clean(top_match.group(2))
            if label == "來源文件":
                document.source_file = value
            elif label == "來源 SHA-256":
                document.source_sha256 = value.strip("`")
            elif label == "產出日期":
                document.generated_date = value
            continue
        if section == "專案摘要" and stripped.startswith("- "):
            document.summary.append(clean(stripped[2:]))

    return document


def validate_master(document: MasterDocument, raw_markdown: str) -> None:
    errors: list[str] = []
    if PLACEHOLDER_RE.search(raw_markdown):
        errors.append("requirements master contains unresolved template placeholders")
    if not document.requirements:
        errors.append("requirements master contains no formal requirements")
    ids = [item.requirement_id for item in document.requirements]
    if len(ids) != len(set(ids)):
        errors.append("requirement IDs are not unique")
    normalized_texts: set[str] = set()
    for item in document.requirements:
        location = item.requirement_id
        if not item.system or not item.group:
            errors.append(f"{location} is missing system/group hierarchy")
        if not item.space:
            errors.append(f"{location} is missing space")
        if item.status not in {"來源明示", "跨章整合", "需人工確認"}:
            errors.append(f"{location} has invalid status: {item.status or 'empty'}")
        if not item.source or not item.pdf_pages:
            errors.append(f"{location} is missing a PDF page source")
        if len(item.quote) < 4:
            errors.append(f"{location} is missing a readable source quote")
        if any(phrase in item.text for phrase in BAD_BOILERPLATE):
            errors.append(f"{location} uses prohibited boilerplate instead of a requirement")
        key = re.sub(r"\W+", "", item.text).lower()
        if key in normalized_texts:
            errors.append(f"{location} duplicates another requirement text")
        normalized_texts.add(key)
    grouped: dict[str, list[Requirement]] = defaultdict(list)
    for item in document.requirements:
        grouped[item.system].append(item)
    for system, items in grouped.items():
        guidance = document.system_guidance.get(system, SystemGuidance())
        if len(guidance.summary) < 12:
            errors.append(f"system {system!r} is missing a readable system summary")
        if len(guidance.design_focus) < 12:
            errors.append(f"system {system!r} is missing readable design focus")
        if len(guidance.deliverables) < 4:
            errors.append(f"system {system!r} is missing likely drawings/documents")
        group_names = {item.group for item in items}
        if len(items) >= 5 and len(group_names) == len(items):
            errors.append(f"system {system!r} creates a private topic for every requirement")
        for group_name in group_names:
            topic = document.topic_guidance.get((system, group_name), TopicGuidance())
            if len(topic.summary) < 8:
                errors.append(f"topic {system!r} / {group_name!r} is missing a readable topic summary")
            if len(topic.design_focus) < 8:
                errors.append(f"topic {system!r} / {group_name!r} is missing readable design focus")
    unique_topics = {(item.system, item.group) for item in document.requirements}
    if len(document.requirements) >= 20 and len(unique_topics) > max(12, math.ceil(len(document.requirements) * 0.75)):
        errors.append("topic reuse is too low: the requirement tree is fragmented into mostly single-item topics")
    review_ids = [item.review_id for item in document.reviews]
    if len(review_ids) != len(set(review_ids)):
        errors.append("review IDs are not unique")
    for item in document.reviews:
        if not item.impact or not item.reviewer or not item.source or not item.quote:
            errors.append(f"{item.review_id} is missing impact/reviewer/source/quote")
    if errors:
        raise ValueError("master validation failed:\n- " + "\n- ".join(errors))


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_source_gate(
    document: MasterDocument,
    weak_current_source_path: Path,
    stage1_receipt_path: Path,
) -> dict[str, object]:
    """Apply only lightweight traceability checks; semantic quality remains AI-owned."""
    if not weak_current_source_path.is_file():
        raise ValueError("source check failed: weak_current_source.md is required")
    source_text = weak_current_source_path.read_text(encoding="utf-8")
    if "# 弱電來源包" not in source_text:
        raise ValueError("source check failed: weak_current_source.md header is missing")
    name_match = re.search(r"^- 來源文件：(.+)$", source_text, re.MULTILINE)
    sha_match = re.search(r"^- 來源 SHA-256：`?([0-9a-fA-F]{64})`?$", source_text, re.MULTILINE)
    batch_match = re.search(r"^- 已閱讀批次：(\d+)\s*/\s*(\d+)$", source_text, re.MULTILINE)
    if not name_match or not sha_match or not batch_match:
        raise ValueError("source check failed: weak-current source metadata is incomplete")
    completed_batches, total_batches = map(int, batch_match.groups())
    if total_batches < 1 or completed_batches != total_batches:
        raise ValueError("source check failed: not every source batch was screened")
    marker_count = len(re.findall(r"<!--\s*screened:SB-\d{3}\s*-->", source_text))
    if marker_count != total_batches:
        raise ValueError("source check failed: screened batch markers do not match the batch count")
    source_name = clean(name_match.group(1))
    source_sha256 = sha_match.group(1).lower()
    if Path(document.source_file).name.casefold() != Path(source_name).name.casefold():
        raise ValueError("source check failed: requirements master source file does not match")
    if document.source_sha256.lower() != source_sha256:
        raise ValueError("source check failed: requirements master SHA-256 does not match")
    if not stage1_receipt_path.is_file():
        raise ValueError("source check failed: stage1_receipt.json is required")
    try:
        receipt = json.loads(stage1_receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"source check failed: invalid stage1 receipt: {exc}") from exc
    required = {
        "schema_version",
        "stage",
        "source_name",
        "source_sha256",
        "pdf_page_count",
        "extraction_batch_count",
        "screening_batch_count",
        "screened_batch_ids",
        "screened_evidence_group_count",
        "weak_current_source_sha256",
    }
    if not required.issubset(receipt):
        raise ValueError("source check failed: stage1 receipt metadata is incomplete")
    if receipt["stage"] != "weak_current_source_complete":
        raise ValueError("source check failed: stage1 receipt is not complete")
    if Path(str(receipt["source_name"])).name.casefold() != Path(source_name).name.casefold():
        raise ValueError("source check failed: stage1 receipt source file does not match")
    if str(receipt["source_sha256"]).lower() != source_sha256:
        raise ValueError("source check failed: stage1 receipt source SHA-256 does not match")
    if str(receipt["weak_current_source_sha256"]).lower() != sha256_path(weak_current_source_path):
        raise ValueError("source check failed: weak-current source hash does not match stage1 receipt")
    receipt_batch_count = int(receipt["screening_batch_count"])
    receipt_batch_ids = [str(value) for value in receipt["screened_batch_ids"]]
    source_batch_ids = re.findall(r"<!--\s*screened:(SB-\d{3})\s*-->", source_text)
    if receipt_batch_count != total_batches or receipt_batch_ids != source_batch_ids:
        raise ValueError("source check failed: stage1 receipt batch coverage does not match source package")
    if int(receipt["pdf_page_count"]) < 1 or int(receipt["extraction_batch_count"]) < 1:
        raise ValueError("source check failed: stage1 receipt has invalid PDF coverage")
    if int(receipt["screened_evidence_group_count"]) < 1:
        raise ValueError("source check failed: stage1 receipt has no screened evidence groups")
    return receipt


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def slug(value: str) -> str:
    digest = sum((index + 1) * ord(char) for index, char in enumerate(value)) % 1_000_003
    return f"sys-{digest:06d}"


def build_tree_html(document: MasterDocument) -> str:
    grouped: dict[str, dict[str, list[Requirement]]] = defaultdict(lambda: defaultdict(list))
    for item in document.requirements:
        grouped[item.system][item.group].append(item)
    chunks: list[str] = [
        '<div class="mindmap-root">',
        f'<div class="tree-node level-1">{esc(document.project_name)}</div>',
        '<section class="tree-category">',
        '<div class="category-heading"><span class="tree-node level-1">弱電需求</span>'
        f'<span class="mini-count">{len(grouped)} 系統</span></div>',
        '<div class="tree-system-list">',
    ]
    for system_index, (system, groups) in enumerate(grouped.items()):
        system_count = sum(len(items) for items in groups.values())
        guidance = document.system_guidance[system]
        expanded = system_index == 0
        chunks.append(
            f'<section class="system-block tree-system" data-system="{esc(system)}">'
            f'<button class="system-toggle" type="button" aria-expanded="{str(expanded).lower()}" aria-controls="{slug(system)}">'
            f'<span class="system-title tree-node level-2">{esc(system)}</span><span class="system-actions"><span class="count-badge">{system_count} 筆</span>'
            f'<span class="toggle-marker" aria-hidden="true"></span></span></button>'
            f'<div class="system-groups" id="{slug(system)}"{("" if expanded else " hidden")}>'
            f'<p class="system-summary">{esc(guidance.summary)}</p>'
        )
        for group, items in groups.items():
            topic = document.topic_guidance[(system, group)]
            chunks.append(
                '<section class="group-block">'
                f'<div class="group-heading"><div><h3 class="tree-node level-3">{esc(group)}</h3><p>{esc(topic.summary)}</p></div>'
                f'<span class="group-count">{len(items)} 筆</span></div><div class="requirement-list">'
            )
            for item in items:
                chunks.append(
                    f'<button type="button" class="requirement-row" data-id="{esc(item.requirement_id)}" '
                    f'data-system="{esc(item.system)}" data-space="{esc(item.space)}" data-status="{esc(item.status)}">'
                    f'<span class="requirement-text tree-node level-4">{esc(item.text)}</span>'
                    f'<span class="row-meta tree-node level-5"><span>{esc(item.requirement_id)}</span><span>{esc(item.space)}</span>'
                    f'<span class="status status-{esc(item.status)}">{esc(item.status)}</span></span></button>'
                )
            chunks.append("</div></section>")
        chunks.append("</div></section>")
    chunks.extend(["</div></section></div>"])
    return "".join(chunks)


def build_options(values: list[str], label: str) -> str:
    options = [f'<option value="">全部{esc(label)}</option>']
    options.extend(f'<option value="{esc(value)}">{esc(value)}</option>' for value in sorted(set(values)))
    return "".join(options)


def split_space_tokens(value: str) -> list[str]:
    return [clean(token) for token in re.split(r"[／、,，]+", value) if clean(token)]


def build_summary_html(items: list[str]) -> str:
    if not items:
        return '<p class="empty-state">來源未形成額外摘要；請從需求樹開始閱讀。</p>'
    return '<ul class="summary-list">' + "".join(f'<li>{esc(item)}</li>' for item in items) + "</ul>"


def build_reviews_html(items: list[Review]) -> str:
    if not items:
        return '<p class="empty-state">目前沒有需人工確認事項。</p>'
    return "".join(
        '<article class="review-card">'
        f'<h3>{esc(item.question)}</h3><p><strong>影響</strong>{esc(item.impact)}</p>'
        f'<p><strong>建議確認</strong>{esc(item.reviewer)}</p><p><strong>來源</strong>{esc(item.source)}</p>'
        f'<blockquote>{esc(item.quote)}</blockquote></article>'
        for item in items
    )


def build_context_html(items: list[ContextItem]) -> str:
    if not items:
        return '<p class="empty-state">沒有需要額外列示的背景或排除紀錄。</p>'
    return "".join(
        '<article class="context-card">'
        f'<h3>{esc(item.text)}</h3><p><strong>理由</strong>{esc(item.reason)}</p>'
        f'<p><strong>來源</strong>{esc(item.source)}</p></article>'
        for item in items
    )


def render_html(document: MasterDocument, template: str) -> str:
    details = [
        {
            "id": item.requirement_id,
            "text": item.text,
            "system": item.system,
            "group": item.group,
            "space": item.space,
            "status": item.status,
            "source": item.source,
            "quote": item.quote,
            "space_tokens": split_space_tokens(item.space),
            "system_summary": document.system_guidance[item.system].summary,
            "system_design_focus": document.system_guidance[item.system].design_focus,
            "system_interfaces": document.system_guidance[item.system].interfaces,
            "system_deliverables": document.system_guidance[item.system].deliverables,
            "topic_summary": document.topic_guidance[(item.system, item.group)].summary,
            "topic_design_focus": document.topic_guidance[(item.system, item.group)].design_focus,
            "topic_deliverables": document.topic_guidance[(item.system, item.group)].deliverables,
        }
        for item in document.requirements
    ]
    space_options = [token for item in document.requirements for token in split_space_tokens(item.space)]
    replacements = {
        "{{PROJECT_NAME}}": esc(document.project_name),
        "{{SOURCE_NAME}}": esc(document.source_file or "未標示"),
        "{{GENERATED_DATE}}": esc(document.generated_date or date.today().isoformat()),
        "{{REQUIREMENT_COUNT}}": str(len(document.requirements)),
        "{{SYSTEM_COUNT}}": str(len(set(item.system for item in document.requirements))),
        "{{REVIEW_COUNT}}": str(len(document.reviews)),
        "{{SYSTEM_OPTIONS}}": build_options([item.system for item in document.requirements], "系統"),
        "{{SPACE_OPTIONS}}": build_options(space_options, "空間"),
        "{{STATUS_OPTIONS}}": build_options([item.status for item in document.requirements], "狀態"),
        "{{TREE_HTML}}": build_tree_html(document),
        "{{DETAILS_JSON}}": json.dumps(details, ensure_ascii=False).replace("</", "<\\/"),
        "{{SUMMARY_HTML}}": build_summary_html(document.summary),
        "{{REVIEWS_HTML}}": build_reviews_html(document.reviews),
        "{{CONTEXT_HTML}}": build_context_html(document.context_items),
    }
    output = template
    for marker, value in replacements.items():
        output = output.replace(marker, value)
    unresolved = re.findall(r"\{\{[A-Z_]+\}\}", output)
    if unresolved:
        raise ValueError(f"template contains unresolved markers: {sorted(set(unresolved))}")
    return output


def render_xmind(document: MasterDocument) -> str:
    grouped: dict[str, dict[str, list[Requirement]]] = defaultdict(lambda: defaultdict(list))
    for item in document.requirements:
        grouped[item.system][item.group].append(item)
    lines = [f"# {document.project_name}", "", "## 需求樹", ""]
    for system, groups in grouped.items():
        lines.extend([f"### {system}", ""])
        for group, items in groups.items():
            lines.extend([f"#### {group}", ""])
            lines.extend(f"- {item.text}" for item in items)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_handoff(document: MasterDocument, stage1_receipt: dict[str, object] | None = None) -> str:
    system_counts = Counter(item.system for item in document.requirements)
    lines = [
        f"# {document.project_name} | 弱電需求交接",
        "",
        f"- 來源文件：{document.source_file or '未標示'}",
        f"- 正式需求：{len(document.requirements)} 筆",
        f"- 涉及系統：{len(system_counts)} 個",
        f"- 需人工確認：{len(document.reviews)} 筆",
    ]
    if stage1_receipt:
        lines.extend([
            f"- 來源處理：PDF {stage1_receipt['pdf_page_count']} 頁；"
            f"來源篩選 {stage1_receipt['screening_batch_count']} / {stage1_receipt['screening_batch_count']} 批完成",
            f"- 第一階段來源包 SHA-256：`{stage1_receipt['weak_current_source_sha256']}`",
        ])
    lines.extend([
        "",
        "## 專案摘要",
        "",
    ])
    lines.extend(f"- {item}" for item in document.summary)
    lines.extend(["", "## 系統需求摘要", ""])
    for system in system_counts:
        lines.extend([f"### {system}（{system_counts[system]} 筆）", ""])
        guidance = document.system_guidance[system]
        lines.extend([
            f"- 系統摘要：{guidance.summary}",
            f"- 設計重點：{guidance.design_focus}",
            f"- 主要介面：{guidance.interfaces or '來源未明示額外介面'}",
            f"- 圖說／文件：{guidance.deliverables}",
            "",
        ])
        groups: dict[str, list[Requirement]] = defaultdict(list)
        for item in (req for req in document.requirements if req.system == system):
            groups[item.group].append(item)
        for group, items in groups.items():
            topic = document.topic_guidance[(system, group)]
            lines.extend([f"#### {group}", "", f"- 主題說明：{topic.summary}", f"- 主題設計重點：{topic.design_focus}"])
            if topic.deliverables:
                lines.append(f"- 主題圖說／文件：{topic.deliverables}")
            lines.append("")
            for item in items:
                lines.append(f"- {item.text}（{item.source}）")
            lines.append("")
        lines.append("")
    lines.extend(["## 需要人工確認", ""])
    if document.reviews:
        for item in document.reviews:
            lines.extend([
                f"### {item.review_id} | {item.question}",
                "",
                f"- 影響：{item.impact}",
                f"- 建議確認：{item.reviewer}",
                f"- 來源：{item.source}",
                f"- 原文：{item.quote}",
                "",
            ])
    else:
        lines.extend(["- 無。", ""])
    lines.extend(["## 背景與排除紀錄", ""])
    if document.context_items:
        for item in document.context_items:
            lines.append(f"- {item.text}；理由：{item.reason}；來源：{item.source}")
    else:
        lines.append("- 無需額外列示。");
    return "\n".join(lines).rstrip() + "\n"


def render_outputs(
    master_path: Path,
    template_path: Path,
    output_dir: Path,
    weak_current_source_path: Path,
    stage1_receipt_path: Path,
) -> list[Path]:
    markdown = master_path.read_text(encoding="utf-8")
    document = parse_master(markdown)
    validate_master(document, markdown)
    stage1_receipt = validate_source_gate(document, weak_current_source_path, stage1_receipt_path)
    template = template_path.read_text(encoding="utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "demand_map.html": render_html(document, template),
        "to_xmind.md": render_xmind(document),
        "todo_handoff.md": render_handoff(document, stage1_receipt),
    }
    paths: list[Path] = []
    for name, content in outputs.items():
        path = output_dir / name
        path.write_text(content, encoding="utf-8", newline="\n")
        paths.append(path)
    zip_path = output_dir / "m1_outputs.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, arcname=path.name)
    paths.append(zip_path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Render M1 outputs from requirements_master.md")
    parser.add_argument("master", type=Path)
    parser.add_argument("template", type=Path, nargs="?", default=Path("weak_current_html_template.html"))
    parser.add_argument("output_dir", type=Path, nargs="?", default=Path("m1_delivery"))
    parser.add_argument("--weak-current-source", type=Path, required=True)
    parser.add_argument("--stage1-receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        outputs = render_outputs(
            args.master,
            args.template,
            args.output_dir,
            args.weak_current_source,
            args.stage1_receipt,
        )
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1
    print("PASS: " + ", ".join(str(path) for path in outputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
