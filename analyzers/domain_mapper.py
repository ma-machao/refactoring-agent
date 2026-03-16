from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tools.json_tools import read_json


class TargetAppInfo(BaseModel):
    name: str
    domains: list[str] = Field(default_factory=list)
    layers: list[str] = Field(default_factory=list)
    audiences: list[str] = Field(default_factory=list)


class MappingItem(BaseModel):
    source_model: str
    source_file: str
    suggested_app: str
    suggested_domain: str
    suggested_model_file: str
    action: str
    confidence: str
    reasons: list[str] = Field(default_factory=list)


class DomainMappingResult(BaseModel):
    source_module: str
    total_models: int
    target_apps: list[str] = Field(default_factory=list)
    mappings: list[MappingItem] = Field(default_factory=list)
    unmapped_models: list[str] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class DomainMapper:
    def __init__(self, blueprint_path: Path):
        self.blueprint_path = blueprint_path
        self.blueprint = read_json(blueprint_path)
        self.target_apps = self._load_target_apps()

    def _load_target_apps(self) -> dict[str, TargetAppInfo]:
        apps = self.blueprint.get("apps", {})
        result: dict[str, TargetAppInfo] = {}

        for app_name, info in apps.items():
            result[app_name] = TargetAppInfo(
                name=app_name,
                domains=info.get("domains", []),
                layers=info.get("layers", []),
                audiences=info.get("audiences", []),
            )

        return result

    def map_db_models(self, db_models_analysis_json: Path) -> DomainMappingResult:
        source = read_json(db_models_analysis_json)

        module_name = source.get("module_name", "db")
        models = source.get("models", [])

        mappings: list[MappingItem] = []
        unmapped_models: list[str] = []

        for model in models:
            mapped = self._map_single_model(model)
            if mapped is None:
                unmapped_models.append(model["name"])
                continue
            mappings.append(mapped)

        summary = self._build_summary(mappings, unmapped_models)

        return DomainMappingResult(
            source_module=module_name,
            total_models=len(models),
            target_apps=list(self.target_apps.keys()),
            mappings=mappings,
            unmapped_models=unmapped_models,
            summary=summary,
        )

    def _map_single_model(self, model: dict[str, Any]) -> MappingItem | None:
        model_name = model["name"]
        source_file = model["file_path"]

        # 1. 先走 blueprint 自动匹配
        blueprint_match = self._match_by_blueprint(model_name)
        if blueprint_match is not None:
            app, domain = blueprint_match
            return MappingItem(
                source_model=model_name,
                source_file=source_file,
                suggested_app=app,
                suggested_domain=domain,
                suggested_model_file=f"apps/{app}/models/{domain}.py",
                action="keep",
                confidence="high",
                reasons=[
                    "通过 target blueprint 自动匹配 domain",
                ],
            )

        # 2. 再走特殊业务规则
        special_match = self._special_rule_map(model_name, source_file)
        if special_match is not None:
            app, domain, action, confidence, reasons = special_match
            return MappingItem(
                source_model=model_name,
                source_file=source_file,
                suggested_app=app,
                suggested_domain=domain,
                suggested_model_file=f"apps/{app}/models/{domain}.py",
                action=action,
                confidence=confidence,
                reasons=reasons,
            )

        # 3. 最后兜底 review
        return None

    def _match_by_blueprint(self, model_name: str) -> tuple[str, str] | None:
        snake_name = self._snake(model_name)

        # 先做精确匹配
        for app_name, app_info in self.target_apps.items():
            for domain in app_info.domains:
                if snake_name == domain:
                    return app_name, domain

        # 再做轻微兼容匹配
        normalized_model = self._normalize_domain_name(snake_name)

        for app_name, app_info in self.target_apps.items():
            for domain in app_info.domains:
                normalized_domain = self._normalize_domain_name(domain)
                if normalized_model == normalized_domain:
                    return app_name, domain

        return None

    def _special_rule_map(
        self,
        model_name: str,
        source_file: str,
    ) -> tuple[str, str, str, str, list[str]] | None:
        name = model_name.lower()
        source = source_file.lower()

        # core: 某些模型即使 blueprint 有，也可能需要特殊动作
        if model_name in {"User"}:
            return "core", "customer", "split", "medium", [
                "User 在旧系统中通常职责过重",
                "建议归入 core，并在后续阶段继续拆分 admin/customer/auth 相关职责",
            ]

        if model_name in {"Token"}:
            return "core", "token", "normalize", "medium", [
                "Token 属于认证/会话体系",
                "建议归入 core.token",
            ]

        if model_name in {"Permission"}:
            return "core", "permission", "normalize", "medium", [
                "Permission 属于权限体系",
                "建议归入 core.permission",
            ]

        if model_name in {"Group"}:
            return "core", "group", "normalize", "medium", [
                "Group 属于权限分组体系",
                "建议归入 core.group",
            ]

        # database
        if "database" in source or model_name.startswith("Database"):
            return "database", self._snake(model_name), "keep", "medium", [
                "数据库服务相关模型",
                "按文件来源和命名判断可先归入 database app",
            ]

        # audit
        if "log" in name or "audit" in name:
            return "audit", self._snake(model_name), "move", "medium", [
                "日志/审计类模型",
                "模型名包含 log/audit 特征",
            ]

        # event
        if model_name in {"ImageJob", "NetworkJob", "CloudVolumeJob", "Job"}:
            return "event", self._snake(model_name), "move", "medium", [
                "任务/事件相关模型",
                "建议归入 event app",
            ]

        # billing
        if model_name in {"Charge"}:
            return "billing", "charge", "move", "medium", [
                "账单/计费相关模型",
                "建议归入 billing app",
            ]

        return None

    def _normalize_domain_name(self, value: str) -> str:
        return value.replace("__", "_").replace("-", "_").lower()

    def _snake(self, name: str) -> str:
        chars: list[str] = []
        for i, ch in enumerate(name):
            if i > 0 and ch.isupper() and (not name[i - 1].isupper()):
                chars.append("_")
            chars.append(ch.lower())
        return "".join(chars)

    def _build_summary(self, mappings: list[MappingItem], unmapped_models: list[str]) -> list[str]:
        summary: list[str] = []

        by_app: dict[str, int] = {}
        for item in mappings:
            by_app[item.suggested_app] = by_app.get(item.suggested_app, 0) + 1

        for app, count in sorted(by_app.items(), key=lambda x: x[0]):
            summary.append(f"{app}: {count} 个模型映射")

        if unmapped_models:
            summary.append(f"仍有 {len(unmapped_models)} 个模型未映射，需要人工确认或交给 LLM 复核")

        if not unmapped_models:
            summary.append("当前规则与 blueprint 已覆盖全部识别到的模型")

        return summary
