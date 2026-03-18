import ast
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from config import DEFAULT_ENCODING
from tools.fs_tools import read_text, relative_to_root
from tools.project_tools import discover_module_model_files, find_module_dir


RELATION_FIELD_TYPES = {"ForeignKey", "ManyToManyField", "OneToOneField"}

COMMON_FIELD_TYPES = {
    "CharField",
    "TextField",
    "IntegerField",
    "BigIntegerField",
    "SmallIntegerField",
    "PositiveIntegerField",
    "PositiveSmallIntegerField",
    "BooleanField",
    "DateTimeField",
    "DateField",
    "TimeField",
    "EmailField",
    "GenericIPAddressField",
    "FloatField",
    "DecimalField",
    "JSONField",
    "UUIDField",
    "SlugField",
    "FileField",
    "ImageField",
    "AutoField",
    "BigAutoField",
    "BinaryField",
    "NullBooleanField",
    "URLField",
    "ForeignKey",
    "ManyToManyField",
    "OneToOneField",
}


class ModelFieldInfo(BaseModel):
    name: str
    field_type: str
    raw_line: str
    is_relation: bool = False
    relation_type: str | None = None
    relation_target: str | None = None
    has_choices: bool = False
    null: bool | None = None
    blank: bool | None = None
    default: str | None = None

    default_expr: str | None = None
    choices_expr: str | None = None


class ModelMetaInfo(BaseModel):
    raw_lines: list[str] = Field(default_factory=list)


class ModelInfo(BaseModel):
    name: str
    file_path: str
    start_line: int
    end_line: int
    fields: list[ModelFieldInfo] = Field(default_factory=list)
    meta: ModelMetaInfo | None = None
    raw_class_header: str = ""
    constants: dict[str, Any] = Field(default_factory=dict)


