import json
import re
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

    enum_analysis_json = agent_root / "reports" / "enum_analysis.json"
    enum_analysis = load_optional_json(enum_analysis_json)
    model_enums = extract_model_enums(enum_analysis, model_name)

    relationship_graph_json = agent_root / "reports" / "relationship_graph.json"
    relationship_graph = load_optional_json(relationship_graph_json)
    model_relationships = extract_model_relationships(relationship_graph, model_name)

    candidate_common_paths = build_candidate_common_serializer_paths(
        target_app=target_app,
        model_relationships=model_relationships,
    )

    common_serializer_context = load_common_serializer_context(
        candidate_paths=candidate_common_paths,
        max_chars_per_file=4000,
    )

    reference_serializers = collect_reference_serializers(
        target_app=target_app,
        project_structure=project_structure,
        candidate_common_paths=candidate_common_paths,
        max_files=8,
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
        model_enums=model_enums,
        model_relationships=model_relationships,
        common_serializer_context=common_serializer_context,
        candidate_common_paths=candidate_common_paths,
    )

    raw = llm.complete(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.0,
        max_tokens=5000,
        timeout=120,
    )

    design_text, common_files_updates, code = split_design_common_and_code(raw)

    if not code.strip():
        raise ValueError(f"LLM 未生成有效 serializer 代码。\n原始输出:\n{raw}")

    serializer_output_path.write_text(code, encoding="utf-8")

    common_output_paths = apply_common_serializer_updates(
        agent_root=agent_root,
        common_files_updates=common_files_updates,
    )

    md_path = agent_root / "reports" / "serializers" / f"{model_name.lower()}_serializer_draft.md"
    write_markdown_report(
        md_path,
        build_markdown(
            model_name=model_name,
            target_app=target_app,
            target_file=serializer_target_file,
            model_draft_path=model_draft_path,
            reference_serializers=reference_serializers,
            common_serializer_context=common_serializer_context,
            common_output_paths=common_output_paths,
            model_enums=model_enums,
            design_text=design_text,
            code=code,
            common_files_updates=common_files_updates,
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
    candidate_common_paths: list[str],
    max_files: int = 8,
    max_chars_per_file: int = 4000,
) -> list[dict[str, Any]]:
    """
    收集：
    1. 同 app 下 serializers/admin/*.py
    2. core 下 serializers/admin/*.py
    3. 仅当前模型相关的 common serializer 文件
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

    references.extend(
        load_selected_common_serializer_files(
            candidate_paths=candidate_common_paths,
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


def load_selected_common_serializer_files(
    candidate_paths: list[str],
    max_chars_per_file: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for rel_path in candidate_paths:
        abs_path = TARGET_PROJECT_ROOT / rel_path
        if not abs_path.exists():
            continue

        try:
            content = read_text(abs_path, encoding="utf-8")[:max_chars_per_file]
        except Exception:
            continue

        results.append(
            {
                "path": rel_path,
                "content": content,
            }
        )

    return results


def load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except Exception:
        return {}


def extract_model_enums(
    enum_analysis: dict[str, Any],
    model_name: str,
) -> list[dict[str, Any]]:
    return [
        item
        for item in enum_analysis.get("enums", [])
        if item.get("model") == model_name
    ]


def extract_model_relationships(
    relationship_graph: dict[str, Any],
    model_name: str,
) -> list[dict[str, Any]]:
    return [
        edge
        for edge in relationship_graph.get("edges", [])
        if edge.get("source_model") == model_name or edge.get("target_model") == model_name
    ]


def build_candidate_common_serializer_paths(
    target_app: str,
    model_relationships: list[dict[str, Any]],
) -> list[str]:
    """
    只根据当前模型真正涉及的 app，挑选 common serializer 文件。
    例如 VirtualServer 只会拿：
    - compute.py
    - customer.py
    - asset.py
    - network.py
    """
    modules: set[str] = set()

    modules.add(map_app_to_common_module(target_app))

    for item in model_relationships:
        source_model = item.get("source_model")
        field_name = item.get("field_name")
        target_app_name = item.get("target_app")

        # 只关心“当前模型主动依赖出去”的关系
        if source_model and field_name and source_model != item.get("target_model"):
            pass

        if target_app_name:
            modules.add(map_app_to_common_module(target_app_name))

    valid_modules = {
        "asset",
        "compute",
        "customer",
        "network",
        "ops",
        "storage",
    }

    result: list[str] = []
    for module in sorted(m for m in modules if m in valid_modules):
        result.append(f"apps/common/serializers/{module}.py")
    return result


def map_app_to_common_module(app_name: str) -> str:
    """
    你的 common serializers 目录是：
    asset.py / compute.py / customer.py / network.py / ops.py / storage.py

    所以 core 这里映射到 customer。
    """
    if app_name == "core":
        return "customer"
    return app_name


def load_common_serializer_context(
    candidate_paths: list[str],
    max_chars_per_file: int = 4000,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for rel_path in candidate_paths:
        abs_path = TARGET_PROJECT_ROOT / rel_path
        if not abs_path.exists():
            results.append(
                {
                    "path": rel_path,
                    "content": "",
                    "exists": False,
                }
            )
            continue

        try:
            content = read_text(abs_path, encoding="utf-8")[:max_chars_per_file]
        except Exception:
            content = ""

        results.append(
            {
                "path": rel_path,
                "content": content,
                "exists": True,
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

Enum 规则：

12. 如果提供了 Enum Analysis，优先将对应字段按 choices / ChoiceField 风格处理
13. 如果 model 中已经定义了 TextChoices，serializer 应与 model 保持一致
14. 不要忽略已经明确识别出的枚举字段
15. 对枚举字段，不要退化成普通 CharField，除非证据明确不足

Common Serializer 规则：

16. 优先复用 apps/common/serializers 下已存在的 SimpleSerializer
17. 不要在当前业务 serializer 文件中重复定义已经存在的 ImageSimpleSerializer / CustomerSimpleSerializer / PhysicalServerSimpleSerializer / IPAddressSimpleSerializer
18. 如果缺少对应 SimpleSerializer，需要增量补充到对应的 apps/common/serializers/<module>.py 中
19. 只针对当前模型真正相关的 common serializer 文件做判断，不要扩散到无关模块
20. 增量补充时，不要重写整个 common 文件，只输出需要追加的 class 代码片段
21. 业务 serializer 文件中应优先 import common serializer，而不是临时定义 serializers.Serializer

输出格式必须严格为：

===DESIGN===
设计说明

===COMMON_FILES===
JSON数组，格式如下：
[
  {
    "path": "apps/common/serializers/compute.py",
    "append_code": "class ImageSimpleSerializer(...):\\n    ..."
  }
]

如果无需补充 common serializer，则输出 []。

===CODE===
Python代码
""".strip()


def build_user_prompt(
    model_name: str,
    target_app: str,
    target_file: Path,
    model_code: str,
    reference_serializers: list[dict[str, Any]],
    model_enums: list[dict[str, Any]],
    model_relationships: list[dict[str, Any]],
    common_serializer_context: list[dict[str, Any]],
    candidate_common_paths: list[str],
) -> str:
    ref_json = json.dumps(reference_serializers, ensure_ascii=False, indent=2)
    enums_json = json.dumps(model_enums, ensure_ascii=False, indent=2)
    relationships_json = json.dumps(model_relationships, ensure_ascii=False, indent=2)
    common_json = json.dumps(common_serializer_context, ensure_ascii=False, indent=2)
    candidate_common_paths_json = json.dumps(candidate_common_paths, ensure_ascii=False, indent=2)

    prompt = f"""
下面是已确认的新项目 model 草稿、参考 serializer，以及当前模型相关的 common serializer 上下文。
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

    prompt += "【Reference Serializers】\n\n"
    prompt += ref_json
    prompt += "\n\n"

    prompt += "【Enum Analysis】\n\n"
    prompt += enums_json
    prompt += "\n\n"

    prompt += "【Model Relationships】\n\n"
    prompt += relationships_json
    prompt += "\n\n"

    prompt += "【Selected Common Serializer Files】\n\n"
    prompt += candidate_common_paths_json
    prompt += "\n\n"

    prompt += "【Current Common Serializer Context】\n\n"
    prompt += common_json
    prompt += "\n\n"

    prompt += f"""额外要求：

1. 只生成 admin CRUD serializer
2. 生成这 3 个类：
   - {model_name}ListResponseSerializer
   - {model_name}DetailResponseSerializer
   - {model_name}CreateUpdateSerializer
3. 尽量遵循参考 serializer 的命名和书写风格
4. 优先保持代码简洁
5. 先不要做复杂嵌套 serializer
6. 如果某些关系字段在 List/Detail 中适合直接返回简单结构，优先复用 common serializer
7. 如果 common serializer 中不存在对应 SimpleSerializer，请把增量补丁输出到 COMMON_FILES
8. COMMON_FILES 中只输出真正缺少的部分，不要重复输出已经存在的类
9. 只针对 Selected Common Serializer Files 做增量判断，不要扩散到无关 common 文件
10. CreateUpdateSerializer 应聚焦写入字段
11. List/DetailSerializer 应聚焦读取展示
12. 如果 Enum Analysis 明确指出某字段是枚举字段，请在 serializer 中按 choices 风格体现，保持与 model 一致
13. 不要生成 view/service/url 代码

请按格式输出：

===DESIGN===
说明

===COMMON_FILES===
JSON数组

===CODE===
Python代码
"""

    return prompt


def split_design_common_and_code(
    raw: str,
) -> tuple[str, list[dict[str, Any]], str]:
    text = raw.strip()

    design = ""
    common_files_updates: list[dict[str, Any]] = []
    code = ""

    if "===CODE===" not in text:
        return "", [], extract_python_code(text)

    before_code, code_part = text.split("===CODE===", 1)
    code = extract_python_code(code_part)

    common_part = ""
    if "===COMMON_FILES===" in before_code:
        before_common, common_part = before_code.split("===COMMON_FILES===", 1)
    else:
        before_common = before_code

    if "===DESIGN===" in before_common:
        design = before_common.split("===DESIGN===", 1)[1].strip()
    else:
        design = before_common.strip()

    if common_part.strip():
        common_files_updates = parse_common_files_json(common_part)

    return design, common_files_updates, code


def parse_common_files_json(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()

    if stripped.startswith("```json"):
        stripped = stripped[len("```json"):].strip()
        if stripped.endswith("```"):
            stripped = stripped[:-3].strip()
    elif stripped.startswith("```"):
        stripped = stripped[len("```"):].strip()
        if stripped.endswith("```"):
            stripped = stripped[:-3].strip()

    if not stripped:
        return []

    try:
        data = json.loads(stripped)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []
    except Exception:
        return []


def extract_python_code(text: str) -> str:
    stripped = text.strip()

    if "```python" in stripped:
        return stripped.split("```python", 1)[1].split("```", 1)[0].strip()

    if "```" in stripped:
        return stripped.split("```", 1)[1].split("```", 1)[0].strip()

    return stripped


def apply_common_serializer_updates(
    agent_root: Path,
    common_files_updates: list[dict[str, Any]],
) -> list[Path]:
    written_paths: list[Path] = []

    for item in common_files_updates:
        rel_path = item.get("path")
        append_code = item.get("append_code")

        if not rel_path or not append_code:
            continue

        target_rel_path = Path(rel_path)
        draft_path = agent_root / "workspace" / "drafts" / target_rel_path
        draft_path.parent.mkdir(parents=True, exist_ok=True)

        if draft_path.exists():
            base_content = draft_path.read_text(encoding="utf-8")
        else:
            source_path = TARGET_PROJECT_ROOT / target_rel_path
            if source_path.exists():
                base_content = source_path.read_text(encoding="utf-8")
            else:
                base_content = ""

        merged_content = merge_append_code(base_content, append_code)

        draft_path.write_text(merged_content, encoding="utf-8")
        written_paths.append(draft_path)

    return written_paths


def merge_append_code(base_content: str, append_code: str) -> str:
    class_names = re.findall(r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", append_code)
    if class_names:
        for class_name in class_names:
            if re.search(rf"class\s+{re.escape(class_name)}\s*\(", base_content):
                return base_content

    base = base_content.rstrip()
    extra = append_code.strip()

    if not base:
        return extra + "\n"

    return base + "\n\n\n" + extra + "\n"


def build_markdown(
    model_name: str,
    target_app: str,
    target_file: Path,
    model_draft_path: Path,
    reference_serializers: list[dict[str, Any]],
    common_serializer_context: list[dict[str, Any]],
    common_output_paths: list[Path],
    model_enums: list[dict[str, Any]],
    design_text: str,
    code: str,
    common_files_updates: list[dict[str, Any]],
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

    lines.append("## Selected Common Serializer Context")
    lines.append("")
    if common_serializer_context:
        for item in common_serializer_context:
            flag = "exists" if item.get("exists") else "missing"
            lines.append(f"- `{item.get('path')}` ({flag})")
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("## Enum Analysis")
    lines.append("")
    if model_enums:
        for item in model_enums:
            lines.append(
                f"- `{item.get('field')}` -> `{item.get('enum_name')}` "
                f"(source=`{item.get('source_constant')}`)"
            )
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("## Common Files Updates")
    lines.append("")
    if common_files_updates:
        for item in common_files_updates:
            lines.append(f"- `{item.get('path')}`")
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("## Common Draft Outputs")
    lines.append("")
    if common_output_paths:
        for path in common_output_paths:
            lines.append(f"- `{path}`")
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
