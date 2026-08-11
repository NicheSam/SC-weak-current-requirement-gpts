from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import tempfile
import unittest
import zipfile

import render_m1_outputs


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "sandbox" / "md_pipeline_v06" / "input" / "m1_candidates.json"


MASTER = """# 中央市場好宅 | 弱電需求主檔

- 來源文件：04-統包需求計畫書整合檔.pdf
- 來源 SHA-256：`36894e15e3fb9ebe3ba4e4c3f69f2625341c8c1976094ae1568aebef63141cd3`
- 產出日期：2026-08-10

## 專案摘要

- 地下停車空間需整合行動通訊改善與車道辨識系統。

## 需求樹

### 通訊涵蓋系統

- 系統摘要：地下停車空間需以強波器及洩波同軸改善行動通訊訊號涵蓋。
- 系統設計重點：確認涵蓋範圍、電信業者介接、供電與訊號測試責任。
- 主要介面：電信業者、停車場空間、弱電供電
- 主要圖說／文件：行動通訊系統架構圖、涵蓋配置圖、訊號測試報告

#### 地下室行動通訊改善

- 主題說明：整合地下室強波器與洩波同軸兩項行動通訊改善要求。
- 主題設計重點：依地下室範圍規劃設備、線纜路徑、供電及涵蓋測試。
- 主題圖說／文件：設備配置圖、洩波同軸路徑圖

- [REQ-M1-0001] 地下室應建置 5G 強波器，以改善地下空間行動通訊涵蓋。
  - 空間：地下室停車空間
  - 狀態：來源明示
  - 來源：PDF 28；印刷 20；CAND-00686
  - 原文：地下室建置 5G 強波器。

- [REQ-M1-0002] 停車空間應設置行動通訊改善系統，並採用洩波同軸電纜。
  - 空間：地下室停車空間
  - 狀態：來源明示
  - 來源：PDF 28；印刷 20；CAND-00687
  - 原文：行動通訊改善系統（洩波同軸電纜）。

### 停車管理系統

- 系統摘要：停車場以車牌、E-TAG 與住戶讀卡整合車道通行管理。
- 系統設計重點：確認汽機車道設備配置、辨識邏輯與出租系統預留介面。
- 主要介面：門禁、中央監控、物業管理
- 主要圖說／文件：停車管理架構圖、車道設備配置圖、I/O 點表

#### 車道辨識與通行

- 主題說明：整合汽機車道的辨識設備、讀卡功能與後續出租預留。
- 主題設計重點：釐清辨識優先序、柵欄控制及異常通行處理方式。

- [REQ-M1-0003] 汽車道及機車道均應設置 E-TAG、車牌辨識及住戶感應讀卡功能，並預留出租系統管線。
  - 空間：車道與停車場出入口
  - 狀態：跨章整合
  - 來源：PDF 28；印刷 20；CAND-00684
  - 原文：車道柵欄汽車道及機車道皆採 E-TAG 系統、車牌辨識系統及住戶讀卡感應。

## 需要人工確認

- [REV-M1-0001] 請確認公設空間不設行動電話設備的敘述，是否排除地下停車空間的 5G 改善要求。
  - 影響：影響地下室通訊涵蓋範圍及設備數量。
  - 建議確認：業主、弱電設計單位、電信業者
  - 來源：PDF 28、34；CAND-00686、CAND-00702
  - 原文：地下室建置 5G 強波器；公設空間不需建置 46 或 56 等行動電話及網路設備。

## 背景與排除紀錄

- [CTX-M1-0001] 一般停車位數量法規不直接形成弱電設備需求。
  - 理由：只有車道辨識、通訊、監測或控制介面部分納入弱電。
  - 來源：PDF 28；CAND-00680

## 轉譯覆核

- 來源卷宗中的每個 evidence group 均已檢查。
"""


