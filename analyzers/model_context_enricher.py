import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tools.json_tools import read_json
from tools.fs_tools import read_text


class FieldHint(BaseModel):
    field_name: str
    looks_like_fk: bool = False
    possible_targets: list[str] = Field(default_factory=list)
    looks_like_enum: bool = False
    observed_values: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ModelContext(BaseModel):
    model_name: str
    source_file: str
    target_app: str
    target_domain: str
    target_file: str

    legacy_model_info: dict[str, Any]
    final_mapping_info: dict[str, Any]

    usage_snippets: list[str] = Field(default_factory=list)
    target_related_files: list[dict[str, Any]] = Field(default_factory=list)
    base_model_context: dict[str, Any] = Field(default_factory=dict)
    field_hints: list[FieldHint] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class ModelContextEnricher:
    def __init__(
        self,
        project_root: Path,              # 旧项目根目录
        db_models_analysis_json: Path,   # agent/reports/db_models_analysis.json
        final_mapping_json: Path,        # agent/reports/db_to_target_mapping_final.json
        target_blueprint_json: Path,     # agent/workspace/target_blueprint.json
    ):
        self.project_root = project_root
        self.db_models = read_json(db_models_analysis_json)
        self.final_mapping = read_json(final_mapping_json)
        self.target_blueprint = read_json(target_blueprint_json)

        # agent_root = target_blueprint_json 所在目录的上上级
        # legacy_refactor_agent/workspace/target_blueprint.json
        # -> legacy_refactor_agent
        self.agent_root = target_blueprint_json.resolve().parent.parent

    def enrich(self, model_name: str) -> ModelContext:
        legacy_model = self._find_model_info(model_name)
        mapping = self._find_mapping_info(model_name)

        if legacy_model is None:
            raise ValueError(f"未找到 legacy model: {model_name}")

        if mapping is None:
            raise ValueError(f"未找到最终映射: {model_name}")

        usage_snippets = self._search_model_usage(model_name, legacy_model)
        field_hints = self._build_field_hints(legacy_model, usage_snippets)
        target_related_files = self._collect_target_related_files(mapping)

        return ModelContext(
            model_name=model_name,
            source_file=legacy_model.get("file_path", ""),
            target_app=mapping.get("final_target_app", ""),
            target_domain=mapping.get("final_target_domain", ""),
            target_file=mapping.get("final_target_file", ""),
            legacy_model_info=legacy_model,
            final_mapping_info=mapping,
            usage_snippets=usage_snippets,
            target_related_files=target_related_files,
            base_model_context=self._get_base_model_context(),
            field_hints=field_hints,
            suggestions=self._build_suggestions(field_hints),
        )

    def _find_model_info(self, model_name: str) -> dict[str, Any] | None:
        for item in self.db_models.get("models", []):
            if item.get("name") == model_name:
                return item
        return None

    def _find_mapping_info(self, model_name: str) -> dict[str, Any] | None:
        for item in self.final_mapping.get("mappings", []):
            if item.get("source_model") == model_name:
                return item
        return None

    # 只分析model中字段信息，分析classmethods超出 model 范围
    #  def _extract_classmethods(self, legacy_model: dict[str, Any]) -> list[str]:
    #      source_file = legacy_model.get("file_path", "")
    #      if not source_file:
    #          return []
    #
    #      abs_path = self.project_root / source_file
    #      if not abs_path.exists():
    #          return []
    #
    #      try:
    #          text = read_text(abs_path)
    #      except Exception:
    #          return []
    #
    #      # 支持:
    #      # @classmethod
    #      # def log(cls, ...)
    #      matches = re.findall(r"@classmethod[\s\n]*def[\s\n]+(\w+)[\s\n]*\(", text)
    #      return list(dict.fromkeys(matches))

    def _build_anchor_patterns(self, model_name: str, legacy_model: dict[str, Any]) -> list[str]:
        """
        只构造和当前模型强相关的锚点。
        """
        patterns = [
            f"{model_name}(",
            f"{model_name}.objects",
            f"{model_name}.objects.create(",
            f"{model_name}.objects.get(",
            f"{model_name}.objects.filter(",
            f"{model_name}.objects.update(",
            f"from db.{model_name.lower()} import {model_name}",
        ]

        source_file = legacy_model.get("file_path", "")
        source_stem = Path(source_file).stem if source_file else model_name.lower()

        patterns.extend([
            f"from db.{source_stem} import {model_name}",
            f"import db.{source_stem}",
        ])

        return list(dict.fromkeys(patterns))

    def _score_usage_snippet(self, model_name: str, file_path: str, matched_line: str) -> int:
        """
        为命中片段打分，优先保留“字段重构”直接相关的创建/查询证据。
        """
        score = 0
        lower_line = matched_line.lower()
        lower_path = file_path.lower()
        lower_model = model_name.lower()

        if f"{model_name}.objects.create(" in matched_line:
            score += 100

        if f"{model_name}(" in matched_line:
            score += 80

        if f"{model_name}.objects.get(" in matched_line:
            score += 60

        if f"{model_name}.objects.filter(" in matched_line:
            score += 50

        if f"{model_name}.objects.update(" in matched_line:
            score += 40

        if f"{model_name}.objects.exclude(" in matched_line:
            score += 30

        # 模型定义文件自身降权
        if lower_path.endswith(f"db/{lower_model}.py"):
            score -= 20

        # tests 降权
        if "tests.py" in lower_path or "/tests/" in lower_path:
            score -= 15

        # 业务代码略微加分
        if "controllers/" in lower_path:
            score += 10
        if "views.py" in lower_path or "views/" in lower_path:
            score += 10
        if "api/" in lower_path:
            score += 5
        if "sysadmin/" in lower_path:
            score += 5

        return score

    def _search_model_usage(self, model_name: str, legacy_model: dict[str, Any]) -> list[str]:
        """
        只搜索和“模型字段重构”强相关的使用证据：
        - Model(...)
        - Model.objects.create/get/filter/update/exclude(...)
        - import 语句

        不再把 classmethod / instance method 作为 model 阶段的分析对象。
        """
        anchor_patterns = self._build_anchor_patterns(model_name, legacy_model)
        scored_snippets: list[tuple[int, str]] = []

        for py_file in self.project_root.rglob("*.py"):
            try:
                text = read_text(py_file)
            except Exception:
                continue

            lines = text.splitlines()
            matched_indexes: list[int] = []

            for idx, line in enumerate(lines):
                line_text = line.strip()
                if any(pattern in line_text for pattern in anchor_patterns):
                    matched_indexes.append(idx)

            if not matched_indexes:
                continue

            rel_path = py_file.relative_to(self.project_root)
            rel_path_str = str(rel_path)

            for idx in matched_indexes:
                start = max(0, idx - 2)
                end = min(len(lines), idx + 3)

                block_lines: list[str] = []
                for i in range(start, end):
                    block_lines.append(f"{i + 1}: {lines[i].rstrip()}")

                snippet = f"[{rel_path}]\n" + "\n".join(block_lines)
                score = self._score_usage_snippet(
                    model_name=model_name,
                    file_path=rel_path_str,
                    matched_line=lines[idx].strip(),
                )
                scored_snippets.append((score, snippet))

        # 去重
        unique: dict[str, int] = {}
        for score, snippet in scored_snippets:
            if snippet not in unique or score > unique[snippet]:
                unique[snippet] = score

        sorted_snippets = sorted(
            unique.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        return [snippet for snippet, _score in sorted_snippets[:30]]

    def _build_field_hints(
        self,
        legacy_model: dict[str, Any],
        usage_snippets: list[str],
    ) -> list[FieldHint]:
        hints: list[FieldHint] = []

        for field in legacy_model.get("fields", []):
            field_name = field.get("name", "")
            if not field_name:
                continue

            hint = FieldHint(field_name=field_name)

            lower_name = field_name.lower()
            relation_target = field.get("relation_target")

            if field.get("is_relation"):
                hint.looks_like_fk = True
                if relation_target:
                    hint.possible_targets = [relation_target]
                hint.notes.append("legacy 模型中该字段已经是关系字段")

            if lower_name in {"user", "operator", "creator", "created_by", "updated_by"}:
                hint.looks_like_fk = True
                hint.notes.append("字段名像登录用户/操作者，优先考虑 auth.User")
                hint.possible_targets.extend(["auth.User"])

            if lower_name in {"admin", "admin_user", "operator_admin"}:
                hint.looks_like_fk = True
                hint.notes.append("字段名像管理员补充资料，优先考虑 core.User")
                hint.possible_targets.extend(["core.User"])

            if lower_name in {"customer", "owner_customer", "billing_customer"}:
                hint.looks_like_fk = True
                hint.notes.append("字段名像客户业务主体，优先考虑 core.Customer")
                hint.possible_targets.extend(["core.Customer"])

            if lower_name in {"group", "permission", "token"}:
                hint.looks_like_fk = True
                hint.notes.append("字段名像权限/认证对象，优先考虑对应 core/auth 模型")
                hint.possible_targets.extend(["Group", "Permission", "Token"])

            if lower_name.endswith("_id"):
                hint.looks_like_fk = True
                hint.notes.append("字段名以 _id 结尾，疑似关系字段")

            if lower_name in {"username", "admin_name", "customer_name"}:
                hint.notes.append("字段名像对象快照字段，可能需要 FK + snapshot 并存")
                hint.possible_targets.extend(["Admin", "Customer"])

            if lower_name in {"action", "status", "type", "source", "used_by"}:
                hint.looks_like_enum = True
                hint.notes.append("字段名像枚举语义，建议考虑 TextChoices")

            observed_values = self._extract_observed_values(field_name, usage_snippets)
            if observed_values:
                hint.observed_values = observed_values

            hints.append(hint)

        return hints

    def _extract_observed_values(self, field_name: str, usage_snippets: list[str]) -> list[str]:
        """
        只从“实例创建 / objects.create / 显式 field=字面量”中提取候选值。
        不再分析 classmethod / 业务方法调用。
        """
        supported_fields = {"action", "status", "type", "source", "used_by"}
        if field_name not in supported_fields:
            return []

        candidates: list[str] = []

        regex_list = [
            # field="xxx" / field='xxx'
            rf"{field_name}\s*=\s*['\"]([^'\"]+)['\"]",
        ]

        for snippet in usage_snippets:
            for regex in regex_list:
                matches = re.findall(regex, snippet)
                for m in matches:
                    value = m.strip()
                    if not value:
                        continue
                    if value not in candidates:
                        candidates.append(value)

        return candidates[:20]

    def _collect_target_related_files(self, mapping: dict[str, Any]) -> list[dict[str, Any]]:
        """
        从 agent 项目中收集目标 app 相关模型文件，而不是从旧项目收集。
        """
        target_app = mapping.get("final_target_app")
        if not target_app:
            return []

        app_dir = self.agent_root / "apps" / target_app
        if not app_dir.exists():
            return []

        collected: list[dict[str, Any]] = []

        candidate_dirs = [
            app_dir / "models",
            self.agent_root / "apps" / "core" / "models",
        ]

        for base_dir in candidate_dirs:
            if not base_dir.exists():
                continue

            if base_dir.is_file():
                try:
                    collected.append({
                        "path": str(base_dir.relative_to(self.agent_root)),
                        "content": read_text(base_dir)[:4000],
                    })
                except Exception:
                    pass
                continue

            for py_file in sorted(base_dir.rglob("*.py")):
                if py_file.name == "__init__.py":
                    continue

                try:
                    collected.append({
                        "path": str(py_file.relative_to(self.agent_root)),
                        "content": read_text(py_file)[:4000],
                    })
                except Exception:
                    continue

                if len(collected) >= 8:
                    return collected

        return collected[:8]

    def _get_base_model_context(self) -> dict[str, Any]:
        return {
            "module_path": "apps.core.models.BaseModel",
            "fields": ["created_at", "updated_at"],
            "rules": [
                "普通业务模型优先继承 BaseModel",
                "继承 BaseModel 后不要重复定义 created_at / updated_at",
            ],
        }

    def _build_suggestions(self, field_hints: list[FieldHint]) -> list[str]:
        suggestions: list[str] = []

        for hint in field_hints:
            if hint.looks_like_fk:
                suggestions.append(f"{hint.field_name}: 优先考虑关系字段")
            if hint.looks_like_enum:
                suggestions.append(f"{hint.field_name}: 可考虑 TextChoices")
            if hint.observed_values:
                suggestions.append(f"{hint.field_name}: 已观察到候选值 {hint.observed_values}")

        return list(dict.fromkeys(suggestions))
