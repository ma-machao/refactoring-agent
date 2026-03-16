import json
from pathlib import Path
from typing import Any

from config import TARGET_PROJECT_ROOT
from llm.client import LLMClient
from tools.fs_tools import read_text
from tools.json_tools import read_json
from tools.report_tools import write_markdown_report


def run_generate_serializer_draft(
    model_name: str,
    agent_root: Path,
    final_mapping_json: Path,
    project_structure_json: Path,
) -> tuple[str, Path, Path]:
    final_mapping = read_json(final_mapping_json)
    project_structure = read_json(project_structure_json)

    mapping = find_mapping(final_mapping, model_name)
    if mapping is None:
        raise ValueError(f"最终映射中未找到模型: {model_name}")

    target_app = mapping.get("final_target_app")
    target_file = mapping.get("final_target_file")

    if not target_app or not target_file:
        raise ValueError(
            f"模型 {model_name} 的最终映射缺少 final_target_app / final_target_file"
        )

    model_draft_path = agent_root / "workspace" / "drafts" / target_file
    if not model_draft_path.exists():
        raise ValueError(
            f"缺少 model draft: {model_draft_path}\n"
            f"请先执行 generate-django6-model-draft --model {model_name}"
        )

    model_code = read_text(model_draft_path, encoding="utf-8")

    serializer_target_file = build_serializer_target_file(target_file)
    serializer_output_path = agent_root / "workspace" / "drafts" / serializer_target_file
    serializer_output_path.parent.mkdir(parents=True, exist_ok=True)

    reference_serializers = collect_reference_serializers(
        target_app=target_app,
        project_structure=project_structure,
        max_files=4,
        max_chars_per_file=4000,
    )

    llm = LLMClient()

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(
        model_name=model_name,
        target_app=target_app,
        target_file=serializer_target_file,
        model_code=model_code,
        reference_serializers=reference_serializers,
    )

    raw = llm.complete(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.0,
        max_tokens=4000,
        timeout=120,
    )

    design_text, code = split_design_and_code(raw)

    if not code.strip():
        raise ValueError(f"LLM 未生成有效 serializer 代码。\n原始输出:\n{raw}")

    serializer_output_path.write_text(code, encoding="utf-8")

    md_path = agent_root / "reports/serializers" / f"{model_name.lower()}_serializer_draft.md"
    write_markdown_report(
        md_path,
        build_markdown(
            model_name=model_name,
            target_app=target_app,
            target_file=serializer_target_file,
            model_draft_path=model_draft_path,
            reference_serializers=reference_serializers,
            design_text=design_text,
            code=code,
        ),
    )

    return code, serializer_output_path, md_path


def find_mapping(
    final_mapping: dict[str, Any],
    model_name: str,
) -> dict[str, Any] | None:
    for item in final_mapping.get("mappings", []):
        if item.get("source_model") == model_name:
            return item
    return None


def build_serializer_target_file(model_target_file: str) -> Path:
    """
    apps/compute/models/ssh_public_key.py
    -> apps/compute/serializers/admin/ssh_public_key.py
    """
    path = Path(model_target_file)
    parts = list(path.parts)

    if "models" not in parts:
        raise ValueError(f"target_file 不是标准 models 路径: {model_target_file}")

    idx = parts.index("models")
    new_parts = parts[:idx] + ["serializers", "admin"] + parts[idx + 1 :]
    return Path(*new_parts)


def collect_reference_serializers(
    target_app: str,
    project_structure: dict[str, Any],
    max_files: int = 4,
    max_chars_per_file: int = 4000,
) -> list[dict[str, Any]]:
    """
    优先收集：
    1. 同 app 下 serializers/admin/*.py
    2. core 下 serializers/admin/*.py
    """
    references: list[dict[str, Any]] = []
    apps = project_structure.get("apps", [])

    references.extend(
        collect_admin_serializer_files_from_app(
            apps=apps,
            app_name=target_app,
            max_chars_per_file=max_chars_per_file,
        )
    )

    if target_app != "core":
        references.extend(
            collect_admin_serializer_files_from_app(
                apps=apps,
                app_name="core",
                max_chars_per_file=max_chars_per_file,
            )
        )

    dedup: dict[str, dict[str, Any]] = {}
    for item in references:
        dedup[item["path"]] = item

    result = list(dedup.values())
    result.sort(key=lambda x: x["path"])

    return result[:max_files]


def collect_admin_serializer_files_from_app(
    apps: list[dict[str, Any]],
    app_name: str,
    max_chars_per_file: int,
) -> list[dict[str, Any]]:
    for app in apps:
        if app.get("app") != app_name:
            continue

        for layer in app.get("layers", []):
            if layer.get("layer") != "serializers":
                continue

            return scan_admin_serializer_tree(
                tree=layer.get("tree", []),
                app_name=app_name,
                max_chars_per_file=max_chars_per_file,
            )

    return []


