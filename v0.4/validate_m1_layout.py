from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


START = "/*__M1_DATA_START__*/"
END = "/*__M1_DATA_END__*/"
REQUIRED_IDS = {
    "tree-panel",
    "details-panel",
    "summary-panel",
    "project-panel",
    "tree-root",
    "detail-root",
    "workspace-resizer",
    "details-list",
    "system-summary-grid",
    "project-info-root",
    "smart-building-root",
}


def normalized_shell(text: str) -> str:
    pattern = re.escape(START) + r".*?" + re.escape(END)
    normalized, count = re.subn(pattern, START + "__LOCKED_DATA__" + END, text, count=1, flags=re.S)
    if count != 1:
        raise ValueError("data marker pair missing")
    return normalized


def extract_data(text: str) -> dict:
    match = re.search(re.escape(START) + r"(.*?)" + re.escape(END), text, flags=re.S)
    if not match:
        raise ValueError("data marker pair missing")
    return json.loads(match.group(1))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify that an M1 HTML output preserves the readable-v2 locked shell.")
    parser.add_argument("--html", required=True, type=Path)
    parser.add_argument("--template", default=Path(__file__).with_name("weak_current_html_template.html"), type=Path)
    args = parser.parse_args()

    html = args.html.read_text(encoding="utf-8")
    template = args.template.read_text(encoding="utf-8")
    errors: list[str] = []

    if normalized_shell(html) != normalized_shell(template):
        errors.append("locked HTML shell differs from template")
    if '<meta name="m1-layout-version" content="readable-v2">' not in html:
        errors.append("layout version missing")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    missing_ids = sorted(REQUIRED_IDS - ids)
    if missing_ids:
        errors.append(f"required ids missing: {missing_ids}")
    if html.count('class="tab-button') != 4:
        errors.append("expected exactly four main tabs")
    if 'role="separator"' not in html or 'aria-orientation="vertical"' not in html:
        errors.append("resizable tree-detail separator missing")
    if "formatSourceLabel" not in html or "source_document_clean\\.md" not in html:
        errors.append("source display normalization missing")
    if "{{" in html or "}}" in html:
        errors.append("unfilled template placeholders found")
    if re.search(r'<(?:script|link)[^>]+(?:src|href)=["\']https?://', html, flags=re.I):
        errors.append("external script or stylesheet found")

    try:
        data = extract_data(html)
        requirement_count = len(data.get("requirements", []))
        system_count = len(data.get("system_summaries", []))
    except Exception as exc:
        errors.append(f"embedded data invalid: {exc}")
        requirement_count = 0
        system_count = 0

    result = {
        "ok": not errors,
        "layout_version": "readable-v2",
        "requirements": requirement_count,
        "systems": system_count,
        "shell_sha256": hashlib.sha256(normalized_shell(html).encode("utf-8")).hexdigest(),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
