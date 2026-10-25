"""Every place a person reads the word for what judgekeeper checks, it says "LLM-as-a-judge",
never "judge" alone: the strings in the code (terminal lines, the marking page, the result page,
the report), the records schema, the README, the reference, the security and trademark
notes, the GitHub templates and the website.

Not checked, on purpose: code names (keys, columns, flags, the `judge=` argument of record()),
docstrings and comments, the verb ("how to judge them"), and the reports in docs/examples/,
which quote the output of the commit they name.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from tests.website_pages import WEBSITE, pages, parse

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "judgekeeper"
BARE = re.compile(r"(?<![-_{.\w/#])judges?(?:'s)?\b(?![_\-.=]\w|=)", re.IGNORECASE)
VERB = re.compile(r"\b(?:to|not|actually) $", re.IGNORECASE)
# Strings that are code, not words: a dict key, a reason's key, a value written to result.json
CODE = frozenset({"judge call failed", "jeffreys, with the judge's wobble"})
SCHEMA_DEFAULT = "Default: judge."  # `name`'s default value, as record() writes it


def bare(text: str) -> list[str]:
    """Each bare "judge" in `text`, with the words around it."""
    return [text[max(0, m.start() - 30):m.end() + 30] for m in BARE.finditer(text)
            if not VERB.search(text[:m.start()]) and not m.group().isupper()]  # JUDGE: a value


def _docstrings(tree: ast.AST) -> set[int]:
    kinds = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    return {id(node.body[0].value) for node in ast.walk(tree)
            if isinstance(node, kinds) and node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)}


def code_strings() -> list[tuple[str, str]]:
    """(where, text) for every string in the code that is not a docstring or a code name."""
    out = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = _docstrings(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in skip and node.value not in CODE
                    and not re.fullmatch(r"\w+", node.value)):
                out.append((f"{path.relative_to(ROOT)}:{node.lineno}", node.value))
    return out


def test_the_code_says_llm_as_a_judge():
    found = [(where, hit) for where, text in code_strings() for hit in bare(text)]
    assert not found, found


def test_the_check_finds_a_bare_judge_and_leaves_the_rest():
    assert bare("Your judge passed it.") and bare("The judge's rule") and bare("Judge: gpt")
    assert bare("Two judges agree.")
    for fine in ("Your LLM-as-a-judge passed it.", "--judge-model NAME", "judge_verdict",
                 "judge-check.csv", ".judgekeeper/judge.json", "pass judge= to record()",
                 "write how to judge them", "{judge}", "judgekeeper", "judgment",
                 "LLM_JUDGE, JUDGE"):
        assert not bare(fine), fine


def test_the_schema_says_llm_as_a_judge():
    path = SRC / "schemas" / "records.schema.json"
    said = []

    def walk(value):
        if isinstance(value, dict):
            said.extend(v for k, v in value.items() if k in ("title", "description"))
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(json.loads(path.read_text(encoding="utf-8")))
    found = [hit for text in said for hit in bare(text.replace(SCHEMA_DEFAULT, ""))]
    assert not found, found


def prose(path: Path) -> str:
    """A Markdown file without its code: no fenced blocks, no `code`, no link targets."""
    text = re.sub(r"^```.*?^```", "", path.read_text(encoding="utf-8"), flags=re.DOTALL | re.MULTILINE)
    return re.sub(r"`[^`\n]*`|\]\([^)]*\)", "", text)


@pytest.mark.parametrize("name", ["README.md", "docs/reference.md", "docs/eval-tools.md", "SECURITY.md",
                                  "TRADEMARKS.md", ".github/CONTRIBUTING.md",
                                  ".github/PULL_REQUEST_TEMPLATE.md"])
def test_the_docs_say_llm_as_a_judge(name):
    found = bare(prose(ROOT / name))
    assert not found, found


@pytest.mark.parametrize("path", sorted((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml")),
                         ids=lambda p: p.name)
def test_the_issue_forms_say_llm_as_a_judge(path):
    found = bare(prose(path))
    assert not found, found


def _page_text(page: Path) -> str:
    parts = []
    for el in parse(page).iter():
        parts.extend(c for c in el.children if isinstance(c, str))
        parts.extend(el.attrs[a] or "" for a in ("alt", "aria-label", "title", "content")
                     if a in el.attrs)
    return " ".join(parts)


@pytest.mark.parametrize("page", pages(), ids=lambda p: str(p.relative_to(WEBSITE)))
def test_the_website_says_llm_as_a_judge(page):
    found = bare(_page_text(page))
    assert not found, found


@pytest.mark.parametrize("name", ["assets/freecheck.js", "assets/site.js"])
def test_the_website_scripts_say_llm_as_a_judge(name):
    text = (WEBSITE / name).read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/|^\s*//[^\n]*", "", text, flags=re.DOTALL | re.MULTILINE)  # comments
    strings = re.findall(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"|`(?:[^`\\]|\\.)*`", text)
    found = [hit for s in strings if not re.fullmatch(r"\W\w+\W", s) for hit in bare(s)]
    assert not found, found


def test_llms_txt_says_llm_as_a_judge():
    found = bare((WEBSITE / "llms.txt").read_text(encoding="utf-8"))
    assert not found, found
