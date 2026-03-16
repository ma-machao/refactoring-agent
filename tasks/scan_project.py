from pathlib import Path

from analyzers.project_scanner import ProjectScanner, ProjectScanResult
from config import REPORTS_DIR
from tools.report_tools import write_json_report, write_markdown_report


def run_scan_project(project_root: Path) -> tuple[ProjectScanResult, Path, Path]:
    scanner = ProjectScanner()
    result = scanner.scan(project_root)

    json_path = REPORTS_DIR / "project_overview.json"
    md_path = REPORTS_DIR / "project_overview.md"

    write_json_report(json_path, result.model_dump())
    write_markdown_report(md_path, build_project_markdown(result))

    return result, json_path, md_path


def build_project_markdown(result: ProjectScanResult) -> str:
    lines: list[str] = []

    lines.append("# Legacy 项目概览")
    lines.append("")
    lines.append(f"- 项目根目录: `{result.project_root}`")
    lines.append(f"- Python 文件数量: `{result.total_python_files}`")
    lines.append(f"- 模板文件数量: `{result.total_template_files}`")
    lines.append("")

    lines.append("## 关键入口文件")
    lines.append("")
    lines.append(f"- manage.py: {format_list_inline(result.manage_files)}")
    lines.append(f"- settings.py: {format_list_inline(result.settings_files)}")
    lines.append(f"- urls.py: {format_list_inline(result.url_files)}")
    lines.append(f"- wsgi.py: {format_list_inline(result.wsgi_files)}")
    lines.append(f"- requirements: {format_list_inline(result.requirements_files)}")
    lines.append("")

    lines.append("## Template 目录")
    lines.append("")
    if result.template_dirs:
        for item in result.template_dirs:
            lines.append(f"- `{item}`")
    else:
        lines.append("- 未发现")
    lines.append("")

    lines.append("## Legacy 模块识别")
    lines.append("")
    if result.legacy_modules:
        lines.append("| 模块 | 路径 | 类型 | 说明 | 识别信号 |")
        lines.append("|---|---|---|---|---|")
        for module in result.legacy_modules:
            signals = ", ".join(module.signals) if module.signals else "-"
            lines.append(
                f"| {module.name} | `{module.path}` | {module.module_type} | {module.description} | {signals} |"
            )
    else:
        lines.append("- 未识别到 legacy 模块")
    lines.append("")

    lines.append("## Python 文件样本")
    lines.append("")
    if result.python_files_sample:
        for item in result.python_files_sample:
            lines.append(f"- `{item}`")
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("## Template 文件样本")
    lines.append("")
    if result.template_files_sample:
        for item in result.template_files_sample:
            lines.append(f"- `{item}`")
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("## 初步重构建议")
    lines.append("")
    lines.append("1. 先将旧项目理解为 legacy monolith，而不是多个标准 Django app。")
    lines.append("2. 优先分析 `db` 模块，梳理核心领域模型与未来新系统的领域拆分关系。")
    lines.append("3. 再分析 `sysadmin`，梳理 controllers / forms / templates 到 Django API + Vue3 的映射。")
    lines.append("4. 然后分析 `api`，梳理旧外部接口到 DRF 的迁移策略。")
    lines.append("5. 最后处理 `hyperviser` 和 `jobd` 这类服务层、任务层代码。")
    lines.append("")

    return "\n".join(lines)


def format_list_inline(items: list[str]) -> str:
    if not items:
        return "未发现"
    return ", ".join(f"`{item}`" for item in items)
