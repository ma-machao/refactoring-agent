from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from tasks.analyze_models import run_analyze_models
from tasks.scan_project import run_scan_project
from tasks.map_db_to_target import run_map_db_to_target
from tasks.llm_review_mapping import run_llm_review_db_mapping
from tasks.merge_final_mapping import run_merge_final_mapping
from tasks.generate_django6_model_draft import run_generate_django6_model_draft
from tasks.analyze_semantics import run_semantic_analysis
from tasks.analyze_relationship_graph import run_analyze_relationship_graph
from tasks.export_relationship_graph_mermaid import run_export_relationship_graph_mermaid
from tasks.analyze_domain_graph import run_analyze_domain_graph
from tasks.analyze_project_structure import run_analyze_project_structure
from tasks.export_project_structure_mermaid import run_export_project_structure_mermaid


app = typer.Typer(
    help="""
Legacy Django Refactor Agent

用于分析 legacy Django 项目并辅助重构为新架构。

典型工作流程：

1. 扫描 legacy 项目
   scan

2. 分析 legacy 模型
   analyze-models

3. 映射 legacy db 模型到 target 架构
   map-db-to-target

4. 使用 LLM 复核映射
   llm-review-db-mapping
"""
)

console = Console()


@app.command("scan")
def scan_project(
    project: str = typer.Option(
        ...,
        "--project",
        "-p",
        help="Legacy Django 项目根目录",
    ),
):
    """
    扫描 legacy Django 项目结构。

    输出：
    - Python 文件统计
    - template 文件统计
    - legacy module 列表
    - settings.py / urls.py 位置

    生成报告：
    reports/project_scan.json
    reports/project_scan.md
    """

    project_root = Path(project).expanduser().resolve()

    if not project_root.exists():
        console.print(f"[red]项目路径不存在: {project_root}[/red]")
        raise typer.Exit(code=1)

    if not project_root.is_dir():
        console.print(f"[red]项目路径不是目录: {project_root}[/red]")
        raise typer.Exit(code=1)

    result, json_path, md_path = run_scan_project(project_root)

    console.print("[green]项目扫描完成[/green]")
    console.print(f"JSON 报告: {json_path}")
    console.print(f"Markdown 报告: {md_path}")
    console.print()

    table = Table(title="扫描摘要")
    table.add_column("项目")
    table.add_column("值")

    table.add_row("项目根目录", result.project_root)
    table.add_row("Python 文件数", str(result.total_python_files))
    table.add_row("模板文件数", str(result.total_template_files))
    table.add_row("Legacy 模块数", str(len(result.legacy_modules)))
    table.add_row("settings.py 数量", str(len(result.settings_files)))
    table.add_row("urls.py 数量", str(len(result.url_files)))

    console.print(table)


@app.command("analyze-models")
def analyze_models(
    project: str = typer.Option(
        ...,
        "--project",
        "-p",
        help="Legacy Django 项目根目录",
    ),
    module_name: str = typer.Option(
        ...,
        "--module",
        help="要分析的 legacy module 名称，例如 db / asset / network",
    ),
):
    """
    分析指定 module 中的 Django models。

    提取：
    - 模型名称
    - 字段
    - 关系字段
    - Meta 信息

    生成报告：
    reports/db_models_analysis.json
    reports/db_models_analysis.md
    """

    project_root = Path(project).expanduser().resolve()

    if not project_root.exists():
        console.print(f"[red]项目路径不存在: {project_root}[/red]")
        raise typer.Exit(code=1)

    if not project_root.is_dir():
        console.print(f"[red]项目路径不是目录: {project_root}[/red]")
        raise typer.Exit(code=1)

    try:
        result, json_path, md_path = run_analyze_models(project_root, module_name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]模型分析完成[/green]")
    console.print(f"JSON 报告: {json_path}")
    console.print(f"Markdown 报告: {md_path}")
    console.print()

    table = Table(title="模型分析摘要")
    table.add_column("项目")
    table.add_column("值")

    table.add_row("Module", result.module_name)
    table.add_row("Module 路径", result.module_path)
    table.add_row("Model 文件数", str(len(result.model_files)))
    table.add_row("模型数量", str(len(result.models)))

    relation_count = sum(1 for m in result.models for f in m.fields if f.is_relation)
    field_count = sum(len(m.fields) for m in result.models)

    table.add_row("字段总数", str(field_count))
    table.add_row("关系字段数", str(relation_count))

    console.print(table)


