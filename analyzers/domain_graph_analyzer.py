from pathlib import Path
from typing import Any

from tools.json_tools import read_json


class DomainGraphAnalyzer:

    def __init__(
        self,
        relationship_graph_json: Path,
    ):
        self.graph = read_json(relationship_graph_json)

    def analyze(self) -> dict[str, Any]:

        nodes = self.graph.get("nodes", [])
        edges = self.graph.get("edges", [])

        domains: dict[str, set[str]] = {}

        for node in nodes:
            domain = node.get("target_app") or "unknown"
            model = node.get("model")

            domains.setdefault(domain, set()).add(model)

        domain_relations: list[dict[str, Any]] = []

        for edge in edges:

            source_model = edge.get("source_model")
            target_model = edge.get("target_model")

            source_domain = self._find_domain(source_model, nodes)
            target_domain = self._find_domain(target_model, nodes)

            if source_domain != target_domain:

                domain_relations.append(
                    {
                        "source_domain": source_domain,
                        "target_domain": target_domain,
                        "via_model": source_model,
                        "relation": edge.get("field_name"),
                    }
                )

        return {
            "domains": [
                {
                    "domain": domain,
                    "models": sorted(models),
                }
                for domain, models in domains.items()
            ],
            "cross_domain_relations": domain_relations,
        }

    def _find_domain(self, model: str, nodes: list[dict]) -> str:

        for node in nodes:
            if node.get("model") == model:
                return node.get("target_app") or "unknown"

        return "unknown"
