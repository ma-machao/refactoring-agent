from pathlib import Path
from typing import Any

from tools.json_tools import read_json
from tools.report_tools import write_markdown_report


def run_export_relationship_graph_mermaid(
    relationship_graph_json: Path,
    model: str | None = None,
) -> tuple[str, Path]:

    graph = read_json(relationship_graph_json)

    if model:
        mermaid = build_model_subgraph(graph, model)
        filename = f"relationship_graph_{model}.md"
    else:
        mermaid = build_full_graph(graph)
        filename = "relationship_graph_mermaid.md"

    output_path = Path("reports") / filename

    write_markdown_report(output_path, build_markdown(mermaid))

    return mermaid, output_path


# --------------------------
# 全图
# --------------------------

def build_full_graph(graph: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("graph TD")

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    for node in nodes:
        node_id = sanitize_id(node.get("model"))
        label = build_label(node)
        lines.append(f'    {node_id}["{label}"]')

    for edge in edges:
        lines.append(build_edge_line(edge))

    return "\n".join(lines)


# --------------------------
# 子图
# --------------------------

def build_model_subgraph(graph: dict[str, Any], model: str) -> str:
    lines: list[str] = []
    lines.append("graph TD")

    edges = graph.get("edges", [])

    related_edges: list[dict[str, Any]] = []
    related_models: set[str] = set()

    for edge in edges:
        if edge["source_model"] == model or edge["target_model"] == model:
            related_edges.append(edge)
            related_models.add(edge["source_model"])
            related_models.add(edge["target_model"])

    # 再扩展一层
    second_edges: list[dict[str, Any]] = []

    for edge in edges:
        if edge["source_model"] in related_models:
            second_edges.append(edge)
            related_models.add(edge["target_model"])

    all_edges = {tuple(e.items()): e for e in related_edges + second_edges}.values()

    for edge in all_edges:
        lines.append(build_edge_line(edge))

    return "\n".join(lines)


# --------------------------
# edge
# --------------------------

def build_edge_line(edge: dict[str, Any]) -> str:

    source = sanitize_id(edge.get("source_model"))
    target = sanitize_id(edge.get("target_model"))

    field = edge.get("field_name", "")
    semantic = edge.get("semantic")

    label = field

    if semantic:
        label += f" ({semantic})"

    return f'    {source} -->|"{label}"| {target}'


# --------------------------
# node label
# --------------------------

def build_label(node: dict[str, Any]) -> str:

    model = node.get("model", "Unknown")
    app = node.get("target_app") or "unknown"
    domain = node.get("target_domain") or ""

    return f"{model}<br/><small>{app}.{domain}</small>"


# --------------------------
# id sanitizer
# --------------------------

def sanitize_id(value: str) -> str:

    chars = []

    for c in value:
        if c.isalnum():
            chars.append(c)
        else:
            chars.append("_")

    result = "".join(chars)

    if result[0].isdigit():
        result = "n_" + result

    return result


# --------------------------
# markdown
# --------------------------

def build_markdown(mermaid: str) -> str:

    return f"""# Relationship Graph
```mermaid
{mermaid}

"""
