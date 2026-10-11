from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class Diagnostic:
    line: int
    code: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    allowed: bool
    diagnostics: tuple[Diagnostic, ...]


class CodePolicy(ast.NodeVisitor):
    DANGEROUS_BUILTINS = {
        "__import__",
        "breakpoint",
        "compile",
        "delattr",
        "dir",
        "eval",
        "exec",
        "getattr",
        "globals",
        "help",
        "input",
        "locals",
        "open",
        "setattr",
        "vars",
    }

    def __init__(self, *, allowed_imports=(), capabilities=()):
        self.allowed_imports = frozenset(allowed_imports)
        self.capabilities = frozenset(capabilities)
        self._diagnostics: list[Diagnostic] = []
        self._variables: dict[str, str] = {}
        self._class_aliases: dict[str, str] = {}

    def validate(self, code: str) -> ValidationResult:
        self._diagnostics = []
        self._variables = {}
        self._class_aliases = {
            name: name.lower()
            for name in ("AI", "Arm", "Camera", "Face", "Hand", "Lidar", "Vision", "Voice")
        }
        try:
            tree = ast.parse(code)
        except SyntaxError as error:
            diagnostic = Diagnostic(
                line=error.lineno or 1,
                code="SYNTAX_ERROR",
                message="Python语法不完整，请检查括号、冒号和缩进。",
            )
            return ValidationResult(False, (diagnostic,))
        self.visit(tree)
        return ValidationResult(not self._diagnostics, tuple(self._diagnostics))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root not in self.allowed_imports:
                self._add(node, "IMPORT_NOT_ALLOWED", f"此实验不允许导入 {root}。")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (node.module or "").split(".", 1)[0]
        if node.level or root not in self.allowed_imports or any(alias.name == "*" for alias in node.names):
            self._add(node, "IMPORT_NOT_ALLOWED", f"此实验不允许导入 {root or '相对模块'}。")
        elif root == "aibox":
            for alias in node.names:
                if alias.name in self._class_aliases:
                    self._class_aliases[alias.asname or alias.name] = alias.name.lower()

    def visit_Assign(self, node: ast.Assign) -> None:
        class_name = self._constructed_class(node.value)
        if isinstance(node.value, ast.Name):
            class_name = self._class_aliases.get(node.value.id)
        if class_name:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._variables[target.id] = class_name
                    self._class_aliases[target.id] = class_name
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "__builtins__":
            self._add(node, "BUILTIN_NOT_ALLOWED", "不允许访问 Python 内置命名空间。")
            return
        if isinstance(node.ctx, ast.Load) and node.id in self.DANGEROUS_BUILTINS:
            self._add(node, "BUILTIN_NOT_ALLOWED", f"不允许使用 {node.id}。")

    def visit_Call(self, node: ast.Call) -> None:
        capability = self._capability(node.func)
        if capability and capability not in self.capabilities:
            self._add(node, "CAPABILITY_NOT_ALLOWED", f"当前实验未开放 {capability}。")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__"):
            self._add(node, "ATTRIBUTE_NOT_ALLOWED", "不允许访问双下划线属性。")
        self.generic_visit(node)

    def _constructed_class(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return self._class_aliases.get(node.func.id)
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "aibox"
        ):
            return self._class_aliases.get(node.attr)
        return None

    def _capability(self, node: ast.AST) -> str | None:
        if not isinstance(node, ast.Attribute):
            return None
        owner = node.value
        if isinstance(owner, ast.Name) and owner.id in self._variables:
            return f"{self._variables[owner.id]}.{node.attr}"
        class_name = self._constructed_class(owner)
        if class_name:
            return f"{class_name}.{node.attr}"
        return None

    def _add(self, node: ast.AST, code: str, message: str) -> None:
        self._diagnostics.append(Diagnostic(getattr(node, "lineno", 1), code, message))

