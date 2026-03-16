import json
import math
import time
from pathlib import Path
from typing import Any

from config import REPORTS_DIR
from llm.client import LLMClient
from tools.json_tools import read_json, write_json
from tools.report_tools import write_markdown_report


REVIEW_TARGET_ACTIONS = {"split", "normalize", "move", "review"}
REVIEW_TARGET_CONFIDENCE = {"low", "medium"}

BATCH_SIZE = 1000
MAX_RETRIES = 0


def run_llm_review_db_mapping(
    db_models_analysis_json: Path,
    db_to_target_mapping_json: Path,
    target_blueprint_json: Path,
    limit: int | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    db_models = read_json(db_models_analysis_json)
    mapping = read_json(db_to_target_mapping_json)
    blueprint = read_json(target_blueprint_json)

    review_candidates = build_review_candidates(db_models, mapping)

    if limit:
        review_candidates = review_candidates[:limit]

    llm = LLMClient()

    result = review_candidates_in_batches(
        llm=llm,
        review_candidates=review_candidates,
        blueprint=blueprint,
    )

    json_path = REPORTS_DIR / "db_to_target_mapping_review.json"
    md_path = REPORTS_DIR / "db_to_target_mapping_review.md"

    write_json(json_path, result)
    write_markdown_report(md_path, build_review_markdown(result))

    return result, json_path, md_path


def build_review_candidates(
    db_models: dict[str, Any],
    mapping: dict[str, Any],
) -> list[dict[str, Any]]:
    model_index = {item["name"]: item for item in db_models.get("models", [])}
    candidates: list[dict[str, Any]] = []

    for item in mapping.get("mappings", []):
        action = item.get("action", "")
        confidence = item.get("confidence", "")
        source_model = item.get("source_model")

        if action in REVIEW_TARGET_ACTIONS or confidence in REVIEW_TARGET_CONFIDENCE:
            model_detail = model_index.get(source_model, {})
            candidates.append({
                "source_model": source_model,
                "source_file": item.get("source_file"),
                "current_target_app": item.get("suggested_app"),
                "current_target_domain": item.get("suggested_domain"),
                "current_target_file": item.get("suggested_model_file"),
                "current_action": action,
                "current_confidence": confidence,
                "current_reasons": item.get("reasons", []),
                "fields": simplify_fields(model_detail.get("fields", [])),
                "meta_exists": bool(model_detail.get("meta")),
            })

    for model_name in mapping.get("unmapped_models", []):
        model_detail = model_index.get(model_name, {})
        candidates.append({
            "source_model": model_name,
            "source_file": model_detail.get("file_path", ""),
            "current_target_app": None,
            "current_target_domain": None,
            "current_target_file": None,
            "current_action": "review",
            "current_confidence": "low",
            "current_reasons": ["规则未命中，需要 LLM 复核"],
            "fields": simplify_fields(model_detail.get("fields", [])),
            "meta_exists": bool(model_detail.get("meta")),
        })

    return candidates


def simplify_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for field in fields[:20]:
        result.append({
            "name": field.get("name"),
            "field_type": field.get("field_type"),
            "is_relation": field.get("is_relation"),
            "relation_target": field.get("relation_target"),
            "has_choices": field.get("has_choices"),
        })
    return result


def review_candidates_in_batches(
    llm: LLMClient,
    review_candidates: list[dict[str, Any]],
    blueprint: dict[str, Any],
) -> dict[str, Any]:
    all_reviews: list[dict[str, Any]] = []
    all_global_suggestions: list[str] = []
    batch_logs: list[dict[str, Any]] = []

    total = len(review_candidates)
    if total == 0:
        return {
            "reviews": [],
            "global_suggestions": ["没有需要 LLM 复核的候选项。"],
            "batch_logs": [],
        }

    batch_count = math.ceil(total / BATCH_SIZE)

    for idx in range(batch_count):
        start = idx * BATCH_SIZE
        end = start + BATCH_SIZE
        batch = review_candidates[start:end]

        print(f"[LLM REVIEW] batch {idx + 1}/{batch_count}, size={len(batch)}")

        batch_result = review_single_batch_with_retry(
            llm=llm,
            batch=batch,
            blueprint=blueprint,
            batch_index=idx + 1,
        )

        batch_logs.append(batch_result["batch_log"])

        if batch_result["parsed_result"]:
            parsed = batch_result["parsed_result"]
            all_reviews.extend(parsed.get("reviews", []))
            all_global_suggestions.extend(parsed.get("global_suggestions", []))

    return {
        "reviews": all_reviews,
        "global_suggestions": list(dict.fromkeys(all_global_suggestions)),
        "batch_logs": batch_logs,
    }


def review_single_batch_with_retry(
    llm: LLMClient,
    batch: list[dict[str, Any]],
    blueprint: dict[str, Any],
    batch_index: int,
) -> dict[str, Any]:
    last_error = None
    raw_outputs: list[str] = []

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            start = time.time()
            parsed_result, raw_output = review_single_batch(
                llm=llm,
                batch=batch,
                blueprint=blueprint,
            )
            latency = round(time.time() - start, 2)

            raw_outputs.append(raw_output)
            save_batch_raw_output(batch_index, attempt, raw_output)

            return {
                "parsed_result": parsed_result,
                "batch_log": {
                    "batch_index": batch_index,
                    "status": "success",
                    "attempt": attempt,
                    "latency_seconds": latency,
                    "candidate_models": [x["source_model"] for x in batch],
                }
            }
        except Exception as exc:
            last_error = str(exc)
            raw_outputs.append(last_error)
            save_batch_raw_output(batch_index, attempt, last_error, is_error=True)
            print(f"[LLM REVIEW] batch={batch_index} attempt={attempt} failed: {exc}")

    return {
        "parsed_result": None,
        "batch_log": {
            "batch_index": batch_index,
            "status": "failed",
            "attempt": MAX_RETRIES + 1,
            "error": last_error,
            "candidate_models": [x["source_model"] for x in batch],
        }
    }


def review_single_batch(
    llm: LLMClient,
    batch: list[dict[str, Any]],
    blueprint: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    system_prompt = """
你是一个资深 Django 重构架构师。
你的任务是根据 legacy Django 模型信息和目标系统蓝图，复核“旧模型 -> 新系统目标 app/domain”的映射建议。

严格要求：
1. 只能在给定 target blueprint 范围内判断。
2. 如果当前映射合理，可以维持。
3. 如果当前映射不合理，给出更合理的 target app / domain。
4. action 只能从以下值中选：
   keep, move, split, merge, rename, normalize, review
5. confidence 只能从以下值中选：
   high, medium, low
6. decision 只能从以下值中选：
   keep_current, change_mapping
7. 你必须只输出 JSON。
8. 不要输出解释性前言。
9. 不要输出 markdown。
10. 不要输出代码块。
"""

    user_prompt = f"""
请复核以下映射候选项。

target_blueprint:
{json.dumps(blueprint, ensure_ascii=False, indent=2)}

review_candidates:
{json.dumps(batch, ensure_ascii=False, indent=2)}

请只输出一个合法 JSON，对象格式如下：

{{
  "reviews": [
    {{
      "source_model": "Region",
      "final_target_app": "asset",
      "final_target_domain": "region",
      "final_action": "keep",
      "final_confidence": "high",
      "decision": "keep_current",
      "reasoning": [
        "理由1",
        "理由2"
      ]
    }}
  ],
  "global_suggestions": [
    "建议1",
    "建议2"
  ]
}}

再次强调：
- 只输出 JSON
- 不要输出任何额外说明
"""

    raw = llm.complete(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.0,
        max_tokens=3000,
        timeout=120,
    )
    print("==== LLM RAW OUTPUT ====")
    print(raw)
    print("========================")
    parsed = llm.try_parse_json(raw)
    if parsed is None:
        raise ValueError(f"LLM 输出不是合法 JSON。raw={raw}")

    validate_review_result(parsed, expected_models=[x["source_model"] for x in batch])

    return parsed, raw


def validate_review_result(data: dict[str, Any], expected_models: list[str]) -> None:
    if "reviews" not in data or not isinstance(data["reviews"], list):
        raise ValueError("LLM JSON 缺少 reviews 列表")

    returned_models = {item.get("source_model") for item in data["reviews"]}
    missing = [m for m in expected_models if m not in returned_models]
    if missing:
        raise ValueError(f"LLM 返回缺少模型: {missing}")


def save_batch_raw_output(batch_index: int, attempt: int, content: str, is_error: bool = False) -> None:
    suffix = "error" if is_error else "raw"
    path = REPORTS_DIR / "llm_batch_logs" / f"batch_{batch_index:02d}_attempt_{attempt}_{suffix}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_review_markdown(result: dict[str, Any]) -> str:
    lines: list[str] = []

    reviews = result.get("reviews", [])
    global_suggestions = result.get("global_suggestions", [])
    batch_logs = result.get("batch_logs", [])

    lines.append("# db -> target 映射复核报告（LLM）")
    lines.append("")
    lines.append(f"- 复核条目数: `{len(reviews)}`")
    lines.append(f"- 批次数: `{len(batch_logs)}`")
    lines.append("")

    lines.append("## 批处理日志")
    lines.append("")
    if batch_logs:
        lines.append("| Batch | 状态 | 尝试次数 | 候选模型 |")
        lines.append("|---|---|---|---|")
        for item in batch_logs:
            models = ", ".join(item.get("candidate_models", []))
            lines.append(
                f"| {item.get('batch_index', '-')} | {item.get('status', '-')} | "
                f"{item.get('attempt', '-')} | {models} |"
            )
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("## 复核结果")
    lines.append("")
    if reviews:
        lines.append("| 模型 | 最终 app | 最终 domain | 动作 | 置信度 | 决策 |")
        lines.append("|---|---|---|---|---|---|")
        for item in reviews:
            lines.append(
                f"| {item.get('source_model', '-')} | "
                f"{item.get('final_target_app', '-')} | "
                f"{item.get('final_target_domain', '-')} | "
                f"{item.get('final_action', '-')} | "
                f"{item.get('final_confidence', '-')} | "
                f"{item.get('decision', '-')} |"
            )
    else:
        lines.append("- 暂无")
    lines.append("")

    lines.append("## 每项复核理由")
    lines.append("")
    if reviews:
        for item in reviews:
            lines.append(f"### {item.get('source_model', '-')}")
            lines.append("")
            lines.append(f"- 最终目标 app: `{item.get('final_target_app', '-')}`")
            lines.append(f"- 最终目标 domain: `{item.get('final_target_domain', '-')}`")
            lines.append(f"- 动作: `{item.get('final_action', '-')}`")
            lines.append(f"- 置信度: `{item.get('final_confidence', '-')}`")
            lines.append(f"- 决策: `{item.get('decision', '-')}`")
            lines.append("- 理由:")
            for reason in item.get("reasoning", []):
                lines.append(f"  - {reason}")
            lines.append("")
    else:
        lines.append("- 暂无")
        lines.append("")

    lines.append("## 全局建议")
    lines.append("")
    if global_suggestions:
        for item in global_suggestions:
            lines.append(f"- {item}")
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("## 原始输出日志位置")
    lines.append("")
    lines.append("- `reports/llm_batch_logs/`")
    lines.append("")

    return "\n".join(lines)
