"""`judgekeeper init`: a starter rule file, and `judge --prompt` refusing one that is not filled in."""

from __future__ import annotations

import json
import re

import pytest

from judgekeeper.cli import main
from judgekeeper.prompts import FILL_IN, load_prompt, unfilled_marker
from judgekeeper.templates import TEMPLATES, template_text

MARKER = re.compile(r"\[FILL IN: [^\]]+\]")


def _fill(text: str) -> str:
    return MARKER.sub("filled in", text)


def _single_anchors(tmp_path):
    anchors = tmp_path / "anchors.jsonl"
    items = [{"id": f"s{i}", "input": "q", "output": "ok" if i % 2 else "",
              "human_label": "pass" if i % 2 else "fail"} for i in range(6)]
    anchors.write_text("\n".join(json.dumps(i) for i in items) + "\n")
    assert main(["freeze", str(anchors)]) == 0
    return anchors


# The templates

@pytest.mark.parametrize("name", ["single.md", "pairwise.md"])
def test_templates_ship_with_the_package_and_load(name):
    path = TEMPLATES / name
    assert path.is_file()
    prompt = load_prompt(path)
    assert prompt.rubric_version == "my-metric-v1"
    assert "{{input}}" in prompt.template


def test_single_template_marks_every_part_the_user_writes():
    text = template_text(pairwise=False)
    markers = MARKER.findall(text)
    assert len(markers) >= 5
    joined = " ".join(markers).lower()
    for part in ("one thing", "pass", "fail", "example", "edge case"):
        assert part in joined, part
    assert "{{input}}" in text and "{{output}}" in text
    assert "{{output_a}}" not in text
    assert text.rstrip().endswith("`Verdict: pass` or `Verdict: fail`.")


def test_pairwise_template_marks_better_and_tie():
    text = template_text(pairwise=True)
    joined = " ".join(MARKER.findall(text)).lower()
    for part in ("one thing", "better", "tie"):
        assert part in joined, part
    for placeholder in ("{{input}}", "{{output_a}}", "{{output_b}}"):
        assert placeholder in text
    assert text.rstrip().endswith("`Verdict: A` or `Verdict: B`.")


def test_filled_templates_still_load():
    for pairwise in (False, True):
        text = _fill(template_text(pairwise))
        assert FILL_IN not in text
        assert unfilled_marker(text) is None


# init

def test_init_writes_the_single_template(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    out = tmp_path / "prompts" / "judge.md"
    assert out.is_file()
    assert out.read_text(encoding="utf-8") == template_text(pairwise=False)
    assert load_prompt(out).rubric_version == "my-metric-v1"
    printed = capsys.readouterr().out
    assert "prompts/judge.md" in printed
    for command in ("judgekeeper label ", "judgekeeper template ",
                    "judgekeeper judge anchors.jsonl", "--prompt prompts/judge.md",
                    "judgekeeper validate anchors.jsonl"):
        assert command in printed, command


def test_init_pairwise_and_out_create_the_folder(tmp_path):
    out = tmp_path / "evals" / "deep" / "rule.md"
    assert main(["init", "--pairwise", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == template_text(pairwise=True)
    assert load_prompt(out).rubric_version == "my-metric-v1"


def test_init_refuses_to_overwrite_without_force(tmp_path, capsys):
    out = tmp_path / "judge.md"
    out.write_text("mine\n")
    assert main(["init", "--out", str(out)]) == 2
    assert out.read_text() == "mine\n"
    assert "--force" in capsys.readouterr().err
    assert main(["init", "--out", str(out), "--force"]) == 0
    assert out.read_text(encoding="utf-8") == template_text(pairwise=False)


def test_init_needs_no_network_and_writes_nothing_else(tmp_path, monkeypatch):
    import socket

    def refuse(*args, **kwargs):
        raise OSError("network disabled in this test")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--out", "rule.md"]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rule.md"]


# judge --prompt on an unfilled file

def test_unfilled_marker_names_the_first_marker_and_its_line():
    text = "---\nrubric_version: x\n---\nok\n[FILL IN: the one thing]\n[FILL IN: pass]\n"
    assert unfilled_marker(text) == (5, "[FILL IN: the one thing]")
    assert unfilled_marker("no markers {{input}}") is None


def test_judge_refuses_an_unfilled_prompt(tmp_path, monkeypatch, capsys):
    anchors = _single_anchors(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--out", "rule.md"]) == 0
    line, marker = unfilled_marker((tmp_path / "rule.md").read_text(encoding="utf-8"))
    runs = tmp_path / "runs"
    code = main(["judge", str(anchors), "--callable", "tests.judges_for_tests:keyword_judge",
                 "--prompt", "rule.md", "--out", str(runs)])
    assert code == 2
    err = capsys.readouterr().err
    assert marker in err and f"line {line}" in err and "rule.md" in err
    assert not runs.exists()
    # the same for a built-in runner, before any key is looked at
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = main(["judge", str(anchors), "--runner", "anthropic", "--model", "m",
                 "--prompt", "rule.md", "--out", str(runs)])
    assert code == 2
    assert marker in capsys.readouterr().err


def test_judge_accepts_a_filled_prompt(tmp_path, monkeypatch):
    anchors = _single_anchors(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--out", "rule.md"]) == 0
    rule = tmp_path / "rule.md"
    rule.write_text(_fill(rule.read_text(encoding="utf-8")), encoding="utf-8")
    runs = tmp_path / "runs"
    assert main(["judge", str(anchors), "--callable", "tests.judges_for_tests:keyword_judge",
                 "--prompt", "rule.md", "--out", str(runs)]) == 0
    header = json.loads((runs / "run-01.jsonl").read_text().splitlines()[0])
    assert header["fingerprint"]["rubric_version"] == "my-metric-v1"
    assert header["fingerprint"]["prompt_hash"] == load_prompt(rule).prompt_hash
