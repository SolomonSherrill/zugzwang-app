"""PyQt is deleted (O2, 2026-10-22), so "no Qt in `zugzwang/` or the sidecar" is now true
without exceptions. This keeps it true: an AST walk of every module, so a deferred import
inside a function body is caught and prose mentioning Qt is not."""

import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_MODULES = sorted([*(_REPO / "zugzwang").rglob("*.py"), *(_REPO / "sidecar").rglob("*.py")])


@pytest.mark.parametrize("path", _MODULES, ids=lambda p: str(p.relative_to(_REPO)))
def test_no_module_imports_qt(path):
    imported = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not {"PyQt6", "PyQt5", "PySide6"} & imported
