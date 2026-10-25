"""`judgekeeper`, finding: which eval tool a project uses, where its saved results are,
and which judge made them. Standard library only; nothing here runs a tool or calls an API.

Each test builds a small project in a temporary folder (tests/start_projects.py). Without a
terminal `start` never asks; a project with enough answers prints what it found, the
labeling plan, and stops (the labeling page comes after).
"""

from __future__ import annotations

import builtins
import io
import json
import os

import pytest

from judgekeeper import find, start
from judgekeeper.cli import main
from tests.start_projects import (
    promptfoo_data,
    promptfoo_project,
    split,
    table_project,
)


def run(capsys, *argv, yes=True):
    """`judgekeeper` without a terminal; with --yes unless `yes` is False, so the run goes
    on to the marking page where a person would say yes."""
    argv = [*map(str, argv)] + (["--yes"] if yes and "--yes" not in argv else [])
    code = main([*argv])
    out, err = capsys.readouterr()
    return code, out, err


# Each tool -------------------------------------------------------------------------------


def test_other_tools_do_not_list_rows(tmp_path, capsys):
    promptfoo_project(tmp_path, split(16, 16))
    _, out, _ = run(capsys, tmp_path)
    assert "The first 3 rows" not in out


# What is searched, and what is not -------------------------------------------------------


def test_the_file_limit_is_five_thousand_and_the_time_limit_two_seconds():
    assert find.MAX_FILES == 5000 and find.MAX_SECONDS == 2


def test_at_most_200_json_files_are_looked_into(tmp_path, monkeypatch):
    for i in range(find.MAX_JSON + 20):
        (tmp_path / f"config-{i:03d}.json").write_text('{"not": "results"}', encoding="utf-8")
    opened = []
    real = find._head

    def head(path):
        opened.append(path)
        return real(path)

    monkeypatch.setattr(find, "_head", head)
    find.search(tmp_path)
    assert len(opened) == find.MAX_JSON == 200


def test_only_the_head_of_a_json_file_is_read_to_sniff_it(tmp_path):
    big = tmp_path / "big.json"
    big.write_text('{"items": [' + ",".join(['"x"'] * 100_000) + "]}", encoding="utf-8")
    assert len(find._head(big)) == find.HEAD_BYTES == 64 * 1024


def test_a_dotenv_file_is_never_opened(tmp_path, capsys, monkeypatch):
    key = "sk-test-" + "k" * 40
    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={key}\n", encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".env").write_text(f"OPENAI_API_KEY={key}\n", encoding="utf-8")
    promptfoo_project(tmp_path, split(20, 12))
    opened = []
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open

    def spy(opener):
        def wrapped(file, *a, **k):
            opened.append(os.fspath(file) if not isinstance(file, int) else "")
            return opener(file, *a, **k)
        return wrapped

    monkeypatch.setattr(builtins, "open", spy(real_open))
    monkeypatch.setattr(io, "open", spy(real_io_open))
    monkeypatch.setattr(os, "open", spy(real_os_open))
    code, out, err = run(capsys, tmp_path)
    assert code == 0
    assert opened, "the spy saw no file at all"
    assert not [p for p in opened if os.path.basename(p) == ".env"]
    assert key not in out + err


def test_what_is_printed_holds_no_answer_text(tmp_path, capsys):
    tag = " zebra-7741"
    promptfoo_project(tmp_path, split(20, 12), tag=tag)
    code, out, err = run(capsys, tmp_path)
    assert code == 0
    assert "zebra-7741" not in out + err


# promptfoo -------------------------------------------------------------------------------


def _strip(data: dict, part: str) -> dict:
    """What promptfoo's PROMPTFOO_STRIP_* settings remove from every row."""
    for row in data["results"]["results"]:
        if part == "output":
            row["response"].pop("output", None)
        elif part == "vars":
            row.pop("vars", None)
            row["testCase"].pop("vars", None)
        else:
            row.pop("gradingResult", None)
    return data


