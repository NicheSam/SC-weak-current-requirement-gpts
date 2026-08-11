from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class KnowledgeContractTests(unittest.TestCase):
    def test_prompts_use_two_simple_ai_owned_stages(self) -> None:
        for name in ("gpt_instructions_weak_current_html.txt", "gpts_prompt_human_html.txt"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("weak_current_source.md", text)
            self.assertIn("stage1_receipt.json", text)
            self.assertIn("不得單獨附上 demand_map.html", text)
            self.assertIn("requirements_master.md", text)
            self.assertIn("不得要求使用者", text)
            self.assertIn("舊版", text)
            self.assertIn("reviewed-pages", text)
            self.assertIn("reviewed-groups", text)
            self.assertIn("疑似相關", text)
            self.assertNotIn("translation_ledger.md", text)
            self.assertNotIn("coverage:EGRP", text)
            self.assertNotIn("m1_scope_select.py", text)
            self.assertNotIn("m1_semantic_freeze.py", text)
            self.assertNotIn("validate_m1_resume.py", text)
        instructions = (ROOT / "gpt_instructions_weak_current_html.txt").read_text(encoding="utf-8")
        self.assertIn("--run-next", instructions)
        self.assertIn("--vision-transcriptions", instructions)
        self.assertIn("pending 影像區", instructions)
        self.assertIn("群組輪廓", instructions)
        self.assertIn("只重讀疑似漏項的批次", instructions)
        self.assertIn("不得摘要或合併不同義務", instructions)
        self.assertIn("設備規格表", instructions)
        self.assertIn("語意覆蓋複核", instructions)

        human_prompt = (ROOT / "gpts_prompt_human_html.txt").read_text(encoding="utf-8")
        self.assertIn("不得摘要或合併不同義務", human_prompt)
        self.assertIn("語意覆蓋複核", human_prompt)
        self.assertIn("m1_prepare_batches.py", human_prompt)
        self.assertIn("--batch-pages 5", human_prompt)
        self.assertIn("不得由 AI 手寫", human_prompt)

        dossier_builder = (ROOT / "m1_build_source_dossier.py").read_text(encoding="utf-8")
        self.assertIn("不得摘要或合併不同義務", dossier_builder)
        self.assertIn("設備規格表", dossier_builder)

        extractor = (ROOT / "m1_extract_source.py").read_text(encoding="utf-8")
        self.assertNotIn("run_semantic_freeze", extractor)
        self.assertIn("review_source_evidence", extractor)

    def test_rules_have_one_control_flow(self) -> None:
        usage = (ROOT / "00_使用說明.md").read_text(encoding="utf-8")
        continuation = (ROOT / "12_M1雙階段續接資料規則.md").read_text(encoding="utf-8")
        classification = (ROOT / "03_弱電系統分類與轉譯規則.md").read_text(encoding="utf-8")
        batch_runner = (ROOT / "m1_prepare_batches.py").read_text(encoding="utf-8")
        self.assertIn("預設兩階段在上傳回合連續完成", continuation)
        self.assertIn("weak_current_source.md", continuation)
        self.assertIn("stage1_receipt.json", continuation)
        self.assertNotIn("--start-background", usage + continuation)
        self.assertNotIn("--start-background", batch_runner)
        self.assertNotIn("--background-worker", batch_runner)
        self.assertNotIn("BACKGROUND_STARTED", batch_runner)
        self.assertNotIn("--run-complete", batch_runner)
        self.assertIn("需求", usage)
        self.assertIn("2–8 筆", classification)
        self.assertIn("renderer 只負責呈現", classification)

    def test_required_runtime_files_exist(self) -> None:
        for name in (
            "m1_extract_source.py",
            "m1_build_source_dossier.py",
            "render_m1_outputs.py",
            "requirements_master_template.md",
            "weak_current_html_template.html",
        ):
            self.assertTrue((ROOT / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
