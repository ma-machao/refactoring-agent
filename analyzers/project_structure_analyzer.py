from pathlib import Path
from typing import Any


class ProjectStructureAnalyzer:
    def __init__(self, project_root: Path):
        self.project_root = project_root

    def analyze(self) -> dict[str, Any]:
        apps_dir = self.project_root / "apps"
        if not apps_dir.exists():
            raise ValueError(f"未找到 apps 目录: {apps_dir}")

        apps: list[dict[str, Any]] = []

        for app_dir in sorted(p for p in apps_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
            app_info = {
                "app": app_dir.name,
                "layers": self._scan_app_layers(app_dir),
            }
            apps.append(app_info)

        return {
            "apps": apps,
        }

    def _scan_app_layers(self, app_dir: Path) -> list[dict[str, Any]]:
        layer_specs = [
            ("models", app_dir / "models"),
            ("serializers", app_dir / "serializers"),
            ("services", app_dir / "services"),
            ("views", app_dir / "views"),
            ("urls", app_dir / "urls"),
            ("queries", app_dir / "queries"),
            ("permissions", app_dir / "permissions"),
            ("rbac", app_dir / "rbac"),
            ("management", app_dir / "management"),
        ]

        layers: list[dict[str, Any]] = []

        for layer_name, layer_path in layer_specs:
            if not layer_path.exists():
                continue

            layers.append({
                "layer": layer_name,
                "tree": self._build_tree(layer_path, app_dir),
            })

        return layers

    def _build_tree(self, base_path: Path, app_dir: Path) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        if base_path.is_file():
            return [{
                "type": "file",
                "name": base_path.name,
                "path": str(base_path.relative_to(app_dir)),
            }]

        children = sorted(base_path.iterdir(), key=lambda p: (p.is_file(), p.name))

        for child in children:
            if child.name.startswith(".") or child.name == "__pycache__":
                continue

            if child.is_dir():
                result.append({
                    "type": "dir",
                    "name": child.name,
                    "path": str(child.relative_to(app_dir)),
                    "children": self._build_tree(child, app_dir),
                })
            else:
                result.append({
                    "type": "file",
                    "name": child.name,
                    "path": str(child.relative_to(app_dir)),
                })

        return result