def scan_admin_serializer_tree(
    tree: list[dict[str, Any]],
    app_name: str,
    max_chars_per_file: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for item in tree:
        item_type = item.get("type")
        item_name = item.get("name")
        item_path = item.get("path", "")

        if item_type == "dir":
            if item_name == "admin" or item_path.startswith("serializers/admin"):
                results.extend(
                    scan_admin_serializer_tree(
                        tree=item.get("children", []),
                        app_name=app_name,
                        max_chars_per_file=max_chars_per_file,
                    )
                )

        elif item_type == "file":
            if not item_path.startswith("serializers/admin/"):
                continue
            if item_name == "__init__.py":
                continue
            if not item_name.endswith(".py"):
                continue

            abs_path = TARGET_PROJECT_ROOT / "apps" / app_name / item_path
            if not abs_path.exists():
                continue

            try:
                content = read_text(abs_path, encoding="utf-8")[:max_chars_per_file]
            except Exception:
                continue

            results.append(
                {
                    "path": f"apps/{app_name}/{item_path}",
                    "content": content,
                }
            )

    return results


def build_system_prompt() -> str:
    return """
你是资深 Django REST Framework 架构师，负责根据已确认的新项目 model 草稿，生成最简 admin CRUD serializers。

目标：
只生成 admin CRUD 所需的 serializers，不生成 view/service/url。

硬性规则：

1. 仅生成 serializers 文件
2. 仅生成以下 3 类：
   - XxxListResponseSerializer
   - XxxDetailResponseSerializer
   - XxxCreateUpdateSerializer
3. 必须基于已经生成好的 Django 6 model 草稿
4. 风格优先模仿项目中已有的 serializers/admin/*.py
5. 默认使用 ModelSerializer
6. 不要臆造复杂嵌套 serializer
7. 不要默认加 SerializerMethodField，除非 model 字段本身明显需要
8. CreateUpdateSerializer 应聚焦创建/更新所需字段
9. List/Detail serializer 应聚焦读取展示
10. 不要生成 customer 端 serializer
11. 输出必须包含设计说明和代码两部分

输出格式必须严格为：

===DESIGN===
设计说明

===CODE===
Python代码
""".strip()


def build_user_prompt(
    model_name: str,
    target_app: str,
    target_file: Path,
    model_code: str,
    reference_serializers: list[dict[str, Any]],
) -> str:
    ref_json = json.dumps(reference_serializers, ensure_ascii=False, indent=2)

    prompt = f"""
下面是已确认的新项目 model 草稿，以及项目中已有的 serializer 参考文件。
请为 `{model_name}` 生成最简 admin CRUD serializers。

【Target App】
{target_app}

【Target Serializer File】
{str(target_file)}

【Model Draft】
""".strip()

    prompt += "\n```python\n"
    prompt += model_code
    prompt += "\n```\n\n"

    prompt += f"""【Reference Serializers】

{ref_json}

额外要求：

1. 只生成 admin CRUD serializer
2. 生成这 3 个类：
   - {model_name}ListResponseSerializer
   - {model_name}DetailResponseSerializer
   - {model_name}CreateUpdateSerializer
3. 尽量遵循参考 serializer 的命名和书写风格
4. 优先保持代码简洁
5. 先不要做复杂嵌套 serializer
6. 如果某些关系字段在 List/Detail 中适合直接返回 id/name 结构，可参考现有风格，但不要过度设计
7. CreateUpdateSerializer 应聚焦写入字段
8. List/DetailSerializer 应聚焦读取展示
9. 不要生成 view/service/url 代码

请按格式输出：

===DESIGN===
说明

===CODE===
Python代码
"""

    return prompt


def split_design_and_code(raw: str) -> tuple[str, str]:
    text = raw.strip()
    design = ""
    code = ""

    if "===CODE===" in text:
        parts = text.split("===CODE===", 1)
        design_part = parts[0]
        code_part = parts[1]

        if "===DESIGN===" in design_part:
            design = design_part.split("===DESIGN===", 1)[1].strip()
        else:
            design = design_part.strip()

        code = extract_python_code(code_part)
        return design, code

    code = extract_python_code(text)
    return design, code


def extract_python_code(text: str) -> str:
    stripped = text.strip()

    if "```python" in stripped:
        return stripped.split("```python", 1)[1].split("```", 1)[0].strip()

    if "```" in stripped:
        return stripped.split("```", 1)[1].split("```", 1)[0].strip()

    return stripped


def build_markdown(
    model_name: str,
    target_app: str,
    target_file: Path,
    model_draft_path: Path,
    reference_serializers: list[dict[str, Any]],
    design_text: str,
    code: str,
) -> str:
    lines: list[str] = []

    lines.append(f"# {model_name} Serializer 草案")
    lines.append("")
    lines.append(f"- 目标 app: `{target_app}`")
    lines.append(f"- 输出文件: `{target_file}`")
    lines.append(f"- 基于 model draft: `{model_draft_path}`")
    lines.append("")

    lines.append("## 设计说明")
    lines.append("")
    lines.append(design_text.strip() if design_text.strip() else "无")
    lines.append("")

    lines.append("## 参考 Serializer")
    lines.append("")
    if reference_serializers:
        for item in reference_serializers:
            lines.append(f"- `{item.get('path')}`")
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("## 生成代码")
    lines.append("")
    lines.append("```python")
    lines.append(code)
    lines.append("```")
    lines.append("")

    return "\n".join(lines)