class ModelAnalysisResult(BaseModel):
    module_name: str
    module_path: str
    model_files: list[str] = Field(default_factory=list)
    models: list[ModelInfo] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class ModelAnalyzer:
    def __init__(self) -> None:
        self._module_constant_cache: dict[str, dict[str, Any]] = {}
        self._module_loading: set[str] = set()

    def analyze(self, project_root: Path, module_name: str) -> ModelAnalysisResult:
        module_dir = find_module_dir(project_root, module_name)
        if not module_dir:
            raise ValueError(f"未找到 module: {module_name}")

        model_files = discover_module_model_files(project_root, module_name)
        models: list[ModelInfo] = []

        for rel_file in model_files:
            abs_file = project_root / rel_file
            models.extend(self._analyze_model_file(abs_file, project_root))

        return ModelAnalysisResult(
            module_name=module_name,
            module_path=relative_to_root(module_dir, project_root),
            model_files=model_files,
            models=models,
            suggestions=self._build_suggestions(module_name, models),
        )

    def _analyze_model_file(self, file_path: Path, project_root: Path) -> list[ModelInfo]:
        text = read_text(file_path, encoding=DEFAULT_ENCODING)

        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []

        source_lines = text.splitlines()

        available_constants = self._load_constants_from_file(file_path, project_root)
        models: list[ModelInfo] = []

        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue

            if not self._is_model_class(node):
                continue

            start_line = getattr(node, "lineno", 1)
            end_line = getattr(node, "end_lineno", start_line)

            raw_header = (
                source_lines[start_line - 1].strip()
                if 0 < start_line <= len(source_lines)
                else f"class {node.name}(...)"
            )

            fields = self._extract_fields_from_class(node, source_lines)
            meta = self._extract_meta_from_class(node, source_lines)

            if not fields:
                continue

            #  referenced_constants = self._collect_referenced_constants(fields, available_constants)
            referenced_constants = available_constants
            constants=available_constants

            models.append(
                ModelInfo(
                    name=node.name,
                    file_path=relative_to_root(file_path, project_root),
                    start_line=start_line,
                    end_line=end_line,
                    fields=fields,
                    meta=meta,
                    raw_class_header=raw_header,
                    constants=referenced_constants,
                )
            )

        return models

    def _is_model_class(self, node: ast.ClassDef) -> bool:
        for base in node.bases:
            base_name = self._expr_to_str(base) or ""
            if base_name.endswith("Model") or ".Model" in base_name:
                return True
        return False

    def _extract_fields_from_class(self, node: ast.ClassDef, source_lines: list[str]) -> list[ModelFieldInfo]:
        fields: list[ModelFieldInfo] = []

        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                targets = stmt.targets
                value = stmt.value
            elif isinstance(stmt, ast.AnnAssign):
                targets = [stmt.target]
                value = stmt.value
            else:
                continue

            if value is None or not isinstance(value, ast.Call):
                continue
            if len(targets) != 1:
                continue
            if not isinstance(targets[0], ast.Name):
                continue

            field_name = targets[0].id
            call_node = value

            field_type = self._get_field_type(call_node)
            if field_type not in COMMON_FIELD_TYPES:
                continue

            kwargs = self._extract_field_kwargs(call_node)
            is_relation = field_type in RELATION_FIELD_TYPES
            relation_target = self._extract_relation_target(call_node) if is_relation else None

            raw_line = self._get_raw_line(source_lines, stmt)

            default_expr = self._expr_to_str(kwargs.get("default"))
            choices_expr = self._expr_to_str(kwargs.get("choices"))

            fields.append(
                ModelFieldInfo(
                    name=field_name,
                    field_type=field_type,
                    raw_line=raw_line,
                    is_relation=is_relation,
                    relation_type=field_type if is_relation else None,
                    relation_target=relation_target,
                    has_choices=choices_expr is not None,
                    null=self._extract_bool_node(kwargs.get("null")),
                    blank=self._extract_bool_node(kwargs.get("blank")),
                    default=self._extract_default_literal(kwargs.get("default")),
                    default_expr=default_expr,
                    choices_expr=choices_expr,
                )
            )

        return fields

    def _extract_meta_from_class(self, node: ast.ClassDef, source_lines: list[str]) -> ModelMetaInfo | None:
        for stmt in node.body:
            if isinstance(stmt, ast.ClassDef) and stmt.name == "Meta":
                start = getattr(stmt, "lineno", None)
                end = getattr(stmt, "end_lineno", None)

                if start is None or end is None:
                    return ModelMetaInfo(raw_lines=["class Meta:"])

                raw_lines = source_lines[start - 1:end]
                return ModelMetaInfo(raw_lines=[line.rstrip() for line in raw_lines])

        return None

    def _get_field_type(self, call_node: ast.Call) -> str:
        func_name = self._expr_to_str(call_node.func) or ""
        return func_name.split(".")[-1]

    def _extract_field_kwargs(self, call_node: ast.Call) -> dict[str, ast.AST]:
        kwargs: dict[str, ast.AST] = {}
        for kw in call_node.keywords:
            if kw.arg is None:
                continue
            kwargs[kw.arg] = kw.value
        return kwargs

    def _extract_relation_target(self, call_node: ast.Call) -> str | None:
        if not call_node.args:
            return None
        expr = self._expr_to_str(call_node.args[0])
        if expr is None:
            return None
        return expr.strip("\"'")

    def _extract_bool_node(self, node: ast.AST | None) -> bool | None:
        if node is None:
            return None
        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            return node.value
        return None

    def _extract_default_literal(self, node: ast.AST | None) -> str | None:
        if node is None:
            return None
        if isinstance(node, ast.Constant):
            return repr(node.value)
        return None

    def _get_raw_line(self, source_lines: list[str], stmt: ast.AST) -> str:
        lineno = getattr(stmt, "lineno", None)
        if lineno is None or lineno < 1 or lineno > len(source_lines):
            return ""
        return source_lines[lineno - 1].strip()

    def _expr_to_str(self, node: ast.AST | None) -> str | None:
        if node is None:
            return None

        try:
            return ast.unparse(node)
        except Exception:
            pass

        if isinstance(node, ast.Name):
            return node.id

        if isinstance(node, ast.Attribute):
            base = self._expr_to_str(node.value)
            if base:
                return f"{base}.{node.attr}"
            return node.attr

        if isinstance(node, ast.Constant):
            return repr(node.value)

        if isinstance(node, ast.Subscript):
            value = self._expr_to_str(node.value)
            slice_expr = self._expr_to_str(node.slice)
            if value and slice_expr:
                return f"{value}[{slice_expr}]"
            return None

        if isinstance(node, ast.Tuple):
            items = [self._expr_to_str(x) for x in node.elts]
            items = [x for x in items if x is not None]
            return f"({', '.join(items)})"

        if isinstance(node, ast.List):
            items = [self._expr_to_str(x) for x in node.elts]
            items = [x for x in items if x is not None]
            return f"[{', '.join(items)}]"

        if isinstance(node, ast.Dict):
            pairs = []
            for k, v in zip(node.keys, node.values):
                k_str = self._expr_to_str(k)
                v_str = self._expr_to_str(v)
                if k_str is not None and v_str is not None:
                    pairs.append(f"{k_str}: {v_str}")
            return "{" + ", ".join(pairs) + "}"

        return None

    def _literal_eval_safe(self, node: ast.AST | None) -> Any:
        if node is None:
            return None

        try:
            return ast.literal_eval(node)
        except Exception:
            return self._expr_to_str(node)

    def _extract_constants_from_module(self, tree: ast.Module) -> dict[str, Any]:
        constants: dict[str, Any] = {}

        for stmt in tree.body:
            # UPPER = ...
            if isinstance(stmt, ast.Assign):
                if len(stmt.targets) != 1:
                    continue
                target = stmt.targets[0]
                if not isinstance(target, ast.Name):
                    continue
                name = target.id
                if not name.isupper():
                    continue
                constants[name] = self._literal_eval_safe(stmt.value)

            # UPPER: Type = ...
            elif isinstance(stmt, ast.AnnAssign):
                if not isinstance(stmt.target, ast.Name):
                    continue
                name = stmt.target.id
                if not name.isupper():
                    continue
                constants[name] = self._literal_eval_safe(stmt.value)
        return constants

    def _load_constants_from_file(self, file_path: Path, project_root: Path) -> dict[str, Any]:
        cache_key = str(file_path.resolve())

        if cache_key in self._module_constant_cache:
            return self._module_constant_cache[cache_key]

        if cache_key in self._module_loading:
            return {}

        self._module_loading.add(cache_key)

        try:
            text = read_text(file_path, encoding=DEFAULT_ENCODING)
            tree = ast.parse(text)
        except Exception:
            self._module_loading.discard(cache_key)
            self._module_constant_cache[cache_key] = {}
            return {}

        constants = self._extract_constants_from_module(tree)
        imported_constants = self._extract_imported_constants(tree, file_path, project_root)

        merged: dict[str, Any] = {}
        merged.update(imported_constants)
        merged.update(constants)

        self._module_loading.discard(cache_key)
        self._module_constant_cache[cache_key] = merged
        return merged

    def _extract_imported_constants(
        self,
        tree: ast.Module,
        file_path: Path,
        project_root: Path,
    ) -> dict[str, Any]:
        imported_constants: dict[str, Any] = {}

        # from xxx import ...
        for stmt in tree.body:
            if not isinstance(stmt, ast.ImportFrom):
                continue

            target_file = self._resolve_importfrom_file(stmt, file_path, project_root)
            if target_file is None or not target_file.exists():
                continue

            target_constants = self._load_constants_from_file(target_file, project_root)

            if any(alias.name == "*" for alias in stmt.names):
                imported_constants.update(target_constants)
                continue

            for alias in stmt.names:
                if alias.name in target_constants:
                    local_name = alias.asname or alias.name
                    imported_constants[local_name] = target_constants[alias.name]

        # import xxx / import xxx as yyy
        for stmt in tree.body:
            if not isinstance(stmt, ast.Import):
                continue

            for alias in stmt.names:
                target_file = self._resolve_import_file(alias.name, project_root, current_file=file_path)
                if target_file is None or not target_file.exists():
                    continue

                target_constants = self._load_constants_from_file(target_file, project_root)
                if not target_constants:
                    continue

                local_name = alias.asname or alias.name.split(".")[-1]
                imported_constants[local_name] = {
                    "__module_constants__": target_constants
                }

        return imported_constants

    def _resolve_importfrom_file(
        self,
        stmt: ast.ImportFrom,
        file_path: Path,
        project_root: Path,
    ) -> Path | None:
        module_name = stmt.module or ""

        # 显式相对导入
        if stmt.level and stmt.level > 0:
            base_dir = file_path.parent
            for _ in range(stmt.level - 1):
                base_dir = base_dir.parent

            if module_name:
                rel_parts = module_name.split(".")
                candidate = base_dir.joinpath(*rel_parts).with_suffix(".py")
                if candidate.exists():
                    return candidate

                candidate_init = base_dir.joinpath(*rel_parts, "__init__.py")
                if candidate_init.exists():
                    return candidate_init
            else:
                candidate_init = base_dir / "__init__.py"
                if candidate_init.exists():
                    return candidate_init

            return None

        # 绝对导入
        if module_name:
            parts = module_name.split(".")
            candidate = project_root.joinpath(*parts).with_suffix(".py")
            if candidate.exists():
                return candidate

            candidate_init = project_root.joinpath(*parts, "__init__.py")
            if candidate_init.exists():
                return candidate_init

        # 包内同级导入: from consts import *
        if module_name:
            sibling_candidate = file_path.parent.joinpath(*module_name.split(".")).with_suffix(".py")
            if sibling_candidate.exists():
                return sibling_candidate

            sibling_init = file_path.parent.joinpath(*module_name.split("."), "__init__.py")
            if sibling_init.exists():
                return sibling_init

        return None

    def _resolve_import_file(self, module_name: str, project_root: Path, current_file: Path | None = None) -> Path | None:
        parts = module_name.split(".")

        # 绝对导入
        candidate = project_root.joinpath(*parts).with_suffix(".py")
        if candidate.exists():
            return candidate

        candidate_init = project_root.joinpath(*parts, "__init__.py")
        if candidate_init.exists():
            return candidate_init

        # 同级导入: import consts
        if current_file is not None:
            sibling_candidate = current_file.parent.joinpath(*parts).with_suffix(".py")
            if sibling_candidate.exists():
                return sibling_candidate

            sibling_init = current_file.parent.joinpath(*parts, "__init__.py")
            if sibling_init.exists():
                return sibling_init

        return None

    def _collect_referenced_constants(
        self,
        fields: list[ModelFieldInfo],
        available_constants: dict[str, Any],
    ) -> dict[str, Any]:
        referenced_names: set[str] = set()

        for field in fields:
            expr_candidates = [
                field.default_expr,
                field.choices_expr,
                field.raw_line,
            ]
            for expr in expr_candidates:
                if not expr:
                    continue
                referenced_names.update(self._extract_uppercase_names_from_expr(expr))

        result: dict[str, Any] = {}

        # 直接常量
        for name in referenced_names:
            if name in available_constants and not (
                isinstance(available_constants[name], dict)
                and "__module_constants__" in available_constants[name]
            ):
                result[name] = available_constants[name]

        # import consts / import xxx as yyy 里的常量
        for _, value in available_constants.items():
            if not isinstance(value, dict):
                continue

            module_constants = value.get("__module_constants__")
            if not isinstance(module_constants, dict):
                continue

            for name in referenced_names:
                if name in module_constants and name not in result:
                    result[name] = module_constants[name]

        return result

    def _extract_uppercase_names_from_expr(self, expr: str) -> set[str]:
        names: set[str] = set()

        try:
            tree = ast.parse(expr, mode="eval")

            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id.isupper():
                    names.add(node.id)

                if isinstance(node, ast.Attribute) and node.attr.isupper():
                    names.add(node.attr)
        except SyntaxError:
            pass

        for token in re.findall(r"\b[A-Z][A-Z0-9_]+\b", expr):
            names.add(token)

        return names

    def _build_suggestions(self, module_name: str, models: list[ModelInfo]) -> list[str]:
        suggestions: list[str] = []

        if not models:
            suggestions.append("当前 module 未识别到明显模型类，请检查 legacy 代码中是否采用了非常规定义方式。")
            return suggestions

        if module_name == "db":
            suggestions.append("`db` 模块应视为旧系统核心领域模型层，后续重构时建议按新领域重新拆分，而不是整体迁移为一个 app。")
            suggestions.append("建议优先建立 `旧 db 模型 -> 新系统领域(app)` 的映射表，例如 asset / network / storage / customer / image。")

        relation_count = sum(1 for model in models for field in model.fields if field.is_relation)
        choices_count = sum(1 for model in models for field in model.fields if field.has_choices)
        constant_count = sum(len(model.constants) for model in models)

        if relation_count > 0:
            suggestions.append("建议优先梳理关系字段，确认 ForeignKey / ManyToMany / OneToOne 的 related_name 与删除策略。")

        if choices_count > 0:
            suggestions.append("建议将 legacy choices 元组逐步迁移到 Django 6 的 TextChoices / IntegerChoices。")

        if constant_count > 0:
            suggestions.append("已检测到字段依赖常量/枚举表达式，生成草稿时建议优先参考 constants 信息重建 choices/default。")

        for model in models:
            if model.meta is None:
                suggestions.append(f"模型 {model.name} 未发现 Meta，迁移到 Django 6 时可补充 ordering、constraints、indexes。")

            has_datetime = any(f.field_type in {"DateTimeField", "DateField"} for f in model.fields)
            if has_datetime:
                suggestions.append(f"模型 {model.name} 可统一检查时间字段规范，如 created_at / updated_at。")

            nullable_char_fields = [
                f.name for f in model.fields
                if f.field_type in {"CharField", "TextField"} and f.null is True
            ]
            if nullable_char_fields:
                suggestions.append(
                    f"模型 {model.name} 存在字符字段使用 null=True（{', '.join(nullable_char_fields)}），迁移时建议统一空值策略。"
                )

            fields_with_expr = [
                f.name for f in model.fields
                if f.default_expr or f.choices_expr
            ]
            if fields_with_expr:
                suggestions.append(
                    f"模型 {model.name} 存在依赖表达式/常量的字段（{', '.join(fields_with_expr)}），建议迁移时显式重建 choices/default。"
                )

        return list(dict.fromkeys(suggestions))
