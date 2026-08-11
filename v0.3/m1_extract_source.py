#!/usr/bin/env python3
"""M1 PDF-to-candidate extractor with native and image-text coverage audit."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Iterable
import unicodedata


SCHEMA_VERSION = "1.4"
WORKFLOW_VERSION = "m1-v0.6-source-dossier"
MAX_QUOTE_CHARS = 760
CHUNK_OVERLAP = 80
EVIDENCE_GROUP_MAX_CANDIDATES = 12
EVIDENCE_GROUP_MAX_CHARS = 4800
# 1.8x keeps ordinary document text legible for chi_tra OCR while cutting the
# pixel workload roughly in half versus 2.5x. Low-confidence regions still go
# to model vision, so speed is improved without silently accepting weak OCR.
VISION_RENDER_SCALE = 1.8
VISION_REGION_MAX_HEIGHT = 300.0
VISION_REGION_VERTICAL_GAP = 20.0
GPTS_TESSERACT_PATH = "/usr/bin/tesseract"
OCR_ACCEPT_CONFIDENCE = 72.0
OCR_HIGH_CONFIDENCE = 88.0
TESSERACT_REGION_TIMEOUT_SECONDS = 30

# Broad system-family vocabulary is used only to suggest a classification. It is
# intentionally free of project-specific expected answers; candidate admission
# also works from BUSINESS_CAPABILITY_TERMS when no system name is recognized.
SYSTEM_TERMS: dict[str, tuple[str, ...]] = {
    "語音與電話系統": ("電話", "語音", "分機", "pbx", "sip", "voip", "總機"),
    "資訊網路系統": ("資訊網路", "網路", "lan", "wan", "wifi", "wi-fi", "交換器", "路由器", "伺服器", "資安", "防火牆", "光纖", "fttb", "onu", "mdf", "idf"),
    "監視系統": ("監視", "cctv", "攝影機", "錄影", "nvr", "影像辨識"),
    "門禁系統": ("門禁", "讀卡", "感應卡", "電鎖", "權限管理", "出入口管制"),
    "停車管理系統": ("停車", "車道", "車輛管制", "進出管理", "出入口管理", "車位", "停管", "柵欄", "車牌", "etag", "e-tag"),
    "中央監控系統": ("中央監控", "bms", "bas", "ba系統", "圖控", "監控點", "io點", "i/o"),
    "能源管理系統": ("能源管理", "ems", "需量", "電表", "水表", "能耗", "分項用電"),
    "廣播與對講系統": ("廣播", "對講", "緊急求救", "求救鈴", "緊急電話", "intercom"),
    "電視與影音系統": ("電視", "數位電視", "共同天線", "catv", "電視插座", "影音", "投影機", "顯示器", "電子布告欄"),
    "通訊涵蓋系統": ("行動通信", "行動通訊", "行動電話", "公眾通信", "電信業者", "訊號涵蓋", "訊號改善", "室內涵蓋", "4g", "5g", "射頻", "強波", "洩波", "漏波"),
    "物聯網與資料平台": ("iot", "物聯網", "資料平台", "api", "資料庫", "資料交換", "通訊協定"),
    "弱電基礎設施": ("弱電", "弱電機房", "電信室", "資訊插座", "機櫃", "機架", "配線架", "纜線", "電纜", "同軸", "配管", "配線", "佈線"),
}

SEMANTIC_TERMS = (
    "資料", "訊號", "通訊", "傳輸", "監測", "監視", "控制", "感測", "辨識", "顯示",
    "告警", "警報", "連動", "介接", "整合", "協定", "遠端", "紀錄", "記錄", "平台",
    "回傳", "通知", "狀態", "權限", "授權", "識別", "偵測", "偵知", "涵蓋",
)
OBLIGATION_TERMS = ("應", "須", "必須", "不得", "需", "宜", "設置", "提供", "預留", "建置", "配置", "安裝")
INTERFACE_DOMAINS = ("消防", "火警", "電梯", "空調", "照明", "給排水", "泵浦", "通風", "排風")
HEADING_HINTS = ("弱電", "資訊", "通訊", "監控", "智慧建築", "系統整合", "設備規格")
TECHNICAL_CONTEXT_TERMS = (
    "系統", "設備", "主機", "線路", "管線", "纜線", "電纜", "槽架", "機房", "插座",
    "訊號", "信號", "資料", "網路", "通訊", "通信", "監測", "監視", "控制", "感測",
    "辨識", "識別", "顯示", "告警", "警報", "連動", "介面", "平台", "傳輸", "紀錄",
)
NEGATION_TERMS = ("不需", "無須", "不得", "不納入", "不包含", "排除", "免設")
CONDITION_TERMS = ("但", "惟", "除外", "除非", "若", "如有", "視", "依業主", "待確認")
GENERIC_PRESERVATION_TERMS = {
    "停車", "車道", "車位", "網路", "資料庫", "資料平台", "平台", "設備", "系統",
    "資料", "紀錄", "記錄", "控制", "整合", "介接", "監測", "監視", "顯示", "通知",
    "上傳", "下載", "儲存", "查詢", "回傳", "狀態", "權限", "授權", "交換", "同步",
    "匯入", "匯出", "連線", "傳輸", "事件", "異常", "開啟", "關閉", "啟停", "切換",
}

# These are business capabilities, not a closed equipment or project-keyword list.
# A previously unseen product or protocol can still enter the candidate pack when
# its surrounding text expresses one or more of these weak-current operations.
BUSINESS_CAPABILITY_TERMS: dict[str, tuple[str, ...]] = {
    "signal": ("訊號", "信號", "頻率", "涵蓋", "收訊", "接收", "發射", "射頻", "4g", "5g", "洩波", "漏波"),
    "data": ("資料", "數據", "紀錄", "記錄", "回傳", "上傳", "下載", "儲存", "查詢"),
    "communication": ("通訊", "通信", "傳輸", "網路", "連線", "協定", "頻寬"),
    "monitoring": ("監測", "監視", "狀態", "圖控", "趨勢", "事件"),
    "control": ("控制", "連動", "啟停", "切換", "開啟", "關閉", "觸發", "授權", "權限", "柵欄", "閘門", "電鎖"),
    "sensing": ("感測", "偵測", "偵知", "量測", "讀取", "採集"),
    "identification": ("辨識", "識別", "驗證", "認證", "判讀", "讀卡", "刷卡", "車牌"),
    "display": ("顯示", "看板", "螢幕", "指示", "播送"),
    "alarm": ("告警", "警報", "通知", "求救", "異常"),
    "integration": ("整合", "介接", "連動", "交換", "同步", "匯入", "匯出"),
    "interface": ("介面", "接點", "乾接點", "i/o", "io點", "api", "閘道"),
    "weak_current_infrastructure": ("線路", "線纜", "纜線", "電纜", "光纖", "同軸", "配線", "配管", "插座", "機櫃", "機架", "端點", "節點"),
}

# These facets are deliberately broad reading dimensions rather than a room-name
# whitelist.  The model may refine them, but the deterministic pass keeps an
# explicit source mention available for later filtering and omission review.
SPACE_FACET_TERMS: dict[str, tuple[str, ...]] = {
    "地下層": ("地下", "地下室", "地下層", "地下一層", "地下二層", "b1", "b2", "b3", "b4"),
    "停車空間": ("停車", "停車場", "停車空間", "停車區", "車道", "汽車位", "機車位", "卸貨車位"),
    "住宅單元": ("住宅單元", "住戶", "各戶", "居住單元", "客廳", "臥室", "戶內"),
    "公共空間": ("公共空間", "公共區域", "公設", "社區大廳", "門廳", "中庭", "公共廁所"),
    "管理與中控空間": ("管理室", "物管辦公室", "物管櫃台", "中央監控室", "中控室", "警衛室"),
    "機房與設備空間": ("弱電機房", "電信室", "資訊機房", "機房", "設備室", "管道間"),
    "商業與服務空間": ("商業空間", "店舖", "店鋪", "公共服務空間", "社福空間"),
    "屋頂與戶外": ("屋頂", "屋突", "露台", "戶外", "公共開放空間"),
}


@dataclass
class ExtractedPage:
    number: int
    blocks: list[str]
    block_boxes: list[tuple[float, float, float, float]] = field(default_factory=list)
    visual_regions: list[dict[str, object]] = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0
    visual_audit_available: bool = True

    @property
    def text(self) -> str:
        return "\n".join(self.blocks)


def rect_area(rect: tuple[float, float, float, float]) -> float:
    return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])


def overlap_ratio(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    intersection = (
        max(first[0], second[0]),
        max(first[1], second[1]),
        min(first[2], second[2]),
        min(first[3], second[3]),
    )
    area = rect_area(intersection)
    return area / rect_area(first) if rect_area(first) else 0.0


def union_rects(rects: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (
        min(rect[0] for rect in rects),
        min(rect[1] for rect in rects),
        max(rect[2] for rect in rects),
        max(rect[3] for rect in rects),
    )


def expand_rect(
    rect: tuple[float, float, float, float],
    width: float,
    height: float,
    padding: float = 7.0,
) -> tuple[float, float, float, float]:
    return (
        max(0.0, rect[0] - padding),
        max(0.0, rect[1] - padding),
        min(width, rect[2] + padding),
        min(height, rect[3] + padding),
    )


def is_text_like_image(info: dict[str, object], page_height: float) -> bool:
    bbox = tuple(float(value) for value in info.get("bbox", (0, 0, 0, 0)))
    if len(bbox) != 4:
        return False
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    pixel_width = int(info.get("width", 0) or 0)
    pixel_height = int(info.get("height", 0) or 0)
    if bbox[1] < 70.0 or bbox[3] > page_height - 65.0:
        return False
    return 6.0 <= height <= 24.0 and width >= 6.0 and pixel_width >= 8 and 16 <= pixel_height <= 80


def split_region_group(
    rects: list[tuple[float, float, float, float]],
) -> list[list[tuple[float, float, float, float]]]:
    chunks: list[list[tuple[float, float, float, float]]] = []
    current: list[tuple[float, float, float, float]] = []
    for rect in sorted(rects, key=lambda value: (value[1], value[0])):
        if current and rect[3] - current[0][1] > VISION_REGION_MAX_HEIGHT:
            chunks.append(current)
            current = []
        current.append(rect)
    if current:
        chunks.append(current)
    return chunks


def detect_visual_regions(
    page_number: int,
    page_width: float,
    page_height: float,
    image_info: list[dict[str, object]],
    native_boxes: list[tuple[float, float, float, float]],
) -> list[dict[str, object]]:
    candidates: list[tuple[float, float, float, float]] = []
    for info in image_info:
        if not is_text_like_image(info, page_height):
            continue
        bbox = tuple(float(value) for value in info["bbox"])
        if any(overlap_ratio(bbox, native_box) >= 0.45 for native_box in native_boxes):
            continue
        candidates.append(bbox)
    groups: list[list[tuple[float, float, float, float]]] = []
    for bbox in sorted(candidates, key=lambda value: (value[1], value[0])):
        if not groups:
            groups.append([bbox])
            continue
        current_rect = union_rects(groups[-1])
        if bbox[1] - current_rect[3] <= VISION_REGION_VERTICAL_GAP:
            groups[-1].append(bbox)
        else:
            groups.append([bbox])

    regions: list[dict[str, object]] = []
    for group in groups:
        for chunk in split_region_group(group):
            union = union_rects(chunk)
            if len(chunk) == 1 and union[2] - union[0] < 80.0:
                continue
            regions.append(
                {
                    "region_id": f"VR-P{page_number:04d}-{len(regions) + 1:03d}",
                    "pdf_page": page_number,
                    "bbox": [round(value, 2) for value in expand_rect(union, page_width, page_height)],
                    "image_count": len(chunk),
                    "reason_code": "image_text_without_native_layer",
                    "status": "pending",
                    "transcribed_text": "",
                    "confidence": "unknown",
                }
            )

    page_area = max(1.0, page_width * page_height)
    large_images = []
    for info in image_info:
        bbox = tuple(float(value) for value in info.get("bbox", (0, 0, 0, 0)))
        if len(bbox) != 4:
            continue
        if rect_area(bbox) / page_area >= 0.35 and int(info.get("width", 0) or 0) >= 500:
            large_images.append(bbox)
    if large_images:
        content_top = 70.0
        content_bottom = max(content_top, page_height - 65.0)
        band_top = content_top
        while band_top < content_bottom:
            band_bottom = min(content_bottom, band_top + VISION_REGION_MAX_HEIGHT)
            band = (0.0, band_top, page_width, band_bottom)
            native_centers = sum(
                1
                for box in native_boxes
                if band_top <= (box[1] + box[3]) / 2.0 <= band_bottom
            )
            overlaps_existing = any(
                overlap_ratio(tuple(float(value) for value in region["bbox"]), band) >= 0.45
                for region in regions
            )
            if native_centers < 3 and not overlaps_existing:
                regions.append(
                    {
                        "region_id": f"VR-P{page_number:04d}-{len(regions) + 1:03d}",
                        "pdf_page": page_number,
                        "bbox": [round(value, 2) for value in band],
                        "image_count": 1,
                        "reason_code": "image_text_without_native_layer",
                        "status": "pending",
                        "transcribed_text": "",
                        "confidence": "unknown",
                    }
                )
            band_top = band_bottom
    if len(regions) <= 1:
        return regions
    combined = union_rects([
        tuple(float(value) for value in region["bbox"])
        for region in regions
    ])
    return [{
        "region_id": f"VR-P{page_number:04d}-001",
        "pdf_page": page_number,
        "bbox": [round(value, 2) for value in combined],
        "image_count": sum(int(region.get("image_count", 0) or 0) for region in regions),
        "reason_code": "page_image_text_without_native_layer",
        "status": "pending",
        "transcribed_text": "",
        "confidence": "unknown",
    }]


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_text(value: str) -> str:
    value = value.replace("\u00a0", " ").replace("\u3000", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def semantic_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    return re.sub(r"[\s\-‐‑‒–—―－_/\\.]+", "", normalized)


def normalized_line(value: str) -> str:
    return semantic_key(value)


def matched_obligation_terms(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text)
    searchable = semantic_key(text)
    matches: list[str] = []
    for term in OBLIGATION_TERMS:
        if term == "需":
            found = re.search(r"需(?!求)", normalized) is not None
        elif term == "應":
            found = re.search(r"(?<!對)應(?!用)", normalized) is not None
        else:
            found = semantic_key(term) in searchable
        if found:
            matches.append(term)
    return matches


def is_navigation_chunk(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return True
    if re.fullmatch(r"[\d\s\-–—_/]+", stripped):
        return True
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    navigation_lines = sum(
        1
        for line in lines
        if re.search(r"(?:\.{4,}|…{2,}|·{4,})\s*\d*\s*$", line)
    )
    return len(lines) >= 2 and navigation_lines / len(lines) >= 0.6


def is_margin_noise_line(value: str) -> bool:
    normalized = normalized_line(value)
    if not 2 <= len(normalized) <= 45:
        return False
    if matched_obligation_terms(value) or any(semantic_key(term) in normalized for term in SEMANTIC_TERMS):
        return False
    if find_system_hints(value)[0]:
        return False
    return True


def extract_with_fitz(path: Path) -> list[ExtractedPage]:
    import fitz  # type: ignore

    document = fitz.open(path)
    pages: list[ExtractedPage] = []
    try:
        for number, page in enumerate(document, start=1):
            raw_blocks = [block for block in page.get_text("blocks", sort=True) if int(block[6]) == 0]
            blocks: list[str] = []
            block_boxes: list[tuple[float, float, float, float]] = []
            for block in raw_blocks:
                value = clean_text(str(block[4]))
                if not value:
                    continue
                blocks.append(value)
                block_boxes.append(tuple(float(coordinate) for coordinate in block[:4]))
            page_width = float(page.rect.width)
            page_height = float(page.rect.height)
            image_info = [dict(item) for item in page.get_image_info(xrefs=True)]
            pages.append(
                ExtractedPage(
                    number=number,
                    blocks=blocks,
                    block_boxes=block_boxes,
                    visual_regions=detect_visual_regions(
                        number,
                        page_width,
                        page_height,
                        image_info,
                        block_boxes,
                    ),
                    width=page_width,
                    height=page_height,
                )
            )
    finally:
        document.close()
    return pages


def extract_with_pypdf(path: Path) -> list[ExtractedPage]:
    from pypdf import PdfReader  # type: ignore

    reader = PdfReader(str(path))
    return [
        ExtractedPage(
            number=number,
            blocks=[text] if (text := clean_text(page.extract_text() or "")) else [],
            visual_audit_available=False,
        )
        for number, page in enumerate(reader.pages, start=1)
    ]


def extract_pages(path: Path) -> tuple[list[ExtractedPage], str]:
    try:
        return extract_with_fitz(path), "pymupdf"
    except Exception as fitz_error:
        try:
            return extract_with_pypdf(path), "pypdf"
        except Exception as pypdf_error:
            raise RuntimeError(f"PDF extraction failed: PyMuPDF={fitz_error}; pypdf={pypdf_error}") from pypdf_error


def repeated_margin_lines(pages: list[ExtractedPage]) -> set[str]:
    counter: Counter[str] = Counter()
    for page in pages:
        lines = [line.strip() for line in page.text.splitlines() if line.strip()]
        samples = lines[:3] + lines[-3:]
        counter.update({normalized_line(line) for line in samples if is_margin_noise_line(line)})
    threshold = max(3, int(len(pages) * 0.15))
    return {line for line, count in counter.items() if count >= threshold}


def remove_margin_noise(page: ExtractedPage, repeated: set[str]) -> ExtractedPage:
    cleaned_blocks: list[str] = []
    cleaned_boxes: list[tuple[float, float, float, float]] = []
    for index, block in enumerate(page.blocks):
        lines = [line for line in block.splitlines() if normalized_line(line) not in repeated]
        value = clean_text("\n".join(lines))
        if value:
            cleaned_blocks.append(value)
            if index < len(page.block_boxes):
                cleaned_boxes.append(page.block_boxes[index])
    return ExtractedPage(
        number=page.number,
        blocks=cleaned_blocks,
        block_boxes=cleaned_boxes,
        visual_regions=page.visual_regions,
        width=page.width,
        height=page.height,
        visual_audit_available=page.visual_audit_available,
    )


def tesseract_capability() -> dict[str, object]:
    confirmed_gpts_path = Path(GPTS_TESSERACT_PATH)
    executable = str(confirmed_gpts_path) if confirmed_gpts_path.is_file() else shutil.which("tesseract")
    if not executable:
        return {
            "available": False,
            "engine": "none",
            "languages": [],
            "reason": "confirmed_gpts_tesseract_missing",
            "expected_executable": GPTS_TESSERACT_PATH,
        }
    try:
        language_probe = subprocess.run(
            [executable, "--list-langs"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        version_probe = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "engine": "none", "languages": [], "reason": f"tesseract_probe_failed:{exc}"}
    languages = [line.strip() for line in language_probe.stdout.splitlines()[1:] if line.strip()]
    available = language_probe.returncode == 0 and {"chi_tra", "eng"}.issubset(languages)
    version = version_probe.stdout.splitlines()[0].strip() if version_probe.stdout.strip() else "unknown"
    return {
        "available": available,
        "engine": "tesseract" if available else "none",
        "languages": languages,
        "language_spec": "chi_tra+eng",
        "version": version,
        "reason": "confirmed_gpts_runtime_ready" if available else "required_language_missing",
        "executable": executable,
    }


def render_visual_regions(
    pdf_path: Path,
    regions: list[dict[str, object]],
    output_dir: Path,
) -> dict[str, object]:
    import fitz  # type: ignore

    output_dir.mkdir(parents=True, exist_ok=True)
    document = fitz.open(pdf_path)
    try:
        for region in regions:
            page_number = int(region.get("source_local_page", region["pdf_page"]))
            bbox = [float(value) for value in region["bbox"]]
            crop_path = output_dir / f"{region['region_id']}.png"
            pixmap = document[page_number - 1].get_pixmap(
                matrix=fitz.Matrix(VISION_RENDER_SCALE, VISION_RENDER_SCALE),
                clip=fitz.Rect(*bbox),
                alpha=False,
            )
            pixmap.save(crop_path)
            region["crop_file"] = crop_path.name
    finally:
        document.close()

    manifest = {
        "schema_version": "1.0",
        "source_pdf": pdf_path.name,
        "region_count": len(regions),
        "instructions": (
            "Tesseract chi_tra+eng is the primary OCR path. Inspect only regions left pending after OCR failure "
            "or low confidence. Compare the crop with ocr_draft when present, then return corrected complete "
            "source text without semantic filtering."
        ),
        "regions": [
            {
                "region_id": region["region_id"],
                "pdf_page": region["pdf_page"],
                "bbox": region["bbox"],
                "crop_file": region.get("crop_file", ""),
                "reason_code": region["reason_code"],
            }
            for region in regions
        ],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def ocr_text_usable(text: str, image_count: int = 0) -> bool:
    compact = re.sub(r"\s+", "", text)
    minimum_length = max(4, image_count * 2)
    return len(compact) >= minimum_length and bool(re.search(r"[\u3400-\u9fffA-Za-z0-9]", compact))


def normalize_ocr_spacing(text: str) -> str:
    value = clean_text(text)
    value = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", value)
    value = re.sub(r"\s+([，。；：！？、）】》])", r"\1", value)
    value = re.sub(r"([（【《])\s+", r"\1", value)
    return value


def parse_tesseract_tsv(tsv_text: str) -> tuple[str, float | None]:
    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
    lines: dict[tuple[str, str, str, str], list[str]] = {}
    weighted_total = 0.0
    weighted_chars = 0
    for row in reader:
        token = str(row.get("text", "")).strip()
        if str(row.get("level", "")) != "5" or not token:
            continue
        try:
            confidence = float(str(row.get("conf", "-1")))
        except ValueError:
            confidence = -1.0
        if confidence < 0:
            continue
        key = tuple(str(row.get(field, "")) for field in ("page_num", "block_num", "par_num", "line_num"))
        lines.setdefault(key, []).append(token)
        weight = max(1, len(re.sub(r"\s+", "", token)))
        weighted_total += confidence * weight
        weighted_chars += weight
    text = "\n".join(" ".join(tokens) for tokens in lines.values())
    mean_confidence = weighted_total / weighted_chars if weighted_chars else None
    return normalize_ocr_spacing(text), mean_confidence


def run_tesseract_regions(
    visual_dir: Path,
    regions: list[dict[str, object]],
    capability: dict[str, object],
) -> dict[str, object]:
    executable = str(capability.get("executable", ""))
    records: list[dict[str, object]] = []
    if not capability.get("available") or not executable:
        return {"schema_version": "1.0", "engine": "none", "regions": records}
    def read_region(region: dict[str, object]) -> dict[str, object]:
        crop_path = visual_dir / str(region.get("crop_file", ""))
        failure_reason = ""
        try:
            completed = subprocess.run(
                [executable, str(crop_path), "stdout", "-l", "chi_tra+eng", "--psm", "6", "tsv"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TESSERACT_REGION_TIMEOUT_SECONDS,
                check=False,
            )
            text, mean_confidence = parse_tesseract_tsv(completed.stdout)
        except subprocess.TimeoutExpired:
            text = ""
            mean_confidence = None
            failure_reason = "tesseract_region_timeout"
        except (OSError, subprocess.SubprocessError):
            text = ""
            mean_confidence = None
            failure_reason = "tesseract_execution_failed"
        usable = ocr_text_usable(text, int(region.get("image_count", 0) or 0))
        # Source recall is more important than OCR certainty. Keep every usable
        # draft for AI review and expose its confidence; only a region with no
        # usable text becomes an explicit unreadable check item.
        accepted = usable
        confidence = (
            "high" if mean_confidence is not None and mean_confidence >= OCR_HIGH_CONFIDENCE
            else "medium" if accepted
            else "low" if mean_confidence is not None
            else "unknown"
        )
        return {
            "region_id": region["region_id"],
            "status": "read" if accepted else "pending",
            "text": text,
            "confidence": confidence,
            "mean_confidence": round(mean_confidence, 2) if mean_confidence is not None else None,
            "engine": "tesseract",
            "review_note": failure_reason or ("" if accepted else "no_usable_ocr_text"),
        }

    # Tesseract is an external process. A small worker pool shortens large mixed
    # PDFs enough to stay inside the GPTS tool window without exhausting memory.
    worker_count = min(5, max(1, len(regions)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        records = list(executor.map(read_region, regions))
    return {"schema_version": "1.0", "engine": "tesseract", "regions": records}


def split_long_text(text: str, limit: int = MAX_QUOTE_CHARS) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"(?<=[。！？；;])|\n+", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for part in parts:
        if len(part) > limit:
            if current:
                chunks.append(current)
                current = ""
            start = 0
            while start < len(part):
                end = min(len(part), start + limit)
                chunks.append(part[start:end])
                if end == len(part):
                    break
                start = max(end - CHUNK_OVERLAP, start + 1)
            continue
        if current and re.match(r"^(?:[一二三四五六七八九十百]+|\d{1,3})[、.)）]", part):
            chunks.append(current)
            current = part
            continue
        if current and has_obligation_signal(current) and has_obligation_signal(part):
            current_axes = set(business_capability_hints(current))
            part_axes = set(business_capability_hints(part))
            current_systems = set(find_system_hints(current)[0])
            part_systems = set(find_system_hints(part)[0])
            if (current_axes or current_systems) and (part_axes or part_systems):
                chunks.append(current)
                current = part
                continue
        candidate = f"{current}\n{part}".strip() if current else part
        if len(candidate) <= limit:
            current = candidate
        else:
            chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks


def ocr_quality_flags(text: str, confidence: object = "unknown", mean_confidence: object = None) -> list[str]:
    """Describe OCR text quality without treating OCR origin as a defect by itself."""
    cleaned = clean_text(text)
    confidence_label = str(confidence or "unknown").lower()
    numeric_confidence: float | None = None
    try:
        if mean_confidence is not None:
            numeric_confidence = float(mean_confidence)
    except (TypeError, ValueError):
        numeric_confidence = None
    confidence_ok = confidence_label == "high" or (
        numeric_confidence is not None and numeric_confidence >= OCR_ACCEPT_CONFIDENCE
    )
    structurally_complete = bool(
        len(cleaned) >= 10
        and matched_obligation_terms(cleaned)
        and re.search(r"[。！？；;：:]」?）?\s*$", cleaned)
    )
    return [] if confidence_ok and structurally_complete else ["ocr_fragment"]


def has_obligation_signal(text: str) -> bool:
    return bool(matched_obligation_terms(text))


def business_capability_hints(text: str) -> list[str]:
    searchable = semantic_key(text)
    return [
        capability
        for capability, terms in BUSINESS_CAPABILITY_TERMS.items()
        if any(semantic_key(term) in searchable for term in terms)
    ]


def extract_space_hints(text: str, heading: str = "") -> list[str]:
    """Return stable, source-explicit space facets for semantic review and UI filters."""
    searchable = semantic_key(f"{heading} {text}")
    return [
        facet
        for facet, terms in SPACE_FACET_TERMS.items()
        if any(semantic_key(term) in searchable for term in terms)
    ]


def is_plausible_heading(value: str) -> bool:
    value = clean_text(value)
    if not 2 <= len(value) <= 90:
        return False
    searchable = semantic_key(value)
    if re.fullmatch(r"[\d\s./\-–—()（）%]+", value):
        return False
    if matched_obligation_terms(value):
        return False
    if re.search(r"[。！？；;]$", value) or len(re.findall(r"[，,：:]", value)) >= 3:
        return False
    if re.match(r"^第.{1,12}[章節篇]", value):
        return True
    if re.match(r"^\d+(?:[.\-]\d+){1,5}\s*[\u4e00-\u9fffA-Za-z]", value):
        return True
    if re.match(r"^\d+[、.]\s*[\u4e00-\u9fffA-Za-z]{2,}", value):
        return True
    return any(
        semantic_key(term) in searchable
        for term in HEADING_HINTS + ("需求", "規格", "說明", "系統", "設備", "工程", "建築", "停車", "安全")
    )


def context_heading(page: ExtractedPage, block_index: int | None = None) -> tuple[str, str]:
    upper = len(page.blocks) if block_index is None else max(0, min(len(page.blocks), block_index - 1))
    for block in reversed(page.blocks[:upper]):
        for line in reversed(block.splitlines()):
            if is_plausible_heading(line):
                return clean_text(line), "preceding_heading"
    for line in page.text.splitlines():
        if is_plausible_heading(line):
            return clean_text(line), "page_heading"
    return f"PDF page {page.number}", "page_fallback"


def page_heading(page: ExtractedPage) -> str:
    return context_heading(page)[0]


def find_system_hints(text: str) -> tuple[list[str], list[str]]:
    searchable = semantic_key(text)
    systems: list[str] = []
    terms: list[str] = []
    for system, values in SYSTEM_TERMS.items():
        matched = [term for term in values if semantic_key(term) in searchable]
        if matched:
            systems.append(system)
            terms.extend(matched)
    return systems, terms


def source_term_present(term: str, text: str) -> bool:
    normalized_term = unicodedata.normalize("NFKC", term).lower()
    normalized_text_value = unicodedata.normalize("NFKC", text).lower()
    if re.fullmatch(r"[a-z0-9+./_-]{2,15}", normalized_term):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])", normalized_text_value))
    return semantic_key(term) in semantic_key(text)


def source_preservation_terms(text: str) -> list[str]:
    """Return source-explicit technical anchors that a translation must not erase."""
    _, hinted_system_terms = find_system_hints(text)
    matched_system_terms = [term for term in hinted_system_terms if source_term_present(term, text)]
    matched_infrastructure_terms = [
        term
        for terms in BUSINESS_CAPABILITY_TERMS.values()
        for term in terms
        if source_term_present(term, text)
    ]
    latin_terms = re.findall(r"(?<![A-Za-z0-9])(?:[A-Za-z]+[-_/])?[A-Za-z]*\d+[A-Za-z0-9+./_-]*|\b[A-Z][A-Z0-9+./_-]{1,14}\b", unicodedata.normalize("NFKC", text))
    terms: list[str] = []
    for term in matched_system_terms + matched_infrastructure_terms + latin_terms:
        normalized = str(term).strip()
        if len(normalized) < 2 or normalized.lower() in GENERIC_PRESERVATION_TERMS:
            continue
        if normalized not in terms:
            terms.append(normalized)
    return terms


def candidate_score(text: str, heading: str, dynamic_terms: set[str]) -> tuple[int, list[str], list[str]]:
    searchable = semantic_key(text)
    systems, matched = find_system_hints(text)
    score = min(6, len(matched) * 2)
    semantic_matches = [term for term in SEMANTIC_TERMS if semantic_key(term) in searchable]
    capability_matches = business_capability_hints(text)
    obligation_matches = matched_obligation_terms(text)
    interface_matches = [term for term in INTERFACE_DOMAINS if semantic_key(term) in searchable]
    dynamic_matches = [term for term in dynamic_terms if semantic_key(term) in searchable]
    if semantic_matches:
        score += 1
    if capability_matches:
        score += 1
    if len(capability_matches) >= 2:
        score += 1
    if obligation_matches:
        score += 1
    if any(semantic_key(term) in semantic_key(heading) for term in HEADING_HINTS):
        score += 2
    if interface_matches and semantic_matches:
        score += 1
    if dynamic_matches and (semantic_matches or obligation_matches):
        score += 1
    return score, systems, sorted(set(matched + semantic_matches + capability_matches + interface_matches + dynamic_matches))


def candidate_admitted(
    text: str,
    heading: str,
    score: int,
    systems: list[str],
    business_axes: list[str],
) -> bool:
    """Keep every readable source block visible; semantic fields are hints only."""
    return bool(clean_text(text))


def candidate_signal_flags(text: str, systems: list[str]) -> list[str]:
    """Return compact semantic cues without deciding the final business route."""
    lowered = unicodedata.normalize("NFKC", text).lower()
    searchable = semantic_key(text)
    flags: list[str] = []
    if any(semantic_key(term) in searchable for term in NEGATION_TERMS):
        flags.append("negation_or_exclusion")
    if any(semantic_key(term) in searchable for term in CONDITION_TERMS):
        flags.append("condition_or_exception")
    if len(systems) >= 2:
        flags.append("cross_system")
    if re.search(r"(?:\d+(?:\.\d+)?\s*(?:mhz|ghz|mbps|gbps|mm|cm|m|v|a|w)\b|iso\s*\d+|ieee\s*[\d.]+)", lowered):
        flags.append("specification_signal")
    if len(text) < 120 and not re.search(r"[.?!。！？；;:]」?）?\s*$", text):
        flags.append("possible_fragment")
    return flags


def discover_dynamic_terms(chunks: Iterable[str]) -> list[str]:
    counter: Counter[str] = Counter()
    for text in chunks:
        searchable = semantic_key(text)
        if not find_system_hints(text)[0] and not any(semantic_key(term) in searchable for term in SEMANTIC_TERMS):
            continue
        for value in re.findall(r"\b[A-Z][A-Z0-9+./_-]{1,14}\b", text.upper()):
            if value not in {"PDF", "PAGE", "THE", "AND", "FOR"}:
                counter[value] += 1
    return [term for term, count in counter.most_common(80) if count >= 2]


def source_pack(
    pdf_path: Path,
    visual_output_dir: Path | None = None,
    auto_ocr: bool = True,
    page_offset: int = 0,
    defer_ocr_to_model_vision: bool = False,
) -> dict[str, object]:
    if not auto_ocr:
        raise ValueError(
            "automatic OCR is mandatory; do not create a source pack with pending image regions"
        )
    pages, engine = extract_pages(pdf_path)
    if not pages:
        raise RuntimeError("PDF contains no pages")
    if any(not page.visual_audit_available for page in pages):
        raise RuntimeError("PyMuPDF is required for image-text coverage audit; pypdf text extraction alone is unsafe")
    if page_offset:
        for page in pages:
            local_page = page.number
            page.number = local_page + page_offset
            for index, region in enumerate(page.visual_regions, start=1):
                region["source_local_page"] = local_page
                region["pdf_page"] = page.number
                region["region_id"] = f"VR-P{page.number:04d}-{index:03d}"
    repeated = repeated_margin_lines(pages)
    pages = [remove_margin_noise(page, repeated) for page in pages]
    all_chunks = [chunk for page in pages for block in page.blocks for chunk in split_long_text(block)]
    dynamic_terms = set(discover_dynamic_terms(all_chunks))

    source_id = "SRC-001"
    page_records: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    claims: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    document_terms: list[dict[str, object]] = []
    term_pages: dict[str, set[str]] = {term: set() for term in dynamic_terms}
    visual_regions: list[dict[str, object]] = []

    for page in pages:
        page_id = f"{source_id}-P{page.number:04d}"
        heading = page_heading(page)
        for region in page.visual_regions:
            region["page_id"] = page_id
            region["context_heading"] = heading or f"來源頁 {page.number} 影像文字區塊"
            region["context_heading_basis"] = "page_heading" if heading else "page_fallback"
            visual_regions.append(region)
        accepted_chunks: list[tuple[str, int, list[str], list[str], list[str], str, str, int, int]] = []
        for block_index, block in enumerate(page.blocks, start=1):
            chunk_heading, heading_basis = context_heading(page, block_index)
            for chunk_index, chunk in enumerate(split_long_text(block), start=1):
                if is_navigation_chunk(chunk):
                    continue
                score, systems, matched_terms = candidate_score(chunk, chunk_heading, dynamic_terms)
                business_axes = business_capability_hints(chunk)
                for term in dynamic_terms:
                    if semantic_key(term) in semantic_key(chunk):
                        term_pages[term].add(page_id)
                if candidate_admitted(chunk, chunk_heading, score, systems, business_axes):
                    accepted_chunks.append(
                        (chunk, score, systems, matched_terms, business_axes, chunk_heading, heading_basis, block_index, chunk_index)
                    )

        first_serial = len(candidates) + 1
        candidate_ids = [f"CAND-{first_serial + offset:05d}" for offset in range(len(accepted_chunks))]
        for page_index, (
            chunk,
            score,
            systems,
            matched_terms,
            business_axes,
            chunk_heading,
            heading_basis,
            block_index,
            chunk_index,
        ) in enumerate(accepted_chunks):
            serial = first_serial + page_index
            candidate_id = candidate_ids[page_index]
            claim_id = f"CLM-{serial:05d}"
            evidence_id = f"EV-{serial:05d}"
            neighbor_candidate_ids = candidate_ids[max(0, page_index - 1):page_index] + candidate_ids[page_index + 1:page_index + 2]
            signal_flags = candidate_signal_flags(chunk, systems)
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "page_ids": [page_id],
                    "topic_hint": systems[0] if systems else "弱電業務能力候選",
                    "status": "pending",
                    "reason": "source_reading_block",
                    "claim_id": claim_id,
                    "score": score,
                    "matched_terms": matched_terms,
                    "preservation_terms": source_preservation_terms(chunk),
                    "obligation_terms": matched_obligation_terms(chunk),
                    "business_axes": business_axes,
                    "sequence_on_page": page_index + 1,
                    "block_index": block_index,
                    "chunk_index": chunk_index,
                    "neighbor_candidate_ids": neighbor_candidate_ids,
                    "signal_flags": signal_flags,
                }
            )
            direct_space_hints = extract_space_hints(chunk)
            inherited_space_hints = extract_space_hints(chunk_heading)
            space_hints = list(dict.fromkeys(direct_space_hints + inherited_space_hints))
            space_hint_basis = "explicit" if direct_space_hints else ("inherited" if inherited_space_hints else "none")
            claims.append(
                {
                    "claim_id": claim_id,
                    "topic": "review",
                    "neutral_fact": chunk,
                    "context_heading": chunk_heading,
                    "context_heading_basis": heading_basis,
                    "system_hints": systems,
                    "system_hint_basis": "inferred" if systems else "none",
                    "space_hints": space_hints,
                    "space_hint_basis": space_hint_basis,
                    "claim_kind": "source_fragment",
                    "semantic_readiness": "meaning_unclear",
                    "source_shape": "table_block" if "\n" in chunk and len(chunk.splitlines()) >= 4 else "sentence",
                    "text_quality_flags": ["mixed_topics"] if len(systems) >= 3 else [],
                    "business_basis_hints": business_axes,
                    "evidence_ids": [evidence_id],
                    "relations": [],
                    "disposition": "uncertain",
                    "audit_origin": "pass1",
                }
            )
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "claim_id": claim_id,
                    "source_id": source_id,
                    "pdf_page": page.number,
                    "printed_page": str(page.number),
                    "section": chunk_heading,
                    "section_basis": heading_basis,
                    "quote": chunk,
                    "origin_kind": "source",
                    "interpretation": "explicit",
                    "integration_flags": [],
                }
            )

        page_text = page.text
        if page.visual_regions:
            status = "pending"
            reason_code = "visual_text_pending"
            coverage_status = "visual_pending"
        else:
            status = "candidate" if candidate_ids else ("unreadable" if not page_text else "excluded")
            reason_code = "source_reading_pack" if candidate_ids else ("no_text_layer" if not page_text else "no_readable_content_after_cleanup")
            coverage_status = "native_complete" if page_text else "unreadable"
        page_records.append(
            {
                "page_id": page_id,
                "source_id": source_id,
                "pdf_page": page.number,
                "printed_page": str(page.number),
                "section": heading,
                "status": status,
                "fingerprint": hashlib.sha256(page_text.encode("utf-8")).hexdigest(),
                "candidate_ids": candidate_ids,
                "reason_code": reason_code,
                "coverage_status": coverage_status,
                "native_text_present": bool(page_text),
                "visual_region_ids": [str(region["region_id"]) for region in page.visual_regions],
            }
        )

    for index, term in enumerate(sorted(dynamic_terms), start=1):
        document_terms.append(
            {
                "term_id": f"TERM-{index:04d}",
                "term": term,
                "source_page_ids": sorted(term_pages[term]),
                "relation_hint": "document_dynamic_term",
            }
        )

    now = datetime.now(timezone.utc).isoformat()
    candidate_ids = [str(item["candidate_id"]) for item in candidates]
    pending_page_ids = [str(page["page_id"]) for page in page_records if page["status"] == "pending"]
    issues = [
        {
            "issue_id": f"ISSUE-UNREADABLE-{int(page['pdf_page']):04d}",
            "kind": "unreadable_page",
            "page_ids": [page["page_id"]],
            "pdf_pages": [page["pdf_page"]],
            "note": "該頁沒有可用文字層，需人工確認是否含弱電相關圖像或掃描文字。",
            "origin_kind": "check_item",
        }
        for page in page_records
        if page["status"] == "unreadable"
    ]
    data: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "workflow_version": WORKFLOW_VERSION,
        "checkpoint": {
            "checkpoint_id": f"CP-{hashlib.sha256((pdf_path.name + now).encode('utf-8')).hexdigest()[:12].upper()}",
            "sequence": 1,
            "state": "stage1_visual_pending" if pending_page_ids else "stage1_auditing",
            "last_passed_gate": "index",
            "next_action": "transcribe_visual_regions" if pending_page_ids else "run_semantic_freeze",
            "pending_page_ids": pending_page_ids,
            "pending_candidate_ids": candidate_ids,
            "continue_count": 0,
            "user_step": "extract",
            "created_at": now,
            "updated_at": now,
        },
        "source_manifest": [
            {
                "source_id": source_id,
                "name": pdf_path.name,
                "role": "requirements",
                "sha256": sha256_path(pdf_path),
                "page_count": len(pages),
                "extraction_engine": engine,
            }
        ],
        "pages": page_records,
        "visual_regions": visual_regions,
        "visual_audit": {
            "status": "pending" if visual_regions else "not_required",
            "engine": "tesseract_primary" if visual_regions else "none",
            "region_count": len(visual_regions),
            "resolved_region_count": 0,
            "pending_region_ids": [str(region["region_id"]) for region in visual_regions],
            "manifest_path": "",
        },
        "document_terms": document_terms,
        "candidates": candidates,
        "claims": claims,
        "evidence": evidence,
        "issues": issues,
        "recall_audit": {
            "audit_round": 0,
            "excluded_pages_rechecked": 0,
            "context_pages_rechecked": 0,
            "empty_sections_rechecked": 0,
            "dynamic_terms_searched": len(dynamic_terms),
            "new_candidate_ids": [],
            "processed_candidate_ids": [],
            "unprocessed_candidate_ids": candidate_ids,
            "settled": False,
            "stop_reason": "source_reading_pack_ready",
        },
        "extraction_summary": {
            "engine": engine,
            "page_count": len(pages),
            "candidate_page_count": sum(1 for item in page_records if item["status"] == "candidate"),
            "candidate_count": len(candidates),
            "unreadable_page_count": sum(1 for item in page_records if item["status"] == "unreadable"),
            "repeated_margin_line_count": len(repeated),
            "visual_region_count": len(visual_regions),
            "visual_pending_page_count": len(pending_page_ids),
        },
    }
    if visual_output_dir is not None and visual_regions:
        render_visual_regions(pdf_path, visual_regions, visual_output_dir)
        visual_audit = data["visual_audit"]
        assert isinstance(visual_audit, dict)
        visual_audit["manifest_path"] = str(visual_output_dir / "manifest.json")
        capability = tesseract_capability()
        visual_audit["runtime_ocr"] = capability
        if defer_ocr_to_model_vision:
            visual_audit["ocr_deferred_to_model_vision"] = True
        elif auto_ocr and capability.get("available"):
            payload = run_tesseract_regions(visual_output_dir, visual_regions, capability)
            data = merge_visual_transcriptions(data, payload)
    return data


def next_numeric_id(items: list[dict[str, object]], key: str, prefix: str) -> int:
    values: list[int] = []
    for item in items:
        match = re.fullmatch(rf"{re.escape(prefix)}-(\d+)", str(item.get(key, "")))
        if match:
            values.append(int(match.group(1)))
    return max(values, default=0) + 1


def visual_candidate_admitted(
    text: str,
    heading: str,
    score: int,
    systems: list[str],
    matched_terms: list[str],
    business_axes: list[str],
) -> bool:
    """Keep readable OCR text visible even when project vocabulary is unfamiliar."""
    return bool(clean_text(text))


def merge_visual_transcriptions(
    data: dict[str, object],
    payload: dict[str, object],
) -> dict[str, object]:
    regions = {
        str(item.get("region_id")): item
        for item in data.get("visual_regions", [])
        if isinstance(item, dict) and item.get("region_id")
    }
    pages = {
        str(item.get("page_id")): item
        for item in data.get("pages", [])
        if isinstance(item, dict) and item.get("page_id")
    }
    records = payload.get("regions", [])
    if not isinstance(records, list):
        raise ValueError("visual transcription payload.regions must be an array")

    candidates = data.get("candidates", [])
    claims = data.get("claims", [])
    evidence = data.get("evidence", [])
    issues = data.get("issues", [])
    if not all(isinstance(value, list) for value in (candidates, claims, evidence, issues)):
        raise ValueError("candidate pack collections are invalid")
    candidates = [item for item in candidates if isinstance(item, dict)]
    claims = [item for item in claims if isinstance(item, dict)]
    evidence = [item for item in evidence if isinstance(item, dict)]
    issues = [item for item in issues if isinstance(item, dict)]
    data["candidates"] = candidates
    data["claims"] = claims
    data["evidence"] = evidence
    data["issues"] = issues

    dynamic_terms = {
        str(item.get("term"))
        for item in data.get("document_terms", [])
        if isinstance(item, dict) and item.get("term")
    }
    existing_quotes: dict[str, set[str]] = {}
    evidence_by_claim = {str(item.get("claim_id")): item for item in evidence if item.get("claim_id")}
    for candidate in candidates:
        claim_id = str(candidate.get("claim_id", ""))
        source = evidence_by_claim.get(claim_id, {})
        page_ids = [str(value) for value in candidate.get("page_ids", []) if value]
        if page_ids and source.get("quote"):
            existing_quotes.setdefault(page_ids[0], set()).add(semantic_key(str(source["quote"])))

    candidate_serial = next_numeric_id(candidates, "candidate_id", "CAND")
    claim_serial = next_numeric_id(claims, "claim_id", "CLM")
    evidence_serial = next_numeric_id(evidence, "evidence_id", "EV")
    new_candidate_ids: list[str] = []

    for record in records:
        if not isinstance(record, dict):
            continue
        region_id = str(record.get("region_id", ""))
        region = regions.get(region_id)
        if region is None:
            raise ValueError(f"unknown visual region: {region_id}")
        status = str(record.get("status", "pending"))
        if status not in {"read", "unreadable", "skipped_non_text", "pending"}:
            raise ValueError(f"visual region {region_id} has invalid status: {status}")
        if status == "skipped_non_text":
            engine = str(record.get("engine", payload.get("engine", "")))
            review_note = clean_text(str(record.get("review_note", "")))
            if engine != "model_vision" or len(review_note) < 8:
                raise ValueError(
                    f"visual region {region_id} cannot be skipped without an explicit model_vision review_note"
                )
        text = clean_text(str(record.get("text", "")))
        if status == "read" and not ocr_text_usable(text, int(region.get("image_count", 0) or 0)):
            status = "pending"
        region["status"] = status
        region["transcribed_text"] = text if status == "read" else ""
        if status == "pending" and text:
            region["ocr_draft"] = text
        region["confidence"] = str(record.get("confidence", "unknown"))
        if record.get("mean_confidence") is not None:
            region["mean_confidence"] = record.get("mean_confidence")
        region["engine"] = str(record.get("engine", payload.get("engine", "gpts_vision")))
        if status != "read":
            continue

        page_id = str(region.get("page_id", ""))
        page = pages.get(page_id)
        if page is None:
            raise ValueError(f"visual region {region_id} references missing page {page_id}")
        heading = str(region.get("context_heading", "")) or f"來源頁 {region.get('pdf_page')} 影像文字區塊"
        heading_basis = str(region.get("context_heading_basis", "page_fallback"))
        for chunk_index, chunk in enumerate(split_long_text(text), start=1):
            quote_key = semantic_key(chunk)
            if not quote_key or quote_key in existing_quotes.setdefault(page_id, set()):
                continue
            score, systems, matched_terms = candidate_score(chunk, heading, dynamic_terms)
            business_axes = business_capability_hints(chunk)
            if not visual_candidate_admitted(chunk, heading, score, systems, matched_terms, business_axes):
                continue
            candidate_id = f"CAND-{candidate_serial:05d}"
            claim_id = f"CLM-{claim_serial:05d}"
            evidence_id = f"EV-{evidence_serial:05d}"
            candidate_serial += 1
            claim_serial += 1
            evidence_serial += 1
            signal_flags = candidate_signal_flags(chunk, systems)
            quality_flags = ocr_quality_flags(
                chunk,
                record.get("confidence", region.get("confidence", "unknown")),
                record.get("mean_confidence", region.get("mean_confidence")),
            )
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "page_ids": [page_id],
                    "topic_hint": systems[0] if systems else "弱電業務能力候選",
                    "status": "pending",
                    "reason": "visual_source_candidate",
                    "claim_id": claim_id,
                    "score": score,
                    "matched_terms": matched_terms,
                    "preservation_terms": source_preservation_terms(chunk),
                    "obligation_terms": matched_obligation_terms(chunk),
                    "business_axes": business_axes,
                    "sequence_on_page": len(page.get("candidate_ids", [])) + 1,
                    "block_index": 100000 + chunk_index,
                    "chunk_index": chunk_index,
                    "neighbor_candidate_ids": [],
                    "signal_flags": signal_flags,
                    "visual_region_id": region_id,
                }
            )
            direct_space_hints = extract_space_hints(chunk)
            inherited_space_hints = extract_space_hints(heading)
            space_hints = list(dict.fromkeys(direct_space_hints + inherited_space_hints))
            claims.append(
                {
                    "claim_id": claim_id,
                    "topic": "review",
                    "neutral_fact": chunk,
                    "context_heading": heading,
                    "context_heading_basis": heading_basis,
                    "system_hints": systems,
                    "system_hint_basis": "inferred" if systems else "none",
                    "space_hints": space_hints,
                    "space_hint_basis": "explicit" if direct_space_hints else ("inherited" if inherited_space_hints else "none"),
                    "claim_kind": "source_fragment",
                    "semantic_readiness": "meaning_unclear",
                    "source_shape": "list_item" if re.match(r"^[一二三四五六七八九十百\d]+[、.]", chunk) else "sentence",
                    "text_quality_flags": quality_flags,
                    "business_basis_hints": business_axes,
                    "evidence_ids": [evidence_id],
                    "relations": [],
                    "disposition": "uncertain",
                    "audit_origin": "pass1",
                }
            )
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "claim_id": claim_id,
                    "source_id": page.get("source_id"),
                    "pdf_page": region.get("pdf_page"),
                    "printed_page": str(page.get("printed_page", region.get("pdf_page", ""))),
                    "section": heading,
                    "section_basis": heading_basis,
                    "quote": chunk,
                    "origin_kind": "source_ocr",
                    "interpretation": "explicit",
                    "integration_flags": [],
                    "visual_region_id": region_id,
                    "bbox": region.get("bbox", []),
                    "confidence": region.get("confidence", "unknown"),
                    "ocr_engine": region.get("engine", "gpts_vision"),
                }
            )
            page.setdefault("candidate_ids", []).append(candidate_id)
            existing_quotes[page_id].add(quote_key)
            new_candidate_ids.append(candidate_id)

    region_by_page: dict[str, list[dict[str, object]]] = {}
    for region in regions.values():
        region_by_page.setdefault(str(region.get("page_id", "")), []).append(region)
    for page_id, page_regions in region_by_page.items():
        page = pages[page_id]
        unresolved = [region for region in page_regions if region.get("status") == "pending"]
        unreadable = [region for region in page_regions if region.get("status") == "unreadable"]
        if unresolved:
            page["status"] = "pending"
            page["reason_code"] = "visual_text_pending"
            page["coverage_status"] = "visual_pending"
            continue
        candidate_ids = [str(value) for value in page.get("candidate_ids", []) if value]
        page["status"] = "candidate" if candidate_ids else ("excluded" if page.get("native_text_present") else "unreadable")
        page["reason_code"] = "source_reading_pack" if candidate_ids else ("no_readable_content_after_cleanup" if page.get("native_text_present") else "no_text_layer")
        page["coverage_status"] = "partial_unreadable" if unreadable else "hybrid_complete"
        combined = str(page.get("fingerprint", "")) + "\n" + "\n".join(
            str(region.get("transcribed_text", "")) for region in page_regions
        )
        page["fingerprint"] = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        for region in unreadable:
            issue_id = f"ISSUE-VISUAL-{region['region_id']}"
            if not any(str(item.get("issue_id")) == issue_id for item in issues):
                issues.append(
                    {
                        "issue_id": issue_id,
                        "kind": "visual_region_unreadable",
                        "page_ids": [page_id],
                        "pdf_pages": [page.get("pdf_page")],
                        "note": "影像文字區塊無法可靠辨識，須人工確認是否含弱電或跨專業介面需求。",
                        "origin_kind": "check_item",
                        "visual_region_ids": [region["region_id"]],
                    }
                )

    candidates_by_page: dict[str, list[str]] = {}
    for candidate in candidates:
        for page_id in candidate.get("page_ids", []):
            candidates_by_page.setdefault(str(page_id), []).append(str(candidate.get("candidate_id")))
    candidate_lookup = {str(item.get("candidate_id")): item for item in candidates}
    for page_id, candidate_ids in candidates_by_page.items():
        if page_id in pages:
            pages[page_id]["candidate_ids"] = candidate_ids
        for index, candidate_id in enumerate(candidate_ids):
            candidate_lookup[candidate_id]["sequence_on_page"] = index + 1
            candidate_lookup[candidate_id]["neighbor_candidate_ids"] = (
                candidate_ids[max(0, index - 1):index] + candidate_ids[index + 1:index + 2]
            )

    pending_region_ids = sorted(
        region_id for region_id, region in regions.items() if region.get("status") == "pending"
    )
    pending_page_ids = sorted(
        page_id for page_id, page in pages.items() if page.get("status") == "pending"
    )
    checkpoint = data.get("checkpoint", {})
    if not isinstance(checkpoint, dict):
        raise ValueError("candidate pack checkpoint is invalid")
    checkpoint.update(
        {
            "state": "stage1_visual_pending" if pending_page_ids else "stage1_auditing",
            "next_action": "transcribe_visual_regions" if pending_page_ids else "run_semantic_freeze",
            "pending_page_ids": pending_page_ids,
            "pending_candidate_ids": [str(item.get("candidate_id")) for item in candidates],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    visual_audit = data.get("visual_audit", {})
    if isinstance(visual_audit, dict):
        visual_audit.update(
            {
                "status": "pending" if pending_region_ids else "complete",
                "engine": str(payload.get("engine", "gpts_vision")),
                "resolved_region_count": len(regions) - len(pending_region_ids),
                "pending_region_ids": pending_region_ids,
            }
        )
    recall = data.get("recall_audit", {})
    if isinstance(recall, dict):
        all_candidate_ids = [str(item.get("candidate_id")) for item in candidates]
        recall["new_candidate_ids"] = list(dict.fromkeys(list(recall.get("new_candidate_ids", [])) + new_candidate_ids))
        recall["unprocessed_candidate_ids"] = all_candidate_ids
        recall["stop_reason"] = (
            "visual_transcription_pending" if pending_region_ids else "source_reading_pack_ready"
        )
    summary = data.get("extraction_summary", {})
    if isinstance(summary, dict):
        summary.update(
            {
                "candidate_page_count": sum(1 for page in pages.values() if page.get("status") == "candidate"),
                "candidate_count": len(candidates),
                "unreadable_page_count": sum(1 for page in pages.values() if page.get("status") == "unreadable"),
                "visual_pending_page_count": len(pending_page_ids),
            }
        )
    return data


def candidate_view(data: dict[str, object]) -> dict[str, object]:
    claims = {
        str(item["claim_id"]): item
        for item in data.get("claims", [])
        if isinstance(item, dict) and item.get("claim_id")
    }
    evidence = {
        str(item["claim_id"]): item
        for item in data.get("evidence", [])
        if isinstance(item, dict) and item.get("claim_id")
    }
    derived_neighbors: dict[str, list[str]] = {}
    for page in data.get("pages", []):
        if not isinstance(page, dict):
            continue
        page_candidate_ids = [str(value) for value in page.get("candidate_ids", []) if value]
        for index, candidate_id in enumerate(page_candidate_ids):
            neighbors = page_candidate_ids[max(0, index - 1):index] + page_candidate_ids[index + 1:index + 2]
            derived_neighbors[candidate_id] = list(dict.fromkeys(derived_neighbors.get(candidate_id, []) + neighbors))
    grouped: dict[str, dict[str, object]] = {}
    for candidate in data.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        claim_id = str(candidate.get("claim_id", ""))
        claim = claims.get(claim_id, {})
        source = evidence.get(claim_id, {})
        quote = str(source.get("quote", ""))
        key = re.sub(r"\s+", "", quote).lower()
        record = grouped.setdefault(
            key,
            {
                "candidate_ids": [],
                "pdf_pages": [],
                "sections": [],
                "context_headings": [],
                "context_heading_bases": [],
                "quote": quote,
                "system_hints": [],
                "space_hints": [],
                "matched_terms": [],
                "preservation_terms": [],
                "business_axes": [],
                "source_shape": claim.get("source_shape"),
                "text_quality_flags": [],
                "neighbor_candidate_ids": [],
                "neighbor_candidate_count": 0,
                "signal_flags": [],
                "origin_kinds": [],
                "source_confidences": [],
                "obligation_terms": [],
            },
        )
        record["candidate_ids"].append(candidate.get("candidate_id"))
        if source.get("pdf_page") not in record["pdf_pages"]:
            record["pdf_pages"].append(source.get("pdf_page"))
        if source.get("section") not in record["sections"]:
            record["sections"].append(source.get("section"))
        if claim.get("context_heading") not in record["context_headings"]:
            record["context_headings"].append(claim.get("context_heading"))
        if claim.get("context_heading_basis") not in record["context_heading_bases"]:
            record["context_heading_bases"].append(claim.get("context_heading_basis"))
        for hint in claim.get("system_hints", []):
            if hint not in record["system_hints"]:
                record["system_hints"].append(hint)
        for hint in claim.get("space_hints", []):
            if hint not in record["space_hints"]:
                record["space_hints"].append(hint)
        for term in candidate.get("matched_terms", []):
            if term not in record["matched_terms"]:
                record["matched_terms"].append(term)
        for term in candidate.get("preservation_terms", source_preservation_terms(quote)):
            if term not in record["preservation_terms"]:
                record["preservation_terms"].append(term)
        for axis in candidate.get("business_axes", claim.get("business_basis_hints", [])):
            if axis not in record["business_axes"]:
                record["business_axes"].append(axis)
        for flag in claim.get("text_quality_flags", []):
            if flag not in record["text_quality_flags"]:
                record["text_quality_flags"].append(flag)
        origin_kind = str(source.get("origin_kind", "source"))
        if origin_kind not in record["origin_kinds"]:
            record["origin_kinds"].append(origin_kind)
        source_confidence = str(source.get("confidence", "not_applicable"))
        if source_confidence not in record["source_confidences"]:
            record["source_confidences"].append(source_confidence)
        for term in candidate.get("obligation_terms", matched_obligation_terms(quote)):
            if term not in record["obligation_terms"]:
                record["obligation_terms"].append(term)
        candidate_neighbors = candidate.get("neighbor_candidate_ids") or derived_neighbors.get(str(candidate.get("candidate_id", "")), [])
        for neighbor_id in candidate_neighbors:
            if neighbor_id not in record["neighbor_candidate_ids"]:
                record["neighbor_candidate_ids"].append(neighbor_id)
        candidate_flags = candidate.get("signal_flags") or candidate_signal_flags(quote, [str(value) for value in claim.get("system_hints", [])])
        for flag in candidate_flags:
            if flag not in record["signal_flags"]:
                record["signal_flags"].append(flag)
    for record in grouped.values():
        record["neighbor_candidate_count"] = len(record["neighbor_candidate_ids"])
        record["neighbor_candidate_ids"] = record["neighbor_candidate_ids"][:12]
    records = list(grouped.values())
    evidence_groups: list[dict[str, object]] = []
    pending: list[dict[str, object]] = []
    pending_key: tuple[object, object] | None = None
    pending_chars = 0
    pending_candidates = 0

    def flush_group() -> None:
        nonlocal pending, pending_key, pending_chars, pending_candidates
        if not pending:
            return
        first_index = records.index(pending[0])
        last_index = records.index(pending[-1])
        leading = records[first_index - 1] if first_index > 0 else None
        trailing = records[last_index + 1] if last_index + 1 < len(records) else None
        group_id = f"EGRP-{len(evidence_groups) + 1:04d}"
        route_candidate_ids = [
            str(candidate_id)
            for record in pending
            for candidate_id in record["candidate_ids"]
        ]
        segments = [
            {
                "candidate_ids": record["candidate_ids"],
                "pdf_pages": record["pdf_pages"],
                "context_headings": record["context_headings"],
                "quote": record["quote"],
                "system_hints": record["system_hints"],
                "space_hints": record["space_hints"],
                "business_axes": record["business_axes"],
                "preservation_terms": record["preservation_terms"],
                "source_shape": record["source_shape"],
                "origin_kinds": record["origin_kinds"],
                "source_confidences": record["source_confidences"],
                "text_quality_flags": record["text_quality_flags"],
                "signal_flags": record["signal_flags"],
            }
            for record in pending
        ]
        evidence_groups.append(
            {
                "evidence_group_id": group_id,
                "route_candidate_ids": route_candidate_ids,
                "pdf_pages": list(dict.fromkeys(page for record in pending for page in record["pdf_pages"])),
                "section_path": list(dict.fromkeys(
                    str(value)
                    for record in pending
                    for value in record["context_headings"] + record["sections"]
                    if value
                )),
                "leading_context": (
                    {"candidate_ids": leading["candidate_ids"], "quote": leading["quote"]}
                    if leading is not None else None
                ),
                "segments": segments,
                "trailing_context": (
                    {"candidate_ids": trailing["candidate_ids"], "quote": trailing["quote"]}
                    if trailing is not None else None
                ),
            }
        )
        pending = []
        pending_key = None
        pending_chars = 0
        pending_candidates = 0

    for record in records:
        key = (record["pdf_pages"][0] if record["pdf_pages"] else None, None)
        record_chars = len(str(record["quote"]))
        record_candidates = len(record["candidate_ids"])
        if pending and (
            key != pending_key
            or pending_chars + record_chars > EVIDENCE_GROUP_MAX_CHARS
            or pending_candidates + record_candidates > EVIDENCE_GROUP_MAX_CANDIDATES
        ):
            flush_group()
        if not pending:
            pending_key = key
        pending.append(record)
        pending_chars += record_chars
        pending_candidates += record_candidates
    flush_group()
    coverage_fields = ["candidate_ids", "evidence_group_id"]
    coverage_rows = [
        [group["route_candidate_ids"], group["evidence_group_id"]]
        for group in evidence_groups
    ]
    return {
        "schema_version": data.get("schema_version"),
        "workflow_version": data.get("workflow_version"),
        "source_manifest": data.get("source_manifest", []),
        "extraction_summary": data.get("extraction_summary", {}),
        "candidate_count": sum(len(record["candidate_ids"]) for record in grouped.values()),
        "row_count": len(coverage_rows),
        "fields": coverage_fields,
        "rows": coverage_rows,
        "evidence_group_count": len(evidence_groups),
        "evidence_groups": evidence_groups,
        "unreadable_pages": [
            {
                "pdf_page": page.get("pdf_page"),
                "section": page.get("section"),
                "reason_code": page.get("reason_code"),
            }
            for page in data.get("pages", [])
            if isinstance(page, dict) and page.get("status") == "unreadable"
        ],
        "visual_pending_pages": [
            {
                "pdf_page": page.get("pdf_page"),
                "section": page.get("section"),
                "visual_region_ids": page.get("visual_region_ids", []),
            }
            for page in data.get("pages", [])
            if isinstance(page, dict) and page.get("status") == "pending"
        ],
        "visual_audit": data.get("visual_audit", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or complete an M1 source-reading pack.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path, nargs="?", default=Path("m1_resume.json"))
    parser.add_argument("candidate_view", type=Path, nargs="?", default=Path("m1_candidates.json"))
    parser.add_argument("--vision-dir", type=Path, default=Path("m1_vision_regions"))
    parser.add_argument("--vision-transcriptions", type=Path)
    parser.add_argument("--page-offset", type=int, default=0)
    args = parser.parse_args()

    if args.vision_transcriptions is None and not args.pdf.is_file():
        print(f"FAIL: PDF not found: {args.pdf}")
        return 2
    try:
        if args.vision_transcriptions is not None:
            if not args.output.is_file():
                print(f"FAIL: checkpoint not found for visual merge: {args.output}")
                return 2
            data = json.loads(args.output.read_text(encoding="utf-8"))
            payload = json.loads(args.vision_transcriptions.read_text(encoding="utf-8"))
            data = merge_visual_transcriptions(data, payload)
        else:
            data = source_pack(
                args.pdf,
                visual_output_dir=args.vision_dir,
                page_offset=args.page_offset,
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        args.candidate_view.parent.mkdir(parents=True, exist_ok=True)
        args.candidate_view.write_text(
            json.dumps(candidate_view(data), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1
    summary = data["extraction_summary"]
    print(
        "PASS: candidate pack created | "
        f"pages={summary['page_count']} candidate_pages={summary['candidate_page_count']} "
        f"candidates={summary['candidate_count']} unreadable={summary['unreadable_page_count']} "
        f"visual_pending={summary.get('visual_pending_page_count', 0)} "
        f"view={args.candidate_view}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
