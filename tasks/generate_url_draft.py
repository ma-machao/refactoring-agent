from pathlib import Path
from typing import Any

from tools.fs_tools import read_text, write_text
from tools.json_tools import read_json
from tools.report_tools import write_markdown_report
from config import TARGET_PROJECT_ROOT


def run_generate_url_draft(
    model_name: str,
    agent_root: Path,
    final_mapping_json: Path,
) -> tuple[str, Path, Path]:
    final_mapping = read_json(final_mapping_json)

    mapping = find_mapping(final_mapping, model_name)
    if mapping is None:
        raise ValueError(f"最终映射中未找到模型: {model_name}")

    target_app = mapping.get("final_target_app")
    target_file = mapping.get("final_target_file")

    if not target_app or not target_file:
        raise ValueError(
            f"模型 {model_name} 的最终映射缺少 final_target_app / final_target_file"
        )

    view_target_file = build_view_target_file(target_file)
    view_draft_path = agent_root / "workspace" / "drafts" / view_target_file
    if not view_draft_path.exists():
        raise ValueError(
            f"缺少 view draft: {view_draft_path}\n"
            f"请先执行 generate-view-draft --model {model_name}"
        )

    url_admin_rel_path = Path("apps") / target_app / "urls" / "admin.py"
    url_output_path = agent_root / "workspace" / "drafts" / url_admin_rel_path
    url_output_path.parent.mkdir(parents=True, exist_ok=True)

    model_snake = snake_name(model_name)
    list_view_name = f"{model_name}ListCreateView"
    detail_view_name = f"{model_name}DetailView"

    path_lines = build_url_path_lines(
        model_snake=model_snake,
        list_view_name=list_view_name,
        detail_view_name=detail_view_name,
    )

    final_code = apply_url_patch(
        agent_root=agent_root,
        url_rel_path=url_admin_rel_path,
        output_path=url_output_path,
        path_lines=path_lines,
    )

    md_path = agent_root / "reports" / "urls" / f"{model_name.lower()}_url_draft.md"
    write_markdown_report(
        md_path,
        build_markdown(
            model_name=model_name,
            target_app=target_app,
            url_rel_path=url_admin_rel_path,
            view_draft_path=view_draft_path,
            path_lines=path_lines,
            final_code=final_code,
        ),
    )

    return final_code, url_output_path, md_path


def find_mapping(
    final_mapping: dict[str, Any],
    model_name: str,
) -> dict[str, Any] | None:
    for item in final_mapping.get("mappings", []):
        if item.get("source_model") == model_name:
            return item
    return None


def build_view_target_file(model_target_file: str) -> Path:
    path = Path(model_target_file)
    parts = list(path.parts)

    if "models" not in parts:
        raise ValueError(f"target_file 不是标准 models 路径: {model_target_file}")

    idx = parts.index("models")
    new_parts = parts[:idx] + ["views", "admin"] + parts[idx + 1 :]
    return Path(*new_parts)


def snake_name(name: str) -> str:
    chars: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            prev = name[i - 1]
            if prev.islower() or (i + 1 < len(name) and name[i + 1].islower()):
                chars.append("_")
        chars.append(ch.lower())
    return "".join(chars)


def build_url_path_lines(
    model_snake: str,
    list_view_name: str,
    detail_view_name: str,
) -> list[str]:
    return [
        f'    path("{model_snake}/", {list_view_name}.as_view()),',
        f'    path("{model_snake}/<int:pk>/", {detail_view_name}.as_view()),',
    ]


def apply_url_patch(
    agent_root: Path,
    url_rel_path: Path,
    output_path: Path,
    path_lines: list[str],
) -> str:
    """
    规则：
    1. 优先基于 draft/admin.py 修改
    2. 否则基于真实项目 apps/<app>/urls/admin.py 修改
    3. 若都不存在，则创建最小 admin.py
    4. 自动避免重复插入
    """
    if output_path.exists():
        base_content = read_text(output_path, encoding="utf-8")
    else:
        source_path = TARGET_PROJECT_ROOT / url_rel_path
        if source_path.exists():
            base_content = read_text(source_path, encoding="utf-8")
        else:
            base_content = build_minimal_admin_url_file()

    merged = merge_url_lines(base_content, path_lines)
    write_text(output_path, merged, encoding="utf-8")
    return merged


def build_minimal_admin_url_file() -> str:
    return (
        "from django.urls import path\n"
        "from ..views import *\n\n"
        "urlpatterns = [\n"
        "]\n"
    )


def merge_url_lines(base_content: str, path_lines: list[str]) -> str:
    """
    只往 urlpatterns 中追加，不重复插入。
    """
    lines = base_content.splitlines()

    existing_text = "\n".join(lines)
    new_lines = [line for line in path_lines if line not in existing_text]

    if not new_lines:
        return base_content if base_content.endswith("\n") else base_content + "\n"

    # 找 urlpatterns = [
    insert_idx = None
    closing_idx = None

    for idx, line in enumerate(lines):
        if "urlpatterns" in line and "[" in line:
            insert_idx = idx + 1
            continue
        if insert_idx is not None and line.strip() == "]":
            closing_idx = idx
            break

    if insert_idx is None or closing_idx is None:
        # 非标准文件，直接重建最小结构
        rebuilt = build_minimal_admin_url_file().splitlines()
        rebuilt = rebuilt[:-1] + new_lines + ["]"]
        return "\n".join(rebuilt) + "\n"

    merged_lines = lines[:closing_idx] + new_lines + lines[closing_idx:]
    return "\n".join(merged_lines) + "\n"


def build_markdown(
    model_name: str,
    target_app: str,
    url_rel_path: Path,
    view_draft_path: Path,
    path_lines: list[str],
    final_code: str,
) -> str:
    lines: list[str] = []

    lines.append(f"# {model_name} URL 草案")
    lines.append("")
    lines.append(f"- 目标 app: `{target_app}`")
    lines.append(f"- 输出文件: `{url_rel_path}`")
    lines.append(f"- 基于 view draft: `{view_draft_path}`")
    lines.append("")

    lines.append("## 新增路由")
    lines.append("")
    for line in path_lines:
        lines.append(f"- `{line.strip()}`")
    lines.append("")

    lines.append("## 最终 admin.py")
    lines.append("")
    lines.append("```python")
    lines.append(final_code.rstrip())
    lines.append("```")
    lines.append("")

    return "\n".join(lines)
