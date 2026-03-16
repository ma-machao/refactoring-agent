import json
from pathlib import Path
from typing import Any

from tools.fs_tools import ensure_dir, write_text


def write_json_report(path: Path, data: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_markdown_report(path: Path, content: str) -> None:
    write_text(path, content, encoding="utf-8")
