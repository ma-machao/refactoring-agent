from pathlib import Path
from typing import Any

from tools.json_tools import read_json
from tools.report_tools import write_markdown_report


def run_export_project_structure_mermaid(
    project_structure_json: Path,
) -> tuple[str, Path]:
    graph = read_json(project_structure_json)
    mermaid = build_mermaid(graph)

    output_path = Path("reports/project_structure_mermaid.md")
    write_markdown_report(output_path, build_markdown(mermaid))

    return mermaid, output_path


def build_mermaid(graph: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("graph TD")
    lines.append('    ROOT["apps"]')

    for app in graph.get("apps", []):
        app_id = sanitize_id(f"app_{app['app']}")
        lines.append(f'    ROOT --> {app_id}["{app["app"]}"]')

        for layer in app.get("layers", []):
            layer_id = sanitize_id(f"{app['app']}_{layer['layer']}")
            lines.append(f'    {app_id} --> {layer_id}["{layer["layer"]}"]')
            _append_tree_mermaid(lines, layer_id, layer["tree"], prefix=f"{app['app']}_{layer['layer']}")

    return "\n".join(lines)


def _append_tree_mermaid(lines: list[str], parent_id: str, tree: list[dict[str, Any]], prefix: str) -> None:
    for idx, item in enumerate(tree):
        node_id = sanitize_id(f"{prefix}_{idx}_{item['name']}")
        if item["type"] == "dir":
            lines.append(f'    {parent_id} --> {node_id}["{item["name"]}/"]')
            _append_tree_mermaid(lines, node_id, item.get("children", []), prefix=node_id)
        else:
            lines.append(f'    {parent_id} --> {node_id}["{item["name"]}"]')


def sanitize_id(value: str) -> str:
    chars = []
    for ch in value:
        if ch.isalnum():
            chars.append(ch)
        else:
            chars.append("_")
    result = "".join(chars) or "node"
    if result[0].isdigit():
        result = "n_" + result
    return result


def build_markdown(mermaid: str) -> str:
    return f"""# Project Structure Mermaid

```mermaid
{mermaid}
"""
