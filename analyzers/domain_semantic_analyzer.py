from pathlib import Path
from typing import Any

from tools.json_tools import read_json


class DomainSemanticAnalyzer:
    """
    分析 legacy 模型字段的业务语义
    """

    def __init__(
        self,
        db_models_analysis_json: Path,
        project_rules_json: Path,
    ):
        self.models = read_json(db_models_analysis_json)
        self.rules = read_json(project_rules_json)

    def analyze(self) -> dict[str, Any]:

        results = []

        for model in self.models["models"]:

            model_name = model["name"]

            for field in model["fields"]:

                semantic = self._infer_field_semantic(
                    model_name,
                    field,
                )

                if semantic is None:
                    continue

                results.append(
                    {
                        "model": model_name,
                        "field": field["name"],
                        "semantic": semantic,
                    }
                )

        return {
            "field_semantics": results
        }

    def _infer_field_semantic(self, model_name: str, field: dict) -> str | None:

        field_name = field["name"].lower()

        # operator / creator
        if field_name in {"operator", "creator", "created_by", "updated_by"}:
            return "operator"

        # customer
        if field_name in {"customer", "owner_customer", "billing_customer"}:
            return "customer"

        # legacy user
        if field_name == "user":

            # 根据模型类型判断
            resource_models = {
                "VirtualServer", "CloudVolume", "Backup",
                "LoadBalancer", "Database", "DirectLink", "Image", "Network",
                "Router", "PhysicalServer", "SecurityGroup", "SSHPublicKey",
                "Uplink", "CloudVolume"
            }

            if model_name in resource_models:
                return "customer"

            if "log" in model_name.lower():
                return "operator"

        return None
