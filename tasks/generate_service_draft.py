import json
from pathlib import Path
from typing import Any

from config import TARGET_PROJECT_ROOT
from llm.client import LLMClient
from tools.fs_tools import read_text
from tools.json_tools import read_json
from tools.report_tools import write_markdown_report


def run_generate_service_draft(
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

    serializer_target_file = build_serializer_target_file(target_file)
    serializer_draft_path = agent_root / "workspace" / "drafts" / serializer_target_file

    model_code = read_text(model_draft_path, encoding="utf-8")
    serializer_code = ""
    if serializer_draft_path.exists():
        serializer_code = read_text(serializer_draft_path, encoding="utf-8")

    service_target_file = build_service_target_file(target_file)
    service_output_path = agent_root / "workspace" / "drafts" / service_target_file
    service_output_path.parent.mkdir(parents=True, exist_ok=True)

    reference_services = collect_reference_services(
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
        target_file=service_target_file,
        model_code=model_code,
        serializer_code=serializer_code,
        reference_services=reference_services,
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
        raise ValueError(f"LLM 未生成有效 service 代码。\n原始输出:\n{raw}")

    service_output_path.write_text(code, encoding="utf-8")

    md_path = agent_root / "reports/services" / f"{model_name.lower()}_service_draft.md"
    write_markdown_report(
        md_path,
        build_markdown(
            model_name=model_name,
            target_app=target_app,
            target_file=service_target_file,
            model_draft_path=model_draft_path,
            serializer_draft_path=serializer_draft_path if serializer_draft_path.exists() else None,
            reference_services=reference_services,
            design_text=design_text,
            code=code,
        ),
    )

    return code, service_output_path, md_path


def find_mapping(
    final_mapping: dict[str, Any],
    model_name: str,
) -> dict[str, Any] | None:
    for item in final_mapping.get("mappings", []):
        if item.get("source_model") == model_name:
            return item
    return None


def build_serializer_target_file(model_target_file: str) -> Path:
    path = Path(model_target_file)
    parts = list(path.parts)

    if "models" not in parts:
        raise ValueError(f"target_file 不是标准 models 路径: {model_target_file}")

    idx = parts.index("models")
    new_parts = parts[:idx] + ["serializers", "admin"] + parts[idx + 1 :]
    return Path(*new_parts)


def build_service_target_file(model_target_file: str) -> Path:
    """
    apps/compute/models/ssh_public_key.py
    -> apps/compute/services/admin/ssh_public_key.py
    """
    path = Path(model_target_file)
    parts = list(path.parts)

    if "models" not in parts:
        raise ValueError(f"target_file 不是标准 models 路径: {model_target_file}")

    idx = parts.index("models")
    new_parts = parts[:idx] + ["services", "admin"] + parts[idx + 1 :]
    return Path(*new_parts)


def collect_reference_services(
    target_app: str,
    project_structure: dict[str, Any],
    max_files: int = 4,
    max_chars_per_file: int = 4000,
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    apps = project_structure.get("apps", [])

    references.extend(
        collect_admin_service_files_from_app(
            apps=apps,
            app_name=target_app,
            max_chars_per_file=max_chars_per_file,
        )
    )

    if target_app != "core":
        references.extend(
            collect_admin_service_files_from_app(
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


def collect_admin_service_files_from_app(
    apps: list[dict[str, Any]],
    app_name: str,
    max_chars_per_file: int,
) -> list[dict[str, Any]]:
    for app in apps:
        if app.get("app") != app_name:
            continue

        for layer in app.get("layers", []):
            if layer.get("layer") != "services":
                continue

            return scan_admin_service_tree(
                tree=layer.get("tree", []),
                app_name=app_name,
                max_chars_per_file=max_chars_per_file,
            )

    return []


def scan_admin_service_tree(
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
            if item_name == "admin" or item_path.startswith("services/admin"):
                results.extend(
                    scan_admin_service_tree(
                        tree=item.get("children", []),
                        app_name=app_name,
                        max_chars_per_file=max_chars_per_file,
                    )
                )

        elif item_type == "file":
            if not item_path.startswith("services/admin/"):
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
你是资深 Django 服务层架构师，负责根据已确认的新项目 model 草稿与 serializer 草稿，生成最简 admin CRUD service。

目标：
只生成 admin CRUD 所需的 service 文件，不生成 view/url。

硬性规则：

1. 仅生成 services 文件
2. 仅生成最基础 CRUD 函数：
   - list_xxx
   - get_xxx
   - create_xxx
   - update_xxx
   - delete_xxx
3. 必须基于已经生成好的 Django 6 model 草稿
4. 如有 serializer 草稿，可参考其类名和字段分工
5. 风格优先模仿项目中已有的 services/admin/*.py
6. 先保持简单，不要引入复杂业务逻辑
7. 不要把 legacy 复杂行为方法直接搬进 service
8. 可以使用事务，但不要滥用
9. 优先返回 queryset / model instance / 删除结果，不要擅自设计复杂返回结构
10. 不生成 view/url 代码
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
    serializer_code: str,
    reference_services: list[dict[str, Any]],
) -> str:
    ref_json = json.dumps(reference_services, ensure_ascii=False, indent=2)

    prompt = f"""
下面是已确认的新项目 model 草稿、可选 serializer 草稿，以及项目中已有的 service 参考文件。
请为 `{model_name}` 生成最简 admin CRUD service。

【Target App】
{target_app}

【Target Service File】
{str(target_file)}

【Model Draft】
""".strip()

    prompt += "\n```python\n"
    prompt += model_code
    prompt += "\n```\n\n"

    if serializer_code.strip():
        prompt += "【Serializer Draft】\n"
        prompt += "\n```python\n"
        prompt += serializer_code
        prompt += "\n```\n\n"

    prompt += f"""【Reference Services】

{ref_json}

额外要求：

1. 只生成 admin CRUD service
2. 生成最基础的 5 个函数：
   - list_{snake_name(model_name)}
   - get_{snake_name(model_name)}
   - create_{snake_name(model_name)}
   - update_{snake_name(model_name)}
   - delete_{snake_name(model_name)}
3. 尽量遵循参考 service 的命名和书写风格
4. 优先保持代码简洁
5. 不要引入复杂业务逻辑
6. create/update 可接收 validated_data
7. delete 返回删除对象或布尔值均可，但风格要统一
8. 不要生成 view/url 代码

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


def snake_name(name: str) -> str:
    chars: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            prev = name[i - 1]
            if prev.islower() or (i + 1 < len(name) and name[i + 1].islower()):
                chars.append("_")
        chars.append(ch.lower())
    return "".join(chars)


def build_markdown(
    model_name: str,
    target_app: str,
    target_file: Path,
    model_draft_path: Path,
    serializer_draft_path: Path | None,
    reference_services: list[dict[str, Any]],
    design_text: str,
    code: str,
) -> str:
    lines: list[str] = []

    lines.append(f"# {model_name} Service 草案")
    lines.append("")
    lines.append(f"- 目标 app: `{target_app}`")
    lines.append(f"- 输出文件: `{target_file}`")
    lines.append(f"- 基于 model draft: `{model_draft_path}`")
    if serializer_draft_path:
        lines.append(f"- 基于 serializer draft: `{serializer_draft_path}`")
    lines.append("")

    lines.append("## 设计说明")
    lines.append("")
    lines.append(design_text.strip() if design_text.strip() else "无")
    lines.append("")

    lines.append("## 参考 Service")
    lines.append("")
    if reference_services:
        for item in reference_services:
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
