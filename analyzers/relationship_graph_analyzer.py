from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tools.json_tools import read_json


class GraphNode(BaseModel):
    model: str
    file_path: str = ""
    target_app: str | None = None
    target_domain: str | None = None


class GraphEdge(BaseModel):
    source_model: str
    field_name: str
    relation_type: str
    target_model: str
    semantic: str | None = None
    target_app: str | None = None
    target_domain: str | None = None


class RelationshipGraphResult(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class RelationshipGraphAnalyzer:
    def __init__(
        self,
        db_models_analysis_json: Path,
        final_mapping_json: Path,
        field_semantics_json: Path | None = None,
    ):
        self.db_models = read_json(db_models_analysis_json)
        self.final_mapping = read_json(final_mapping_json)
        self.field_semantics = read_json(field_semantics_json) if field_semantics_json and field_semantics_json.exists() else {"field_semantics": []}

        self.mapping_index = self._build_mapping_index()
        self.semantic_index = self._build_semantic_index()

    def analyze(self) -> dict[str, Any]:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        for model in self.db_models.get("models", []):
            model_name = model.get("name")
            file_path = model.get("file_path", "")
            mapping = self.mapping_index.get(model_name, {})

            nodes.append(
                GraphNode(
                    model=model_name,
                    file_path=file_path,
                    target_app=mapping.get("final_target_app"),
                    target_domain=mapping.get("final_target_domain"),
                )
            )

            for field in model.get("fields", []):
                if not field.get("is_relation"):
                    continue

                target_model = self._normalize_relation_target(field.get("relation_target"))
                semantic = self.semantic_index.get((model_name, field.get("name")))

                target_mapping = self.mapping_index.get(target_model, {})

                edges.append(
                    GraphEdge(
                        source_model=model_name,
                        field_name=field.get("name"),
                        relation_type=field.get("relation_type") or field.get("field_type") or "Relation",
                        target_model=target_model,
                        semantic=semantic,
                        target_app=target_mapping.get("final_target_app"),
                        target_domain=target_mapping.get("final_target_domain"),
                    )
                )

        result = RelationshipGraphResult(
            nodes=nodes,
            edges=edges,
            summary=self._build_summary(nodes, edges),
        )
        return result.model_dump()

    def _build_mapping_index(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in self.final_mapping.get("mappings", []):
            source_model = item.get("source_model")
            if source_model:
                result[source_model] = item
        return result

    def _build_semantic_index(self) -> dict[tuple[str, str], str]:
        result: dict[tuple[str, str], str] = {}
        for item in self.field_semantics.get("field_semantics", []):
            model = item.get("model")
            field = item.get("field")
            semantic = item.get("semantic")
            if model and field and semantic:
                result[(model, field)] = semantic
        return result

    def _normalize_relation_target(self, relation_target: Any) -> str:
        if not relation_target:
            return "Unknown"

        target = str(relation_target).strip("\"'")

        # 例如 "app.Model" → "Model"
        if "." in target:
            target = target.split(".")[-1]

        return target

    def _build_summary(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> list[str]:
        summary: list[str] = []

        summary.append(f"共识别模型节点 {len(nodes)} 个")
        summary.append(f"共识别关系边 {len(edges)} 条")

        app_counts: dict[str, int] = {}
        for node in nodes:
            app = node.target_app or "unknown"
            app_counts[app] = app_counts.get(app, 0) + 1

        for app, count in sorted(app_counts.items(), key=lambda x: x[0]):
            summary.append(f"{app}: {count} 个模型节点")

        semantic_counts: dict[str, int] = {}
        for edge in edges:
            if edge.semantic:
                semantic_counts[edge.semantic] = semantic_counts.get(edge.semantic, 0) + 1

        for semantic, count in sorted(semantic_counts.items(), key=lambda x: x[0]):
            summary.append(f"语义关系 {semantic}: {count} 条")

        return summary
