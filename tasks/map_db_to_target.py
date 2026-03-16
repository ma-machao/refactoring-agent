from pathlib import Path

from analyzers.domain_mapper import DomainMapper, DomainMappingResult
from config import REPORTS_DIR
from tools.report_tools import write_markdown_report
from tools.json_tools import write_json


def run_map_db_to_target(
    db_models_analysis_json: Path,
    target_blueprint_json: Path,
) -> tuple[DomainMappingResult, Path, Path]:
    mapper = DomainMapper(target_blueprint_json)
    result = mapper.map_db_models(db_models_analysis_json)

    json_path = REPORTS_DIR / "db_to_target_mapping.json"
    md_path = REPORTS_DIR / "db_to_target_mapping.md"

    write_json(json_path, result.model_dump())
    write_markdown_report(md_path, build_mapping_markdown(result))

    return result, json_path, md_path


def build_mapping_markdown(result: DomainMappingResult) -> str:
    lines: list[str] = []

    lines.append("# db -> target 结构映射报告")
    lines.append("")
    lines.append(f"- 来源模块: `{result.source_module}`")
    lines.append(f"- 模型总数: `{result.total_models}`")
    lines.append(f"- 成功映射数: `{len(result.mappings)}`")
    lines.append(f"- 未映射数: `{len(result.unmapped_models)}`")
    lines.append("")

    lines.append("## 映射摘要")
    lines.append("")
    if result.summary:
        for item in result.summary:
            lines.append(f"- {item}")
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("## 详细映射")
    lines.append("")
    if result.mappings:
        lines.append("| 旧模型 | 旧文件 | 目标 app | 目标 domain | 目标文件 | 动作 | 置信度 |")
        lines.append("|---|---|---|---|---|---|---|")
        for item in result.mappings:
            lines.append(
                f"| {item.source_model} | `{item.source_file}` | "
                f"{item.suggested_app} | {item.suggested_domain} | "
                f"`{item.suggested_model_file}` | {item.action} | {item.confidence} |"
            )
    else:
        lines.append("- 暂无")
    lines.append("")

    lines.append("## 每个模型的映射理由")
    lines.append("")
    if result.mappings:
        for item in result.mappings:
            lines.append(f"### {item.source_model}")
            lines.append("")
            lines.append(f"- 来源文件: `{item.source_file}`")
            lines.append(f"- 建议目标: `{item.suggested_model_file}`")
            lines.append(f"- 动作: `{item.action}`")
            lines.append(f"- 置信度: `{item.confidence}`")
            lines.append("- 理由:")
            for reason in item.reasons:
                lines.append(f"  - {reason}")
            lines.append("")
    else:
        lines.append("- 暂无")
        lines.append("")

    lines.append("## 未映射模型")
    lines.append("")
    if result.unmapped_models:
        for name in result.unmapped_models:
            lines.append(f"- `{name}`")
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("## 下一步建议")
    lines.append("")
    lines.append("1. 先人工确认低置信度或未映射模型。")
    lines.append("2. 再补充更细的领域规则，例如 DirectLink、Router、LoadBalancer、DatabaseSnapshot。")
    lines.append("3. 确认后即可进入 Django 6 模型草案生成阶段。")
    lines.append("")

    return "\n".join(lines)
