from pathlib import Path
from typing import Any

from tools.json_tools import read_json


ENUM_LIKE_FIELD_NAMES = {
    "status",
    "type",
    "action",
    "source",
    "used_by",
    "cpu_mode",
    "disk_type",
    "role",
    "config_version",
}


class EnumAnalyzer:
    def __init__(
        self,
        db_models_analysis_json: Path,
        field_semantics_json: Path | None = None,
    ):
        self.db_models = read_json(db_models_analysis_json)
        self.field_semantics = (
            read_json(field_semantics_json)
            if field_semantics_json and field_semantics_json.exists()
            else {"field_semantics": []}
        )
        self.semantic_index = self._build_semantic_index()

    def analyze(self) -> dict[str, Any]:
        enums: list[dict[str, Any]] = []

        for model in self.db_models.get("models", []):
            model_name = model.get("name")
            constants = model.get("constants", {}) or {}

            for field in model.get("fields", []):
                enum_info = self._analyze_field_enum(
                    model_name=model_name,
                    field=field,
                    constants=constants,
                )
                if enum_info:
                    enums.append(enum_info)

        return {
            "enums": enums,
        }

    def _build_semantic_index(self) -> dict[tuple[str, str], str]:
        result: dict[tuple[str, str], str] = {}
        for item in self.field_semantics.get("field_semantics", []):
            model = item.get("model")
            field = item.get("field")
            semantic = item.get("semantic")
            if model and field and semantic:
                result[(model, field)] = semantic
        return result

    def _analyze_field_enum(
        self,
        model_name: str,
        field: dict[str, Any],
        constants: dict[str, Any],
    ) -> dict[str, Any] | None:
        field_name = field.get("name")
        if not field_name:
            return None

        lower_name = field_name.lower()
        if lower_name not in ENUM_LIKE_FIELD_NAMES:
            return None

        candidate_constant_names = self._guess_constant_names(field_name)

        matched_constant_name = None
        matched_choices = None

        for const_name in candidate_constant_names:
            if const_name in constants:
                normalized = self._normalize_choices(constants[const_name])
                if normalized:
                    matched_constant_name = const_name
                    matched_choices = normalized
                    break

        # 如果字段本身有 choices_expr，也尝试从 constants 中找包含该名字的常量
        if matched_constant_name is None:
            for const_name, value in constants.items():
                if lower_name in const_name.lower():
                    normalized = self._normalize_choices(value)
                    if normalized:
                        matched_constant_name = const_name
                        matched_choices = normalized
                        break

        if matched_constant_name is None or matched_choices is None:
            return None

        enum_name = self._build_enum_name(model_name, field_name)

        return {
            "model": model_name,
            "field": field_name,
            "enum_name": enum_name,
            "source_constant": matched_constant_name,
            "enum_type": "TextChoices",
            "choices": matched_choices,
            "semantic": self.semantic_index.get((model_name, field_name)),
        }

    def _guess_constant_names(self, field_name: str) -> list[str]:
        upper = field_name.upper()
        print(upper)
        return [
            upper,
            f"{upper}S",
            f"{upper}_TYPE",
            f"{upper}_STATUS",
            f"{upper}_MODES",
            f"{upper}_VERSION",
            f"VIRTUAL_SERVER_{upper}",
        ]

    def _normalize_choices(self, value: Any) -> list[dict[str, str]] | None:
        """
        支持：
        - [("a", "A"), ("b", "B")]
        - ["SAS", "SSD"]
        """
        if not isinstance(value, list):
            return None

        result: list[dict[str, str]] = []

        for item in value:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                key = str(item[0])
                label = str(item[1])
                result.append(
                    {
                        "value": key,
                        "label": label,
                        "member_name": self._to_member_name(key),
                    }
                )
            elif isinstance(item, str):
                result.append(
                    {
                        "value": item,
                        "label": item,
                        "member_name": self._to_member_name(item),
                    }
                )
            else:
                return None

        return result or None

    def _to_member_name(self, value: str) -> str:
        cleaned = value.replace("-", "_").replace(" ", "_")
        cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch == "_")
        cleaned = cleaned.upper()
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        cleaned = cleaned.strip("_")
        if not cleaned:
            cleaned = "UNKNOWN"
        if cleaned[0].isdigit():
            cleaned = f"VALUE_{cleaned}"
        return cleaned

    def _build_enum_name(self, model_name: str, field_name: str) -> str:
        parts = field_name.split("_")
        field_pascal = "".join(p.capitalize() for p in parts)
        return f"{model_name}{field_pascal}"
