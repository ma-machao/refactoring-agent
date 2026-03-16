from pathlib import Path
from typing import Any

from tools.fs_tools import read_text
from tools.json_tools import read_json


class ReferenceSelector:
    def __init__(
        self,
        project_root: Path,
        relationship_graph_json: Path,
        project_structure_json: Path,
        reference_models_json: Path | None = None,
    ):
        self.project_root = project_root
        self.graph = self._safe_read_json(relationship_graph_json)
        self.structure = self._safe_read_json(project_structure_json)
        self.reference_models = self._safe_read_json(reference_models_json) if reference_models_json else {}

        self._whitelist_paths = self._build_whitelist_path_set()
        self._core_whitelist_paths = set(self.reference_models.get("core", []))

    def select_model_references(
        self,
        model_name: str,
        target_app: str,
        limit: int = 6,
        max_chars_per_file: int = 4000,
    ) -> list[dict[str, Any]]:
        related_models = self._find_related_models(model_name)

        candidates: list[dict[str, Any]] = []

        # 1. 图驱动：当前模型 + 直接相关模型
        for related_model in related_models:
            model_file = self._find_model_file(related_model)
            if not model_file:
                continue

            candidate = self._build_candidate(
                model_name=model_name,
                related_model=related_model,
                model_file=model_file,
                target_app=target_app,
                max_chars_per_file=max_chars_per_file,
            )
            if candidate:
                candidates.append(candidate)

        # 2. 白名单增强：core 永远值得参考
        for model_file in sorted(self._core_whitelist_paths):
            candidate = self._build_candidate(
                model_name=model_name,
                related_model=self._infer_model_name_from_path(model_file),
                model_file=model_file,
                target_app=target_app,
                max_chars_per_file=max_chars_per_file,
                force_bonus=120,
            )
            if candidate:
                candidates.append(candidate)

        # 3. 白名单增强：target_app 对应的参考文件
        for model_file in sorted(self.reference_models.get(target_app, [])):
            candidate = self._build_candidate(
                model_name=model_name,
                related_model=self._infer_model_name_from_path(model_file),
                model_file=model_file,
                target_app=target_app,
                max_chars_per_file=max_chars_per_file,
                force_bonus=100,
            )
            if candidate:
                candidates.append(candidate)

        # 去重：同 path 只保留最高分
        dedup: dict[str, dict[str, Any]] = {}
        for item in candidates:
            path = item["path"]
            if path not in dedup or item["score"] > dedup[path]["score"]:
                dedup[path] = item

        result = sorted(
            dedup.values(),
            key=lambda x: (-x["score"], x["path"]),
        )[:limit]

        # 去掉内部 score，避免污染 prompt
        cleaned: list[dict[str, Any]] = []
        for item in result:
            cleaned.append(
                {
                    "model": item["model"],
                    "path": item["path"],
                    "content": item["content"],
                }
            )

        return cleaned

    # -------------------------
    # internal
    # -------------------------

    def _safe_read_json(self, path: Path | None) -> dict[str, Any]:
        if path is None or not path.exists():
            return {}
        return read_json(path)

    def _build_whitelist_path_set(self) -> set[str]:
        paths: set[str] = set()
        for _, items in self.reference_models.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, str):
                    paths.add(item)
        return paths

    def _build_candidate(
        self,
        model_name: str,
        related_model: str,
        model_file: str,
        target_app: str,
        max_chars_per_file: int,
        force_bonus: int = 0,
    ) -> dict[str, Any] | None:
        abs_path = self.project_root / model_file
        if not abs_path.exists():
            return None

        try:
            content = read_text(abs_path, encoding="utf-8")[:max_chars_per_file]
        except Exception:
            return None

        return {
            "model": related_model,
            "path": model_file,
            "content": content,
            "score": self._score_candidate(
                model_name=model_name,
                related_model=related_model,
                path=model_file,
                target_app=target_app,
            ) + force_bonus,
        }

    def _find_related_models(self, model_name: str) -> list[str]:
        """
        当前模型 + 与它直接相连的模型
        """
        edges = self.graph.get("edges", [])
        related: set[str] = {model_name}

        for edge in edges:
            source_model = edge.get("source_model")
            target_model = edge.get("target_model")

            if source_model == model_name and target_model:
                related.add(target_model)

            if target_model == model_name and source_model:
                related.add(source_model)

        return sorted(related)

    def _find_model_file(self, model_name: str) -> str | None:
        """
        从 project_structure_graph.json 里找真实的 models 文件路径
        """
        apps = self.structure.get("apps", [])

        expected_file_name = self._snake(model_name) + ".py"

        for app in apps:
            app_name = app.get("app")
            for layer in app.get("layers", []):
                if layer.get("layer") != "models":
                    continue

                hit = self._search_tree_for_file(
                    tree=layer.get("tree", []),
                    expected_file_name=expected_file_name,
                    app_name=app_name,
                )
                if hit:
                    return hit

        return None

    def _search_tree_for_file(
        self,
        tree: list[dict[str, Any]],
        expected_file_name: str,
        app_name: str,
    ) -> str | None:
        for item in tree:
            item_type = item.get("type")
            if item_type == "file":
                name = item.get("name")
                path = item.get("path")
                if name == expected_file_name and path:
                    return f"apps/{app_name}/{path}"

            elif item_type == "dir":
                children = item.get("children", [])
                hit = self._search_tree_for_file(
                    tree=children,
                    expected_file_name=expected_file_name,
                    app_name=app_name,
                )
                if hit:
                    return hit

        return None

    def _score_candidate(
        self,
        model_name: str,
        related_model: str,
        path: str,
        target_app: str,
    ) -> int:
        score = 0

        # 当前模型自身最优先
        if related_model == model_name:
            score += 100

        # 同 app 优先
        if path.startswith(f"apps/{target_app}/"):
            score += 50

        # models 文件天然加分
        if "/models/" in path:
            score += 20

        # 白名单文件额外加分
        if path in self._whitelist_paths:
            score += 80

        # core 白名单再加一层分，几乎每次都值得参考
        if path in self._core_whitelist_paths:
            score += 40

        # 某些基础模型适度加分
        lower_model = related_model.lower()
        if lower_model in {"customer", "admin", "image", "physical_server", "ipaddress"}:
            score += 10

        return score

    def _infer_model_name_from_path(self, path: str) -> str:
        file_name = Path(path).stem
        parts = file_name.split("_")
        return "".join(part.capitalize() for part in parts)

    def _snake(self, name: str) -> str:
        chars: list[str] = []
        for i, ch in enumerate(name):
            if ch.isupper() and i > 0:
                prev = name[i - 1]
                if prev.islower() or (i + 1 < len(name) and name[i + 1].islower()):
                    chars.append("_")
            chars.append(ch.lower())
        return "".join(chars)