class RendererTests(unittest.TestCase):
    @staticmethod
    def write_verified_source(root: Path) -> Path:
        source = root / "weak_current_source.md"
        source.write_text(
            """# 弱電來源包

## 文件資訊

- 來源文件：04-統包需求計畫書整合檔.pdf
- 來源 SHA-256：`36894e15e3fb9ebe3ba4e4c3f69f2625341c8c1976094ae1568aebef63141cd3`
- 已閱讀批次：1 / 1

<!-- screened:SB-001 -->

## 弱電相關來源

- PDF 28：地下室建置 5G 強波器，並設置洩波同軸、E-TAG 與車牌辨識。
""",
            encoding="utf-8",
        )
        return source

    @staticmethod
    def write_verified_receipt(root: Path, source: Path) -> Path:
        receipt = root / "stage1_receipt.json"
        receipt.write_text(
            json.dumps({
                "schema_version": "1.0",
                "stage": "weak_current_source_complete",
                "source_name": "04-統包需求計畫書整合檔.pdf",
                "source_sha256": "36894e15e3fb9ebe3ba4e4c3f69f2625341c8c1976094ae1568aebef63141cd3",
                "pdf_page_count": 194,
                "extraction_batch_count": 39,
                "screening_batch_count": 1,
                "screened_batch_ids": ["SB-001"],
                "screened_evidence_group_count": 3,
                "retained_candidate_id_count": 3,
                "weak_current_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return receipt

    def test_master_parser_and_validator(self) -> None:
        document = render_m1_outputs.parse_master(MASTER)
        render_m1_outputs.validate_master(document, MASTER)
        self.assertEqual(3, len(document.requirements))
        self.assertEqual(1, len(document.reviews))

    def test_three_outputs_and_zip_are_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            master = root / "requirements_master.md"
            master.write_text(MASTER, encoding="utf-8")
            source = self.write_verified_source(root)
            receipt = self.write_verified_receipt(root, source)
            outputs = render_m1_outputs.render_outputs(
                master,
                ROOT / "weak_current_html_template.html",
                root / "delivery",
                source,
                receipt,
            )
            html = (root / "delivery" / "demand_map.html").read_text(encoding="utf-8")
            xmind = (root / "delivery" / "to_xmind.md").read_text(encoding="utf-8")
            handoff = (root / "delivery" / "todo_handoff.md").read_text(encoding="utf-8")
            self.assertEqual(4, len(outputs))
            for term in ("5G 強波器", "洩波同軸電纜", "E-TAG", "車牌辨識"):
                self.assertIn(term, html)
                self.assertIn(term, xmind)
                self.assertIn(term, handoff)
            with zipfile.ZipFile(root / "delivery" / "m1_outputs.zip") as archive:
                self.assertEqual({"demand_map.html", "to_xmind.md", "todo_handoff.md"}, set(archive.namelist()))

    def test_html_uses_fixed_list_and_right_detail(self) -> None:
        document = render_m1_outputs.parse_master(MASTER)
        output = render_m1_outputs.render_html(
            document,
            (ROOT / "weak_current_html_template.html").read_text(encoding="utf-8"),
        )
        self.assertIn('class="tree-workbench"', output)
        self.assertIn('class="detail-pane"', output)
        self.assertIn('id="system-filter"', output)
        self.assertIn('id="detail-design-focus"', output)
        self.assertIn('id="detail-deliverables"', output)
        self.assertIn('class="system-summary"', output)
        self.assertIn('class="group-count">2 筆', output)
        self.assertIn('class="tree-system-list"', output)
        self.assertIn('tree-node level-4', output)
        self.assertIn('id="close-detail"', output)
        self.assertNotIn("drag", output.lower())
        self.assertNotIn("zoom", output.lower())
        ids = re.findall(r'\bid="([^"]+)"', output)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotRegex(output, r"\{\{[A-Z_]+\}\}")

    def test_delivery_requires_weak_current_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            master = root / "requirements_master.md"
            master.write_text(MASTER, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "weak_current_source.md is required"):
                render_m1_outputs.render_outputs(
                    master,
                    ROOT / "weak_current_html_template.html",
                    root / "delivery",
                    root / "missing_weak_current_source.md",
                    root / "missing_stage1_receipt.json",
                )
            self.assertFalse((root / "delivery" / "m1_outputs.zip").exists())

    def test_incomplete_screening_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = self.write_verified_source(root)
            receipt = self.write_verified_receipt(root, source)
            source.write_text(source.read_text(encoding="utf-8").replace("1 / 1", "0 / 1"), encoding="utf-8")
            document = render_m1_outputs.parse_master(MASTER)
            with self.assertRaisesRegex(ValueError, "not every source batch"):
                render_m1_outputs.validate_source_gate(document, source, receipt)

    def test_stage1_receipt_rejects_source_package_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = self.write_verified_source(root)
            receipt = self.write_verified_receipt(root, source)
            source.write_text(source.read_text(encoding="utf-8") + "\n未經收據記錄的變更。\n", encoding="utf-8")
            document = render_m1_outputs.parse_master(MASTER)
            with self.assertRaisesRegex(ValueError, "source hash does not match"):
                render_m1_outputs.validate_source_gate(document, source, receipt)

    def test_large_pdf_receipt_rejects_implausible_single_extraction_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = self.write_verified_source(root)
            receipt = self.write_verified_receipt(root, source)
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            payload["extraction_batch_count"] = 1
            receipt.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            document = render_m1_outputs.parse_master(MASTER)
            with self.assertRaisesRegex(ValueError, "implausible extraction batch coverage"):
                render_m1_outputs.validate_source_gate(document, source, receipt)

    def test_boilerplate_is_rejected(self) -> None:
        bad = MASTER.replace(
            "地下室應建置 5G 強波器，以改善地下空間行動通訊涵蓋。",
            "依來源規格納入 5G 設備選型、配置與介面設計。",
        )
        document = render_m1_outputs.parse_master(bad)
        with self.assertRaisesRegex(ValueError, "prohibited boilerplate"):
            render_m1_outputs.validate_master(document, bad)

    def test_private_topic_for_every_requirement_is_rejected(self) -> None:
        sections = []
        for index in range(1, 6):
            sections.append(
                f"""#### 私人主題 {index}

- 主題說明：這是一個只服務單筆需求的測試主題。
- 主題設計重點：此內容只用來驗證碎片化主題會被拒絕。

- [REQ-M1-{index:04d}] 測試系統應完成第 {index} 項獨立設備需求。
  - 空間：全案
  - 狀態：來源明示
  - 來源：PDF {index}；CAND-{index:05d}
  - 原文：完成第 {index} 項設備需求。
"""
            )
        bad = """# 碎片化測試 | 弱電需求主檔

- 來源文件：test.pdf
- 來源 SHA-256：`abc`
- 產出日期：2026-08-10

## 需求樹

### 測試系統

- 系統摘要：這是一個用來驗證主題分組品質的測試系統。
- 系統設計重點：不得讓每一筆需求各自形成無整合作用的私人主題。
- 主要介面：來源未明示額外介面
- 主要圖說／文件：系統架構圖

""" + "\n".join(sections)
        document = render_m1_outputs.parse_master(bad)
        with self.assertRaisesRegex(ValueError, "private topic"):
            render_m1_outputs.validate_master(document, bad)


if __name__ == "__main__":
    unittest.main()
