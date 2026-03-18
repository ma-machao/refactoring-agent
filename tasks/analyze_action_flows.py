from pathlib import Path

from analyzers.action_flow_analyzer import ActionFlowAnalyzer
from tools.report_tools import write_json_report, write_markdown_report


def run_analyze_action_flows(
    project_root: Path,
    model_name: str,
):
    analyzer = ActionFlowAnalyzer(project_root)

    result = analyzer.analyze(model_name)

    output_json = Path(f"reports/{model_name.lower()}_action_flows.json")
    output_md = Path(f"reports/{model_name.lower()}_action_flows.md")

    write_json_report(output_json, result)
    write_markdown_report(output_md, build_markdown(result))

    return result, output_json, output_md


def build_markdown(result: dict) -> str:
    lines = []

    lines.append(f"# {result['model']} Action Flows")
    lines.append("")

    for action in result["actions"]:
        lines.append(f"## {action['name']}")
        lines.append("")
        lines.append(f"关键词: {', '.join(action['keywords'])}")
        lines.append("")

        lines.append("### 使用位置")
        for usage in action["usages"][:5]:
            lines.append(f"- {usage['file']}")
        lines.append("")

        lines.append("### 状态变化")
        for s in action["state_changes"][:5]:
            lines.append(f"- {s}")
        lines.append("")

    return "\n".join(lines)
