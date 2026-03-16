from pathlib import Path
from typing import Any

from analyzers.relationship_graph_analyzer import RelationshipGraphAnalyzer
from tools.report_tools import write_json_report, write_markdown_report


def run_analyze_relationship_graph(
    db_models_analysis_json: Path,
    final_mapping_json: Path,
    field_semantics_json: Path | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    analyzer = RelationshipGraphAnalyzer(
        db_models_analysis_json=db_models_analysis_json,
        final_mapping_json=final_mapping_json,
        field_semantics_json=field_semantics_json,
    )

    result = analyzer.analyze()

    json_path = Path("reports/relationship_graph.json")
    md_path = Path("reports/relationship_graph.md")

    write_json_report(json_path, result)
    write_markdown_report(md_path, build_markdown(result))

    return result, json_path, md_path


def build_markdown(result: dict[str, Any]) -> str:
    lines: list[str] = []

    lines.append("# Relationship Graph")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    for item in result.get("summary", []):
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Edges")
    lines.append("")
    lines.append("| Source | Field | Relation | Target | Semantic | Target App |")
    lines.append("|---|---|---|---|---|---|")

    for edge in result.get("edges", []):
        lines.append(
            f"| {edge.get('source_model')} "
            f"| {edge.get('field_name')} "
            f"| {edge.get('relation_type')} "
            f"| {edge.get('target_model')} "
            f"| {edge.get('semantic') or '-'} "
            f"| {edge.get('target_app') or '-'} |"
        )

    lines.append("")
    return "\n".join(lines)
