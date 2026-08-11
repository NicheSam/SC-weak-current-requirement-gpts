#!/usr/bin/env python3
"""Merge page-batch dossiers into one AI-readable source dossier."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


def body(text: str) -> str:
    marker = re.search(r"(?m)^## EG-", text)
    return text[marker.start():].strip() if marker else text.strip()


def prefix_ids(text: str, batch_id: str) -> str:
    return re.sub(r"\b(EG|CAND|CLM|EV)-(\d+)\b", rf"{batch_id}-\1-\2", text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge M1 batch dossiers.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path, nargs="?", default=Path("source_dossier.md"))
    args = parser.parse_args()
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    sections: list[str] = [
        "# 弱電來源卷宗",
        "",
        "> 本檔由頁面批次合併，供 AI 完成工程語意理解與轉譯；批次邊界不是需求邊界。跨批次相鄰頁仍須合併判讀。",
        "",
        "## 文件資訊",
        "",
        f"- 來源文件：{data['source_name']}",
        f"- 來源 SHA-256：`{data['source_sha256']}`",
        f"- PDF 頁數：{data['page_count']}",
        f"- 擷取批次：{len(data['batches'])}",
        "",
    ]
    for batch in data["batches"]:
        dossier = Path(batch["dossier_md"])
        if not dossier.is_file():
            raise FileNotFoundError(f"missing batch dossier: {dossier}")
        sections.extend([
            "---",
            "",
            f"# {batch['batch_id']} | PDF {batch['page_start']}-{batch['page_end']}",
            "",
            prefix_ids(body(dossier.read_text(encoding="utf-8")), batch["batch_id"]),
            "",
        ])
    args.output.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8", newline="\n")
    print(f"PASS: wrote {args.output} | batches={len(data['batches'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
