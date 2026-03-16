from pathlib import Path

from analyzers.model_analyzer import ModelAnalysisResult, ModelAnalyzer
from config import REPORTS_DIR
from tools.report_tools import write_json_report, write_markdown_report


def run_analyze_models(project_root: Path, module_name: str) -> tuple[ModelAnalysisResult, Path, Path]:
    analyzer = ModelAnalyzer()
    result = analyzer.analyze(project_root, module_name)

    json_path = REPORTS_DIR / f"{module_name}_models_analysis.json"
    md_path = REPORTS_DIR / f"{module_name}_models_analysis.md"

    write_json_report(json_path, result.model_dump())
    write_markdown_report(md_path, build_models_markdown(result))

    return result, json_path, md_path


def build_models_markdown(result: ModelAnalysisResult) -> str:
    lines: list[str] = []

    lines.append(f"# `{result.module_name}` 模型分析报告")
    lines.append("")
    lines.append(f"- Module 名称: `{result.module_name}`")
    lines.append(f"- Module 路径: `{result.module_path}`")
    lines.append(f"- Model 文件数: `{len(result.model_files)}`")
    lines.append(f"- 模型数量: `{len(result.models)}`")
    lines.append("")

    lines.append("## Model 文件")
    lines.append("")
    if result.model_files:
        for file in result.model_files:
            lines.append(f"- `{file}`")
    else:
        lines.append("- 未发现")
    lines.append("")

    lines.append("## 模型列表")
    lines.append("")
    if not result.models:
        lines.append("- 未识别到模型")
        lines.append("")
    else:
        for model in result.models:
            lines.append(f"### {model.name}")
            lines.append("")
            lines.append(f"- 文件: `{model.file_path}`")
            lines.append(f"- 行号: `{model.start_line}-{model.end_line}`")
            lines.append(f"- 类声明: `{model.raw_class_header}`")
            lines.append("")

            if model.fields:
                lines.append("| 字段名 | 类型 | 关系 | 目标 | choices | null | blank | default |")
                lines.append("|---|---|---|---|---|---|---|---|")
                for field in model.fields:
                    lines.append(
                        f"| {field.name} | {field.field_type} | "
                        f"{field.relation_type or '-'} | {field.relation_target or '-'} | "
                        f"{'Y' if field.has_choices else '-'} | "
                        f"{field.null if field.null is not None else '-'} | "
                        f"{field.blank if field.blank is not None else '-'} | "
                        f"{field.default or '-'} |"
                    )
            else:
                lines.append("- 未识别到字段")
            lines.append("")

            lines.append("#### 原始字段定义")
            lines.append("")
            if model.fields:
                for field in model.fields:
                    lines.append(f"- `{field.raw_line}`")
            else:
                lines.append("- 无")
            lines.append("")

            lines.append("#### Meta")
            lines.append("")
            if model.meta and model.meta.raw_lines:
                lines.append("```python")
                for raw in model.meta.raw_lines:
                    lines.append(raw)
                lines.append("```")
            else:
                lines.append("- 未发现 Meta")
            lines.append("")

    lines.append("## 初步 Django 6 重构建议")
    lines.append("")
    if result.suggestions:
        for idx, item in enumerate(result.suggestions, start=1):
            lines.append(f"{idx}. {item}")
    else:
        lines.append("1. 暂无")
    lines.append("")

    lines.append("## 下一步建议")
    lines.append("")
    lines.append("1. 继续梳理每个模型属于未来哪个新领域模块。")
    lines.append("2. 确认主键、唯一约束、索引、排序规则。")
    lines.append("3. 确认关系字段是否需要 related_name。")
    lines.append("4. 将 legacy choices 迁移为 constants + TextChoices。")
    lines.append("5. 下一阶段可以生成 Django 6 新模型草案。")
    lines.append("")

    return "\n".join(lines)