STRIPPED = {
    "output": ("The answers are missing from {f}. promptfoo leaves them out when "
               "PROMPTFOO_STRIP_RESPONSE_OUTPUT is on, in your environment or in the config's "
               "env: block. Turn it off and write the file again."),
    "vars": ("The inputs are missing from {f}. promptfoo leaves them out when "
             "PROMPTFOO_STRIP_TEST_VARS is on, in your environment or in the config's env: "
             "block. Turn it off and write the file again."),
    "grading": ("The LLM-as-a-judge's decisions are missing from {f}. promptfoo leaves them out when "
                "PROMPTFOO_STRIP_GRADING_RESULT is on, in your environment or in the config's "
                "env: block. Turn it off and write the file again."),
}


@pytest.mark.parametrize("part", list(STRIPPED))
def test_stripped_promptfoo_results_say_which_setting_removed_what(tmp_path, capsys, part):
    from tests.start_projects import PROMPTFOO

    data = _strip(json.loads(PROMPTFOO.read_text(encoding="utf-8")), part)
    path = tmp_path / "promptfoo-results.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    code, out, err = run(capsys, tmp_path)
    assert code == 2
    assert STRIPPED[part].format(f="promptfoo-results.json") in out + err
    assert "Its decisions" not in out


def test_a_few_rows_without_an_answer_are_not_stripped_results(tmp_path, capsys):
    outputs = [f"Answer {i}." for i in range(32)]
    outputs[3] = None
    promptfoo_project(tmp_path, split(20, 12), outputs=outputs)
    code, out, _ = run(capsys, tmp_path)
    assert code == 0 and "missing" not in out


def test_another_project_without_a_terminal_stops(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 12), description="billing bot")
    code, out, _ = run(capsys, tmp_path, yes=False)
    assert code == start.EXIT_QUESTION
    assert "looks like it is from another project" in out


def test_the_fixture_reads_as_promptfoo_data():
    data = promptfoo_data(split(1, 1))
    assert len(data["results"]["results"]) == 2


def test_a_records_file_outside_the_records_folder_is_found(tmp_path):
    line = {"schema_version": 2, "name": "Helpful", "annotator_kind": "LLM", "label": "pass",
            "input": "q", "output": "a"}
    (tmp_path / "judge-results.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")
    found = find.search(tmp_path)
    assert [r.path.name for r in found.results.get("records", [])] == ["judge-results.jsonl"]
    assert "table" not in found.results


def test_an_mlruns_folder_of_artifacts_only_is_not_a_store(tmp_path):
    # With mlflow.db, MLflow keeps logged artifacts in ./mlruns/<experiment>/<run>/artifacts
    (tmp_path / "mlruns" / "1" / "a1b2" / "artifacts").mkdir(parents=True)
    (tmp_path / "mlruns" / "1" / "a1b2" / "artifacts" / "notes.txt").write_text(
        "x", encoding="utf-8")
    (tmp_path / "mlruns" / ".trash").mkdir()  # made by reading it as a store once
    assert not find.is_mlflow_folder(tmp_path / "mlruns")
    assert not find.search(tmp_path).readable("mlflow")
    (tmp_path / "mlruns" / "1" / "meta.yaml").write_text("name: qa\n", encoding="utf-8")
    assert find.is_mlflow_folder(tmp_path / "mlruns")


@pytest.mark.parametrize("folder", ["judgekeeper-report", "judgekeeper-demo-2026-10-01",
                                    "judgekeeper-demo"])
def test_judgekeepers_own_folders_are_never_your_judge(tmp_path, capsys, folder):
    # the check command's report (anchors.jsonl looks like a table) and 0.1.3's demo data
    table_project(tmp_path / folder, split(16, 16), name="anchors.csv")
    (tmp_path / folder / "own.jsonl").write_text(
        json.dumps({"input": "q", "output": "a", "score": 1}) + "\n", encoding="utf-8")
    found = find.search(tmp_path)
    assert not found.readable("table"), folder
    from judgekeeper import own_format

    assert own_format.search(tmp_path) is None
    table_project(tmp_path, split(16, 16), name="results.csv")  # the person's own, still found
    assert [r.rel for r in find.search(tmp_path).readable("table")] == ["results.csv"]


def test_the_same_description_does_not_ask(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 12), description="support bot")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0 and "looks like it is from another project" not in out
