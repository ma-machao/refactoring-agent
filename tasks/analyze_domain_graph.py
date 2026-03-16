from pathlib import Path
from typing import Any

from analyzers.domain_graph_analyzer import DomainGraphAnalyzer
from tools.report_tools import write_json_report, write_markdown_report


def run_analyze_domain_graph(
    relationship_graph_json: Path,
) -> tuple[dict[str, Any], Path, Path]:

    analyzer = DomainGraphAnalyzer(
        relationship_graph_json=relationship_graph_json
    )

    result = analyzer.analyze()

    json_path = Path("reports/domain_graph.json")
    md_path = Path("reports/domain_graph.md")

    write_json_report(json_path, result)
    write_markdown_report(md_path, build_markdown(result))

    return result, json_path, md_path


def build_markdown(result: dict[str, Any]) -> str:

    lines = []

    lines.append("# Domain Graph")
    lines.append("")

    lines.append("## Domains")
    lines.append("")

    for domain in result.get("domains", []):

        lines.append(f"### {domain['domain']}")
        lines.append("")

        for model in domain["models"]:
            lines.append(f"- {model}")

        lines.append("")

    lines.append("## Cross Domain Relations")
    lines.append("")

    for rel in result.get("cross_domain_relations", []):

        lines.append(
            f"- {rel['source_domain']} → {rel['target_domain']} "
            f"(via {rel['via_model']}.{rel['relation']})"
        )

    return "\n".join(lines)