@app.command("map-db-to-target")
def map_db_to_target(
    project: str = typer.Option(
        ...,
        "--project",
        "-p",
        help="Legacy Django 项目根目录",
    ),
    target: str = typer.Option(
        ...,
        "--target",
        help="Target 架构 blueprint JSON 文件路径",
    ),
):
    """
    将 legacy db models 映射到 target 架构。

    输入：
    reports/db_models_analysis.json
    target_blueprint.json

    输出：
    reports/db_to_target_mapping.json
    reports/db_to_target_mapping.md
    """

    project_root = Path(project).expanduser().resolve()
    target_blueprint = Path(target).expanduser().resolve()

    if not project_root.exists():
        console.print(f"[red]项目路径不存在: {project_root}[/red]")
        raise typer.Exit(code=1)

    if not target_blueprint.exists():
        console.print(f"[red]target blueprint 不存在: {target_blueprint}[/red]")
        raise typer.Exit(code=1)

    db_models_analysis_json = Path("reports/db_models_analysis.json").resolve()
    if not db_models_analysis_json.exists():
        console.print("[red]缺少 reports/db_models_analysis.json，请先执行 analyze-models --module db[/red]")
        raise typer.Exit(code=1)

    result, json_path, md_path = run_map_db_to_target(
        db_models_analysis_json=db_models_analysis_json,
        target_blueprint_json=target_blueprint,
    )

    console.print("[green]db -> target 映射完成[/green]")
    console.print(f"JSON 报告: {json_path}")
    console.print(f"Markdown 报告: {md_path}")
    console.print()

    table = Table(title="db -> target 映射摘要")
    table.add_column("项目")
    table.add_column("值")

    table.add_row("来源模块", result.source_module)
    table.add_row("模型总数", str(result.total_models))
    table.add_row("成功映射数", str(len(result.mappings)))
    table.add_row("未映射数", str(len(result.unmapped_models)))

    console.print(table)


@app.command("analyze-semantics")
def analyze_semantics():

    result, path = run_semantic_analysis(
        db_models_analysis_json=Path("reports/db_models_analysis.json"),
        project_rules_json=Path("workspace/project_rules.json"),
    )

    console.print("[green]字段语义分析完成[/green]")
    console.print(f"输出: {path}")


@app.command("analyze-relationship-graph")
def analyze_relationship_graph():
    result, json_path, md_path = run_analyze_relationship_graph(
        db_models_analysis_json=Path("reports/db_models_analysis.json"),
        final_mapping_json=Path("reports/db_to_target_mapping_final.json"),
        field_semantics_json=Path("reports/field_semantics.json"),
    )

    console.print("[green]关系图分析完成[/green]")
    console.print(f"JSON: {json_path}")
    console.print(f"Markdown: {md_path}")


@app.command("llm-review-db-mapping")
def llm_review_db_mapping(
    target: str = typer.Option(
        ...,
        "--target",
        help="target blueprint JSON 文件路径",
    ),
    limit: int = typer.Option(
        None,
        "--limit",
        help="限制复核模型数量（调试用，例如 --limit 2）",
    ),
):
    """
    使用 LLM 复核 db -> target 映射结果。

    输入：
    reports/db_models_analysis.json
    reports/db_to_target_mapping.json
    target_blueprint.json

    输出：
    reports/db_to_target_mapping_review.json
    reports/db_to_target_mapping_review.md

    示例：

    只复核 2 个模型（调试）：
    python main.py llm-review-db-mapping --target workspace/target_blueprint.json --limit 2
    """

    target_blueprint = Path(target).expanduser().resolve()
    db_models_analysis_json = Path("reports/db_models_analysis.json").resolve()
    db_to_target_mapping_json = Path("reports/db_to_target_mapping.json").resolve()

    if not target_blueprint.exists():
        console.print(f"[red]target blueprint 不存在: {target_blueprint}[/red]")
        raise typer.Exit(code=1)

    if not db_models_analysis_json.exists():
        console.print("[red]缺少 reports/db_models_analysis.json，请先执行 analyze-models --module db[/red]")
        raise typer.Exit(code=1)

    if not db_to_target_mapping_json.exists():
        console.print("[red]缺少 reports/db_to_target_mapping.json，请先执行 map-db-to-target[/red]")
        raise typer.Exit(code=1)

    try:
        result, json_path, md_path = run_llm_review_db_mapping(
            db_models_analysis_json=db_models_analysis_json,
            db_to_target_mapping_json=db_to_target_mapping_json,
            target_blueprint_json=target_blueprint,
            limit=limit,
        )
    except Exception as exc:
        console.print(f"[red]LLM 复核失败: {exc}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]LLM 映射复核完成[/green]")
    console.print(f"JSON 报告: {json_path}")
    console.print(f"Markdown 报告: {md_path}")
    console.print()

    table = Table(title="LLM 复核摘要")
    table.add_column("项目")
    table.add_column("值")

    table.add_row("复核条目数", str(len(result.get("reviews", []))))
    table.add_row("全局建议数", str(len(result.get("global_suggestions", []))))

    console.print(table)


@app.command("merge-final-mapping")
def merge_final_mapping():
    """
    合并规则映射与 LLM 复核结果，生成最终映射文件。

    输出：
    reports/db_to_target_mapping_final.json
    reports/db_to_target_mapping_final.md
    """
    mapping_json = Path("reports/db_to_target_mapping.json").resolve()
    review_json = Path("reports/db_to_target_mapping_review.json").resolve()

    if not mapping_json.exists():
        console.print("[red]缺少 reports/db_to_target_mapping.json，请先执行 map-db-to-target[/red]")
        raise typer.Exit(code=1)

    if not review_json.exists():
        console.print("[red]缺少 reports/db_to_target_mapping_review.json，请先执行 llm-review-db-mapping[/red]")
        raise typer.Exit(code=1)

    result, json_path, md_path = run_merge_final_mapping(mapping_json, review_json)

    console.print("[green]最终映射生成完成[/green]")
    console.print(f"JSON 报告: {json_path}")
    console.print(f"Markdown 报告: {md_path}")
    console.print()

    table = Table(title="最终映射摘要")
    table.add_column("项目")
    table.add_column("值")
    table.add_row("模型总数", str(result.get("total_models", 0)))
    table.add_row("LLM复核覆盖数", str(result.get("reviewed_count", 0)))
    console.print(table)


