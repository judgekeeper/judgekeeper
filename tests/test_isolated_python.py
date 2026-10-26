"""Every Python judgekeeper starts for itself runs isolated (`-I`): no current folder or script
folder on its path, no PYTHON* variables, no user site. So a project's `json.py` never runs in
it. The project's own Python, which `fix` and `check` run on purpose, is not this one."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "judgekeeper"


def _is_sys_executable(node: ast.AST) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "executable"
            and isinstance(node.value, ast.Name) and node.value.id == "sys")


def _starts() -> list[tuple[str, int, list[ast.AST]]]:
    """Each call whose first argument is a list starting with sys.executable: where, and the
    list's items."""
    found = []
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and node.args
                    and isinstance(node.args[0], ast.List) and node.args[0].elts
                    and _is_sys_executable(node.args[0].elts[0])):
                found.append((f"{path.relative_to(SRC)}:{node.lineno}", node.args[0].elts))
    return found


def test_every_python_judgekeeper_starts_for_itself_is_isolated():
    starts = _starts()
    assert starts, "no process started with sys.executable was found"
    for where, argv in starts:
        flags = [a.value for a in argv[1:] if isinstance(a, ast.Constant)]
        assert "-I" in flags, f"{where} starts sys.executable without -I"
