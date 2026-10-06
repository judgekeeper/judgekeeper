"""Every text file judgekeeper (or a script or a test) reads or writes says UTF-8.

Without `encoding=`, Python uses the system's encoding: cp1252 on most Windows machines, so a
file with "·" or an emoji reads as garbage or fails there. This scans the code for `open()`,
`.open()`, `.read_text()` and `.write_text()` calls with no `encoding=`; binary modes, and
`open` calls that do not open a text file (a browser, a web request, a tar archive), are fine.
(Ruff's unspecified-encoding rule is a preview rule and misses most `Path` calls.)
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDERS = ("src", "scripts", "tests")
NOT_TEXT_FILES = {"webbrowser", "self._opener", "tarfile"}


def _mode(call: ast.Call) -> str:
    modes = [a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    modes += [k.value.value for k in call.keywords
              if k.arg == "mode" and isinstance(k.value, ast.Constant)]
    return "".join(str(m) for m in modes)


def unstated(path: Path, root: Path = ROOT) -> list[str]:
    """`file:line call` for each text read or write in `path` with no encoding."""
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id == "open":
            name = "open"
        elif isinstance(f, ast.Attribute) and f.attr in ("open", "read_text", "write_text"):
            if f.attr == "open" and ast.unparse(f.value) in NOT_TEXT_FILES:
                continue
            name = f.attr
        else:
            continue
        if any(k.arg == "encoding" for k in node.keywords) or "b" in _mode(node):
            continue
        if any(k.arg is None for k in node.keywords):  # **kwargs: cannot tell
            continue
        out.append((node.lineno, f"{path.relative_to(root).as_posix()}:{node.lineno} {name}"))
    return [text for _, text in sorted(out)]


def test_every_text_read_and_write_says_utf_8():
    found = [hit for folder in FOLDERS for path in sorted((ROOT / folder).rglob("*.py"))
             for hit in unstated(path)]
    assert found == [], f"{len(found)} calls without encoding=:\n" + "\n".join(found[:40])


def test_the_scan_catches_what_it_should(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "open('a.txt')\n"
        "open('a.bin', 'rb')\n"
        "open('a.txt', 'w', encoding='utf-8')\n"
        "p.read_text()\n"
        "p.write_text('x', encoding='utf-8')\n"
        "p.open('w', newline='')\n"
        "webbrowser.open(url)\n", encoding="utf-8")
    hits = [h.split(" ")[1] for h in unstated(sample, root=tmp_path)]
    assert hits == ["open", "read_text", "open"]
