from pathlib import Path
from typing import Any

from config import REPORTS_DIR
from tools.json_tools import read_json, write_json
from tools.report_tools import write_markdown_report


def run_merge_final_mapping(
    mapping_json: Path,
    review_json: Path,
) -> tuple[dict[str, Any], Path, Path]:
    mapping = read_json(mapping_json)
    review = read_json(review_json)

    base_mappings = mapping.get("mappings", [])
    review_items = review.get("reviews", [])

    review_index = {item["source_model"]: item for item in review_items}

    final_mappings = []
    reviewed_count = 0

    for item in base_mappings:
        source_model = item["source_model"]
        reviewed = review_index.get(source_model)

        if reviewed:
            reviewed_count += 1
            final_mappings.append({
                "source_model": source_model,
                "source_file": item.get("source_file"),
                "final_target_app": reviewed.get("final_target_app", item.get("suggested_app")),
                "final_target_domain": reviewed.get("final_target_domain", item.get("suggested_domain")),
                "final_target_file": f"apps/{reviewed.get('final_target_app', item.get('suggested_app'))}/models/{reviewed.get('final_target_domain', item.get('suggested_domain'))}.py",
                "final_action": reviewed.get("final_action", item.get("action")),
                "final_confidence": reviewed.get("final_confidence", item.get("confidence")),
                "decision": reviewed.get("decision", "keep_current"),
                "reasoning": reviewed.get("reasoning", item.get("reasons", [])),
            })
        else:
            final_mappings.append({
                "source_model": source_model,
                "source_file": item.get("source_file"),
                "final_target_app": item.get("suggested_app"),
                "final_target_domain": item.get("suggested_domain"),
                "final_target_file": item.get("suggested_model_file"),
                "final_action": item.get("action"),
                "final_confidence": item.get("confidence"),
                "decision": "rule_only",
                "reasoning": item.get("reasons", []),
            })

    # review 里可能有 unmapped 的模型
    existing_models = {x["source_model"] for x in final_mappings}
    for reviewed in review_items:
        if reviewed["source_model"] in existing_models:
            continue
        final_mappings.append({
            "source_model": reviewed["source_model"],
            "source_file": "",
            "final_target_app": reviewed.get("final_target_app"),
            "final_target_domain": reviewed.get("final_target_domain"),
            "final_target_file": f"apps/{reviewed.get('final_target_app')}/models/{reviewed.get('final_target_domain')}.py",
            "final_action": reviewed.get("final_action"),
            "final_confidence": reviewed.get("final_confidence"),
            "decision": reviewed.get("decision", "change_mapping"),
            "reasoning": reviewed.get("reasoning", []),
        })

    result = {
        "total_models": len(final_mappings),
        "reviewed_count": reviewed_count,
        "global_suggestions": review.get("global_suggestions", []),
        "mappings": final_mappings,
    }

    json_path = REPORTS_DIR / "db_to_target_mapping_final.json"
    md_path = REPORTS_DIR / "db_to_target_mapping_final.md"

    write_json(json_path, result)
    write_markdown_report(md_path, build_markdown(result))

    return result, json_path, md_path


def build_markdown(result: dict[str, Any]) -> str:
    lines: list[str] = []

    lines.append("# db -> target 最终映射")
    lines.append("")
    lines.append(f"- 模型总数: `{result.get('total_models', 0)}`")
    lines.append(f"- LLM复核覆盖数: `{result.get('reviewed_count', 0)}`")
    lines.append("")

    lines.append("## 最终映射")
    lines.append("")
    lines.append("| 模型 | 最终 app | 最终 domain | 动作 | 置信度 | 决策 |")
    lines.append("|---|---|---|---|---|---|")
    for item in result.get("mappings", []):
        lines.append(
            f"| {item.get('source_model')} | "
            f"{item.get('final_target_app')} | "
            f"{item.get('final_target_domain')} | "
            f"{item.get('final_action')} | "
            f"{item.get('final_confidence')} | "
            f"{item.get('decision')} |"
        )
    lines.append("")

    lines.append("## 全局建议")
    lines.append("")
    for s in result.get("global_suggestions", []):
        lines.append(f"- {s}")
    if not result.get("global_suggestions"):
        lines.append("- 无")
    lines.append("")

    return "\n".join(lines)
