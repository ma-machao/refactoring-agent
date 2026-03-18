from pathlib import Path
from typing import Any

from analyzers.enum_analyzer import EnumAnalyzer
from tools.report_tools import write_json_report, write_markdown_report


def run_analyze_enums(
    db_models_analysis_json: Path,
    field_semantics_json: Path | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    analyzer = EnumAnalyzer(
        db_models_analysis_json=db_models_analysis_json,
        field_semantics_json=field_semantics_json,
    )

    result = analyzer.analyze()

    json_path = Path("reports/enum_analysis.json")
    md_path = Path("reports/enum_analysis.md")

    write_json_report(json_path, result)
    write_markdown_report(md_path, build_markdown(result))

    return result, json_path, md_path


def build_markdown(result: dict[str, Any]) -> str:
    lines: list[str] = []

    lines.append("# Enum Analysis")
    lines.append("")

    for item in result.get("enums", []):
        lines.append(f"## {item['model']}.{item['field']}")
        lines.append("")
        lines.append(f"- enum_name: `{item['enum_name']}`")
        lines.append(f"- source_constant: `{item['source_constant']}`")
        lines.append(f"- enum_type: `{item['enum_type']}`")
        if item.get("semantic"):
            lines.append(f"- semantic: `{item['semantic']}`")
        lines.append("")
        lines.append("| member | value | label |")
        lines.append("|---|---|---|")
        for choice in item.get("choices", []):
            lines.append(
                f"| {choice['member_name']} | {choice['value']} | {choice['label']} |"
            )
        lines.append("")

    return "\n".join(lines)