@app.command("export-relationship-graph-mermaid")
def export_relationship_graph_mermaid(
    model: str | None = typer.Option(None, "--model", help="只导出某个模型关系图"),
):
    relationship_graph_json = Path("reports/relationship_graph.json")

    if not relationship_graph_json.exists():
        console.print("[red]缺少 reports/relationship_graph.json[/red]")
        raise typer.Exit(code=1)

    mermaid, output_path = run_export_relationship_graph_mermaid(
        relationship_graph_json=relationship_graph_json,
        model=model,
    )

    console.print("[green]Mermaid 图生成完成[/green]")
    console.print(f"输出: {output_path}")


@app.command("analyze-domain-graph")
def analyze_domain_graph():

    result, json_path, md_path = run_analyze_domain_graph(
        relationship_graph_json=Path("reports/relationship_graph.json"),
    )

    console.print("[green]Domain Graph 生成完成[/green]")
    console.print(f"JSON: {json_path}")
    console.print(f"Markdown: {md_path}")


@app.command("analyze-project-structure")
def analyze_project_structure(
    project: str = typer.Option(..., "--project", "-p", help="新项目根目录"),
):
    project_root = Path(project).expanduser().resolve()

    result, json_path, md_path = run_analyze_project_structure(project_root)

    console.print("[green]Project Structure Graph 完成[/green]")
    console.print(f"JSON: {json_path}")
    console.print(f"Markdown: {md_path}")


@app.command("export-project-structure-mermaid")
def export_project_structure_mermaid():
    structure_json = Path("reports/project_structure_graph.json")

    if not structure_json.exists():
        console.print("[red]缺少 reports/project_structure_graph.json，请先执行 analyze-project-structure[/red]")
        raise typer.Exit(code=1)

    mermaid, path = run_export_project_structure_mermaid(structure_json)

    console.print("[green]Project Structure Mermaid 完成[/green]")
    console.print(path)


@app.command("generate-django6-model-draft")
def generate_django6_model_draft(
    legacy_project: str = typer.Option(..., "--project", help="旧项目根目录"),
    model: str = typer.Option(..., "--model", help="要生成草案的 legacy 模型名，例如 Region"),
    target: str = typer.Option(..., "--target", help="target blueprint JSON 文件路径（相对于 agent 项目或绝对路径）"),
):
    """
    根据最终映射结果，为单个 legacy 模型生成 Django 6 模型草案。

    示例：
    python main.py generate-django6-model-draft \\
        --project /Users/machao/Desktop/old_nexus \\
        --model ActionLog \\
        --target workspace/target_blueprint.json
    """
    legacy_project_root = Path(legacy_project).expanduser().resolve()
    agent_root = Path(__file__).resolve().parent

    target_path = Path(target).expanduser()
    if target_path.is_absolute():
        target_blueprint = target_path.resolve()
    else:
        target_blueprint = (agent_root / target_path).resolve()

    db_models_analysis_json = (agent_root / "reports" / "db_models_analysis.json").resolve()
    final_mapping_json = (agent_root / "reports" / "db_to_target_mapping_final.json").resolve()

    if not legacy_project_root.exists():
        console.print(f"[red]旧项目路径不存在: {legacy_project_root}[/red]")
        raise typer.Exit(code=1)

    if not legacy_project_root.is_dir():
        console.print(f"[red]旧项目路径不是目录: {legacy_project_root}[/red]")
        raise typer.Exit(code=1)

    if not target_blueprint.exists():
        console.print(f"[red]target blueprint 不存在: {target_blueprint}[/red]")
        raise typer.Exit(code=1)

    if not db_models_analysis_json.exists():
        console.print("[red]缺少 reports/db_models_analysis.json，请先执行 analyze-models --module db[/red]")
        raise typer.Exit(code=1)

    if not final_mapping_json.exists():
        console.print("[red]缺少 reports/db_to_target_mapping_final.json，请先执行 merge-final-mapping[/red]")
        raise typer.Exit(code=1)

    try:
        _, output_path, md_path = run_generate_django6_model_draft(
            model_name=model,
            legacy_project_root=legacy_project_root,
            agent_root=agent_root,
            db_models_analysis_json=db_models_analysis_json,
            final_mapping_json=final_mapping_json,
            target_blueprint_json=target_blueprint,
        )
    except Exception as exc:
        console.print(f"[red]生成模型草案失败: {exc}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]Django 6 模型草案生成完成[/green]")
    console.print(f"输出文件: {output_path}")
    console.print(f"说明文档: {md_path}")


if __name__ == "__main__":
    app()
