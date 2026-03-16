import json
from pathlib import Path
from typing import Any

from analyzers.model_context_enricher import ModelContextEnricher
from analyzers.reference_selector import ReferenceSelector
from llm.client import LLMClient
from tools.json_tools import read_json
from tools.report_tools import write_markdown_report
from config import TARGET_PROJECT_ROOT


def load_project_rules(agent_root: Path) -> dict[str, Any]:
    rules_path = agent_root / "workspace" / "project_rules.json"
    if not rules_path.exists():
        return {}
    with rules_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return read_json(path)


def extract_model_field_semantics(field_semantics: dict[str, Any], model_name: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in field_semantics.get("field_semantics", []):
        if item.get("model") == model_name:
            results.append(item)
    return results


def extract_model_relationships(relationship_graph: dict[str, Any], model_name: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for edge in relationship_graph.get("edges", []):
        if edge.get("source_model") == model_name or edge.get("target_model") == model_name:
            results.append(edge)
    return results


def run_generate_django6_model_draft(
    model_name: str,
    legacy_project_root: Path,
    agent_root: Path,
    db_models_analysis_json: Path,
    final_mapping_json: Path,
    target_blueprint_json: Path,
) -> tuple[str, Path, Path]:
    enricher = ModelContextEnricher(
        project_root=legacy_project_root,
        db_models_analysis_json=db_models_analysis_json,
        final_mapping_json=final_mapping_json,
        target_blueprint_json=target_blueprint_json,
    )
    model_context = enricher.enrich(model_name)

    relationship_graph_json = agent_root / "reports" / "relationship_graph.json"
    project_structure_json = agent_root / "reports" / "project_structure_graph.json"
    field_semantics_json = agent_root / "reports" / "field_semantics.json"
    reference_models_json = agent_root / "workspace" / "reference_models.json"

    selector = ReferenceSelector(
        project_root=TARGET_PROJECT_ROOT,
        relationship_graph_json=relationship_graph_json,
        project_structure_json=project_structure_json,
        reference_models_json=reference_models_json,
    )
    reference_selection = selector.select_model_references(
        model_name=model_name,
        target_app=model_context.target_app,
    )

    project_rules = load_project_rules(agent_root)
    relationship_graph = load_optional_json(relationship_graph_json)
    field_semantics = load_optional_json(field_semantics_json)

    model_relationships = extract_model_relationships(relationship_graph, model_name)
    model_field_semantics = extract_model_field_semantics(field_semantics, model_name)

    llm = LLMClient()

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(
        model_context=model_context.model_dump(),
        reference_selection=reference_selection,
        project_rules=project_rules,
        model_relationships=model_relationships,
        model_field_semantics=model_field_semantics,
    )

    raw = llm.complete(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.0,
        max_tokens=5000,
        timeout=120,
    )

    design_text, code = split_design_and_code(raw)

    if not code.strip():
        raise ValueError(f"LLM 未生成有效代码。\n原始输出:\n{raw}")

    output_path = agent_root / "workspace" / "drafts" / model_context.target_file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(code, encoding="utf-8")

    md_path = agent_root / "reports/models" / f"{model_name.lower()}_model_draft.md"
    write_markdown_report(
        md_path,
        build_markdown(
            model_name=model_name,
            model_context=model_context.model_dump(),
            reference_selection=reference_selection,
            model_relationships=model_relationships,
            model_field_semantics=model_field_semantics,
            output_path=output_path,
            design_text=design_text,
            code=code,
        ),
    )

    return code, output_path, md_path


def build_system_prompt() -> str:
    return """
你是资深 Django 6 架构师，负责把 legacy Django 模型重构为新系统模型草案。

目标：
生成“符合新项目规范”的 Django 6 模型草案，而不是机械兼容旧系统写法。

硬性规则：

1. 优先继承项目中的 BaseModel
2. 如果继承 BaseModel，不要重复定义 created_at / updated_at
3. 关系字段优先使用 ForeignKey / ManyToManyField / OneToOneField
4. 对跨 app 的关系字段，统一使用字符串形式 "app_label.ModelName"
5. 不要只写 "ModelName"，除非可以明确确认目标模型与当前模型位于同一 Django app
6. 如果上下文不足以确认关系目标，不要乱猜，请保守生成并添加 TODO 注释
7. 如果字段看起来像对象快照字段（例如 username），可考虑“FK + snapshot 字段并存”
8. 如果字段看起来像枚举语义（例如 action/status/type/source/used_by），优先考虑 TextChoices；如果证据不足，可保留 CharField / TextField 并加 TODO
9. 默认生成“新架构规范模型”，不是“legacy 兼容模型”
10. 不要为了兼容旧系统自动生成 property / classmethod / helper method
11. 不要自动保留旧字段别名，例如 date -> created_at 的兼容属性
12. 旧系统中的行为方法应优先迁移到 services 层，而不是继续保留在 model 中
13. 只生成 models 文件
14. 不生成 serializer / view / service
15. 输出必须包含设计说明和代码两部分

身份模型硬规则：

16. auth.User 是 Django 登录用户主表
17. core.Admin 是 auth.User 的补充资料表，不是认证主表
18. core.Customer 是客户业务主体表，不是 Django 用户表
19. 旧项目中类名为 User 的模型不能直接等同于 auth.User
20. 如果旧 User 来源于 db 模块，或表名是 db_user，应优先视为客户主体并迁移为 core.Customer
21. 只有在字段明确表示操作者、创建人、更新人时，才优先使用 auth.User
22. 如果 legacy 字段名为 user，但业务语义表示资源归属客户，可以在新项目中重命名为 customer

输出格式必须严格为：

===DESIGN===
设计说明

===CODE===
Python代码
""".strip()


def build_user_prompt(
    model_context: dict[str, Any],
    reference_selection: list[dict[str, Any]],
    project_rules: dict[str, Any],
    model_relationships: list[dict[str, Any]],
    model_field_semantics: list[dict[str, Any]],
) -> str:
    return f"""
下面是某个 legacy 模型的完整上下文包，以及新项目中自动挑选的参考样本文件。
请根据这些信息生成 Django 6 模型草案。

【Model Context】
{json.dumps(model_context, ensure_ascii=False, indent=2)}

【Reference Selection】
{json.dumps(reference_selection, ensure_ascii=False, indent=2)}

【Project Rules】
{json.dumps(project_rules, ensure_ascii=False, indent=2)}

【Model Relationships】
{json.dumps(model_relationships, ensure_ascii=False, indent=2)}

【Field Semantics】
{json.dumps(model_field_semantics, ensure_ascii=False, indent=2)}

额外要求：

1. 当前目标是生成“符合新项目 Django 6 规范”的模型草案
2. 不要为了兼容旧项目自动保留 legacy API
3. 不要自动生成 date 属性映射 created_at
4. 不要自动生成 ActionLog.log() 这类 classmethod
5. 如果认为旧行为应该迁移到 services 层，请在 DESIGN 中说明，不要写进 model
6. 充分参考 Reference Selection 中的真实新项目代码风格
7. 如果已有接近风格的模型，尽量保持一致
8. 身份模型必须遵循 Project Rules
9. 当字段表示登录用户、操作者、创建人时，优先考虑 auth.User
10. 当字段表示管理员扩展资料时，优先考虑 core.Admin
11. 当字段表示客户归属、业务主体时，优先考虑 core.Customer
12. 如果 Field Semantics 明确指出 legacy 字段语义是 customer，则可以把 legacy 字段名 user 重命名为 customer
13. 如果 Model Relationships 显示该模型与 Customer 关系更强，请优先考虑 customer 命名
14. 对跨 app 的关系字段，统一使用 "app_label.ModelName"
15. 如果某个关系目标已经能从上下文确认所属 app，必须直接写成 "app_label.ModelName"
16. 如果证据仍不足，请加 TODO 注释，不要强行臆造
17. 如果字段在 legacy 中依赖 constants/choices/default_expr，请尽量利用这些信息重建 choices/default
18. 如果 legacy 字段明显是自由文本，而不是稳定枚举，不要强行生成为 TextChoices

请按格式输出：

===DESIGN===
说明

===CODE===
Python代码
""".strip()


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
    model_context: dict[str, Any],
    reference_selection: list[dict[str, Any]],
    model_relationships: list[dict[str, Any]],
    model_field_semantics: list[dict[str, Any]],
    output_path: Path,
    design_text: str,
    code: str,
) -> str:
    lines: list[str] = []

    lines.append(f"# {model_name} Django 6 模型草案")
    lines.append("")
    lines.append(f"- 目标 app: `{model_context.get('target_app')}`")
    lines.append(f"- 目标 domain: `{model_context.get('target_domain')}`")
    lines.append(f"- 输出文件: `{output_path}`")
    lines.append("")

    lines.append("## 设计说明")
    lines.append("")
    lines.append(design_text.strip() if design_text.strip() else "无")
    lines.append("")

    lines.append("## 关键上下文提示")
    lines.append("")
    for s in model_context.get("suggestions", []):
        lines.append(f"- {s}")
    if not model_context.get("suggestions"):
        lines.append("- 无")
    lines.append("")

    lines.append("## 字段语义")
    lines.append("")
    if model_field_semantics:
        for item in model_field_semantics:
            lines.append(
                f"- `{item.get('model')}.{item.get('field')}` → `{item.get('semantic')}`"
            )
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("## 模型关系")
    lines.append("")
    if model_relationships:
        for item in model_relationships:
            lines.append(
                f"- `{item.get('source_model')}.{item.get('field_name')}` "
                f"→ `{item.get('target_model')}` "
                f"(semantic={item.get('semantic') or '-'}, app={item.get('target_app') or '-'})"
            )
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("## 参考文件")
    lines.append("")
    if reference_selection:
        for item in reference_selection:
            lines.append(
                f"- `{item.get('path')}` | model={item.get('model')}"
            )
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
