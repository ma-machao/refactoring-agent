from pathlib import Path
from typing import Any

from analyzers.project_structure_analyzer import ProjectStructureAnalyzer
from tools.report_tools import write_json_report, write_markdown_report


def run_analyze_project_structure(
    project_root: Path,
) -> tuple[dict[str, Any], Path, Path]:
    analyzer = ProjectStructureAnalyzer(project_root=project_root)
    result = analyzer.analyze()

    json_path = Path("reports/project_structure_graph.json")
    md_path = Path("reports/project_structure_graph.md")

    write_json_report(json_path, result)
    write_markdown_report(md_path, build_markdown(result))

    return result, json_path, md_path


def build_markdown(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Project Structure Graph")
    lines.append("")

    for app in result.get("apps", []):
        lines.append(f"## {app['app']}")
        lines.append("")

        for layer in app.get("layers", []):
            lines.append(f"### {layer['layer']}")
            lines.append("")
            _append_tree(lines, layer["tree"], indent=0)
            lines.append("")

    return "\n".join(lines)


def _append_tree(lines: list[str], tree: list[dict[str, Any]], indent: int) -> None:
    prefix = "  " * indent
    for item in tree:
        if item["type"] == "dir":
            lines.append(f"{prefix}- {item['name']}/")
            _append_tree(lines, item.get("children", []), indent + 1)
        else:
            lines.append(f"{prefix}- {item['name']}")
