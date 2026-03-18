import ast
from pathlib import Path
from typing import Any

from tools.fs_tools import find_files_by_suffixes, read_text
from config import IGNORE_DIRS


ACTION_KEYWORDS = {
    "start": ["start", "boot", "poweron"],
    "stop": ["stop", "shutdown", "poweroff"],
    "reboot": ["reboot", "restart"],
    "suspend": ["suspend", "pause"],
    "resume": ["resume", "unpause"],
    "force_stop": ["force", "kill"],
}


class ActionFlowAnalyzer:
    def __init__(self, project_root: Path):
        self.project_root = project_root

    def analyze(self, model_name: str) -> dict[str, Any]:
        py_files = find_files_by_suffixes(
            self.project_root,
            suffixes={".py"},
            ignore_dirs=IGNORE_DIRS,
        )

        actions: dict[str, dict] = {}

        for action_name in ACTION_KEYWORDS:
            actions[action_name] = {
                "name": action_name,
                "keywords": ACTION_KEYWORDS[action_name],
                "usages": [],
                "files": set(),
                "state_changes": [],
            }

        for file in py_files:
            try:
                content = read_text(file)
                tree = ast.parse(content)
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    call_name = self._get_call_name(node)

                    if not call_name:
                        continue

                    for action_name, config in ACTION_KEYWORDS.items():
                        if any(k in call_name.lower() for k in config):
                            snippet = self._extract_snippet(content, node)

                            actions[action_name]["usages"].append(
                                {
                                    "file": str(file),
                                    "call": call_name,
                                    "snippet": snippet,
                                }
                            )
                            actions[action_name]["files"].add(str(file))

                # 状态变更检测（简单版）
                if isinstance(node, ast.Assign):
                    targets = [self._get_name(t) for t in node.targets]
                    if any(t in ["status", "state", "power_state"] for t in targets):
                        value = self._get_name(node.value)
                        if value:
                            for action in actions.values():
                                action["state_changes"].append(f"{targets} -> {value}")

        # 转换 set
        for action in actions.values():
            action["files"] = list(action["files"])

        return {
            "model": model_name,
            "actions": [
                action for action in actions.values() if action["usages"]
            ],
        }

    def _get_call_name(self, node: ast.Call) -> str | None:
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        if isinstance(node.func, ast.Name):
            return node.func.id
        return None

    def _get_name(self, node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Constant):
            return str(node.value)
        return None

    def _extract_snippet(self, content: str, node: ast.AST) -> str:
        lines = content.splitlines()
        if hasattr(node, "lineno"):
            start = max(node.lineno - 2, 0)
            end = min(node.lineno + 2, len(lines))
            return "\n".join(lines[start:end])
        return ""
