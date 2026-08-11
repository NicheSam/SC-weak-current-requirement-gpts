from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

import m1_build_source_dossier


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "tmp" / "pdfs" / "central_market.pdf"
PACK = ROOT / "sandbox" / "md_pipeline_v06" / "input" / "m1_candidates.json"
PILOT = ROOT / "sandbox" / "md_pipeline_v06" / "artifacts" / "pilot_readable_requirements.md"


@unittest.skipUnless(
    PDF.is_file() and PACK.is_file() and PILOT.is_file(),
    "private central-market regression fixtures are not installed",
)
class CentralMarketRegressionTests(unittest.TestCase):
    def test_candidate_pack_matches_actual_pdf(self) -> None:
        data = json.loads(PACK.read_text(encoding="utf-8"))
        digest = hashlib.sha256(PDF.read_bytes()).hexdigest()
        self.assertEqual(digest, data["source_manifest"][0]["sha256"])
        self.assertEqual(194, data["source_manifest"][0]["page_count"])

    def test_real_dossier_and_pilot_preserve_business_scope(self) -> None:
        data = json.loads(PACK.read_text(encoding="utf-8"))
        dossier = m1_build_source_dossier.build_dossier(data)
        pilot = PILOT.read_text(encoding="utf-8")
        # The source OCR preserves the malformed phrase "住戶讀卡威應"; the
        # dossier must retain the recoverable business noun while the AI pilot
        # demonstrates the semantic repair to "住戶感應讀卡".
        for term in ("5G 強波器", "洩波同軸電纜", "E-TAG", "車牌辨識", "住戶讀卡"):
            self.assertIn(term, dossier)

        for term in ("5G 強波器", "洩波同軸電纜", "E-TAG", "車牌辨識", "住戶感應讀卡"):
            self.assertIn(term, pilot)
        self.assertIn("地下室應建置 5G 強波器，以改善地下空間行動通訊涵蓋", pilot)
        self.assertIn("汽車道及機車道均應設置 E-TAG、車牌辨識及住戶感應讀卡功能", pilot)


if __name__ == "__main__":
    unittest.main()
