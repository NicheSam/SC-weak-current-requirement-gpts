from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


START = "/*__M1_DATA_START__*/"
END = "/*__M1_DATA_END__*/"
REQUIRED_REQUIREMENT_FIELDS = {
    "id",
    "navTitle",
    "system",
    "group",
    "space",
    "title",
    "source",
    "evidence",
    "conditions",
    "status",
    "review",
    "docs",
}
VALID_STATUSES = {"clear", "review", "interface"}


def require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


def validate_data(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("root must be an object")

    project = data.get("project")
    if not isinstance(project, dict):
        raise ValueError("project must be an object")
    require_text(project.get("name"), "project.name")
    require_text(project.get("source"), "project.source")

    requirements = data.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise ValueError("requirements must be a non-empty array")

    ids: set[str] = set()
    systems: set[str] = set()
    for index, item in enumerate(requirements):
        if not isinstance(item, dict):
            raise ValueError(f"requirements[{index}] must be an object")
        missing = REQUIRED_REQUIREMENT_FIELDS.difference(item)
        if missing:
            raise ValueError(f"requirements[{index}] missing fields: {sorted(missing)}")
        for field in REQUIRED_REQUIREMENT_FIELDS:
            require_text(item.get(field), f"requirements[{index}].{field}")
        item_id = item["id"]
        if item_id in ids:
            raise ValueError(f"duplicate requirement id: {item_id}")
        ids.add(item_id)
        systems.add(item["system"])
        if item["status"] not in VALID_STATUSES:
            raise ValueError(f"requirements[{index}].status must be clear, review, or interface")

    summaries = data.get("system_summaries")
    if not isinstance(summaries, list):
        raise ValueError("system_summaries must be an array")
    summary_systems: set[str] = set()
    for index, item in enumerate(summaries):
        if not isinstance(item, dict):
            raise ValueError(f"system_summaries[{index}] must be an object")
        system = require_text(item.get("system"), f"system_summaries[{index}].system")
        require_text(item.get("summary"), f"system_summaries[{index}].summary")
        if system in summary_systems:
            raise ValueError(f"duplicate system summary: {system}")
        summary_systems.add(system)
    if systems != summary_systems:
        missing = sorted(systems - summary_systems)
        extra = sorted(summary_systems - systems)
        raise ValueError(f"system summaries must match requirements; missing={missing}, extra={extra}")

    for field in ("project_info", "smart_building"):
        if not isinstance(data.get(field, []), list):
            raise ValueError(f"{field} must be an array")

    return data


def render(template: str, data: dict[str, Any]) -> str:
    if template.count(START) != 1 or template.count(END) != 1:
        raise ValueError("template data markers are missing or duplicated")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    pattern = re.escape(START) + r".*?" + re.escape(END)
    return re.sub(pattern, START + payload + END, template, count=1, flags=re.S)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inject AI-authored M1 content into the locked readable-v2 HTML template.")
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--template", default=Path(__file__).with_name("weak_current_html_template.html"), type=Path)
    parser.add_argument("--output", default=Path("demand_map.html"), type=Path)
    args = parser.parse_args()

    data = validate_data(json.loads(args.data.read_text(encoding="utf-8")))
    html = render(args.template.read_text(encoding="utf-8"), data)
    args.output.write_text(html, encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(args.output), "requirements": len(data["requirements"]), "systems": len(data["system_summaries"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
