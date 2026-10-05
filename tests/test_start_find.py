"""`judgekeeper start`, finding: which eval tool a project uses, where its saved results are,
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
from datetime import datetime

import pytest

from judgekeeper import find, textio
from judgekeeper.cli import main
from tests.start_projects import (
    deepeval_project,
    inspect_project,
    promptfoo_data,
    promptfoo_project,
    split,
    table_project,
)


def run(capsys, *argv):
    code = main(["start", *map(str, argv)])
    out, err = capsys.readouterr()
    return code, out, err


def ok() -> str:
    return textio.tick()


def local(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone().strftime(
        "%Y-%m-%d %H:%M")


# Each tool -------------------------------------------------------------------------------

def test_promptfoo_names_the_tool_the_judge_and_the_counts(tmp_path, capsys):
    promptfoo_project(tmp_path, split(25, 15))
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert f"Looking in {tmp_path.resolve()} ..." in out
    assert (f"{ok()} Your eval tool: promptfoo (results.json, saved "
            f"{local('2026-10-03T14:12:00Z')})") in out
    assert f'{ok()} Your judge: llm-rubric "Is polite and correct." with openai:gpt-4.1-mini' in out
    assert f"{ok()} 40 answers with a verdict: the judge passed 25 and failed 15" in out


def test_enough_answers_print_the_labeling_plan_and_write_nothing(tmp_path, capsys):
    promptfoo_project(tmp_path, split(25, 15))
    before = sorted(p.name for p in tmp_path.iterdir())
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "You will label answers in your browser, one at a time: Correct or Wrong." in out
    assert "  A rough check needs 15 Correct and 15 Wrong." in out
    assert "  A reliable result needs 25 Correct and 25 Wrong." in out
    assert "  Most people need 10 to 20 minutes." in out
    assert sorted(p.name for p in tmp_path.iterdir()) == before  # no .judgekeeper/ yet


def test_deepeval_latest_run(tmp_path, capsys):
    deepeval_project(tmp_path, split(20, 12))
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert f"{ok()} Your eval tool: DeepEval (.deepeval/.latest_run_full.json, saved " in out
    assert (f'{ok()} Your judge: Correctness [GEval] "Is the actual output factually correct '
            'given the input?" with gpt-4.1') in out
    assert f"{ok()} 32 answers with a verdict: the judge passed 20 and failed 12" in out


def test_deepeval_results_folder_from_its_variable(tmp_path, capsys, monkeypatch):
    deepeval_project(tmp_path, split(20, 12), name="evals/runs/test_run_20261002_090000.json")
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["deepeval"]\n')
    monkeypatch.setenv("DEEPEVAL_RESULTS_FOLDER", str(tmp_path / "evals" / "runs"))
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "DeepEval (evals/runs/test_run_20261002_090000.json, saved 2026-10-02 09:00)" in out


def test_a_results_variable_outside_the_folder_is_not_read(tmp_path, capsys, monkeypatch):
    project, elsewhere = tmp_path / "project", tmp_path / "elsewhere"
    deepeval_project(elsewhere, split(20, 12), name="test_run_20261002_090000.json")
    table_project(project, split(20, 12))
    monkeypatch.setenv("DEEPEVAL_RESULTS_FOLDER", str(elsewhere))
    code, out, _ = run(capsys, project)
    assert code == 0
    assert "DeepEval" not in out.replace("DEEPEVAL_RESULTS_FOLDER", "")
    assert "Your eval tool: a plain table (results.csv" in out
    assert "DEEPEVAL_RESULTS_FOLDER points outside this folder, so it was not read." in out


def test_inspect_json_log(tmp_path, capsys):
    inspect_project(tmp_path, split(18, 14))
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert (f"{ok()} Your eval tool: Inspect AI (logs/2026-10-02_support.json, saved "
            f"{local('2026-09-30T10:00:00+00:00')})") in out
    assert (f'{ok()} Your judge: model_graded_qa "Grade the answer as C (correct) or I '
            '(incorrect)." with anthropic/claude-haiku-4-5') in out
    assert f"{ok()} 32 answers with a verdict: the judge passed 18 and failed 14" in out


def test_inspect_eval_logs_without_the_extra_say_how_to_read_them(tmp_path, capsys,
                                                                    monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "inspect_ai", None)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "2026-10-02_support.eval").write_bytes(b"PK\x03\x04 not read")
    code, out, _ = run(capsys, tmp_path)
    assert code == 2
    assert ('Inspect AI found (logs/). To read it: pip install "judgekeeper[inspect]", then run '
            "judgekeeper start again.") in out


def test_a_plain_table(tmp_path, capsys):
    table_project(tmp_path, split(16, 16), name="data/results.csv")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert f"{ok()} Your eval tool: a plain table (data/results.csv, saved " in out
    assert f"{ok()} Your judge: not named in results.csv" in out
    assert f"{ok()} 32 answers with a verdict: the judge passed 16 and failed 16" in out


def test_a_plain_table_with_a_model_column_and_another_verdict_name(tmp_path, capsys):
    table_project(tmp_path, split(16, 16), model="gpt-4.1-mini", verdict_column="judge_verdict",
                  name="scores.csv")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert f"{ok()} Your judge: judge_verdict in scores.csv with gpt-4.1-mini" in out


def test_a_table_deeper_than_two_folders_is_not_a_table(tmp_path, capsys):
    table_project(tmp_path, split(16, 16), name="a/b/results.csv")
    code, out, _ = run(capsys, tmp_path)
    assert code == 2
    assert "No saved eval results found" in out


def test_mlflow_store(tmp_path, capsys):
    from tests.conftest import build_mlflow_store

    build_mlflow_store(tmp_path)
    code, out, _ = run(capsys, tmp_path, "--metric", "correctness")
    assert f"{ok()} Your eval tool: MLflow (mlflow.db, experiment qa-judge)" in out
    assert f"{ok()} Your judge: correctness with fake:/judge-model-1" in out
    assert f"{ok()} 8 answers with a verdict: the judge passed 4 and failed 4" in out
    assert "Run your MLflow evaluation again on more data." in out
    assert code == 2  # too few, and no terminal to ask in


def test_mlflow_without_the_extra_says_how_to_read_it(tmp_path, capsys, monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "mlflow", None)
    (tmp_path / "mlruns").mkdir()
    code, out, _ = run(capsys, tmp_path)
    assert code == 2
    assert ('MLflow found (mlruns/). To read it: pip install "judgekeeper[mlflow]", then run '
            "judgekeeper start again.") in out


def test_a_results_file_as_the_path_skips_the_search(tmp_path, capsys):
    path = promptfoo_project(tmp_path / "out", split(20, 12), name="run.json", config=False)
    promptfoo_project(tmp_path / "other", split(1, 1))  # would be found by a search
    code, out, _ = run(capsys, path)
    assert code == 0
    assert "Looking in" not in out
    assert "Your eval tool: promptfoo (run.json, saved" in out
    assert "32 answers with a verdict" in out


def test_a_file_that_is_not_results_is_a_usage_error(tmp_path, capsys):
    path = tmp_path / "notes.json"
    path.write_text('{"hello": 1}')
    code, _, err = run(capsys, path)
    assert code == 2
    assert "notes.json is not a results file judgekeeper start can read" in err


def test_nothing_found_says_what_is_read(tmp_path, capsys):
    (tmp_path / "README.md").write_text("hello")
    code, out, _ = run(capsys, tmp_path)
    assert code == 2
    assert f"No saved eval results found in {tmp_path.resolve()}." in out
    assert "judgekeeper start path/to/results.json" in out


# What is searched, and what is not -------------------------------------------------------

@pytest.mark.parametrize("folder", [".git", "node_modules", ".venv", "venv", "site-packages",
                                    "dist-packages", "__pycache__", ".judgekeeper", ".cache"])
def test_skipped_folders_are_skipped(tmp_path, capsys, folder):
    promptfoo_project(tmp_path / folder, split(20, 12), config=False)
    code, out, _ = run(capsys, tmp_path)
    assert code == 2
    assert "No saved eval results found" in out


def test_files_deeper_than_four_folders_are_not_found(tmp_path, capsys):
    promptfoo_project(tmp_path / "a" / "b" / "c" / "d" / "e", split(20, 12), config=False)
    code, out, _ = run(capsys, tmp_path)
    assert code == 2 and "No saved eval results found" in out
    promptfoo_project(tmp_path / "a" / "b" / "c" / "d", split(20, 12), config=False)
    code, out, _ = run(capsys, tmp_path)
    assert code == 0 and "a/b/c/d/results.json" in out


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symbolic links")
def test_symbolic_links_are_not_followed(tmp_path, capsys):
    outside = tmp_path / "outside"
    promptfoo_project(outside, split(20, 12), config=False)
    project = tmp_path / "project"
    project.mkdir()
    try:
        (project / "linked").symlink_to(outside, target_is_directory=True)
        (project / "results.json").symlink_to(outside / "results.json")
    except OSError:
        pytest.skip("symbolic links not allowed here")
    code, out, _ = run(capsys, project)
    assert code == 2
    assert "No saved eval results found" in out


def test_the_search_stops_after_the_file_limit(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(find, "MAX_FILES", 20)
    for i in range(30):
        (tmp_path / f"note-{i:02d}.txt").write_text("x")
    code, out, _ = run(capsys, tmp_path)
    assert code == 2
    assert ("Stopped looking after 20 files. Point me at the results: judgekeeper start "
            "path/to/results.json") in out


def test_the_file_limit_is_five_thousand_and_the_time_limit_two_seconds():
    assert find.MAX_FILES == 5000 and find.MAX_SECONDS == 2


def test_the_search_stops_after_the_time_limit(tmp_path, capsys, monkeypatch):
    ticks = iter(range(0, 1000, 3))
    monkeypatch.setattr(find, "_clock", lambda: next(ticks))
    for i in range(5):
        (tmp_path / f"note-{i}.txt").write_text("x")
    code, out, _ = run(capsys, tmp_path)
    assert code == 2
    assert "Stopped looking after 2 seconds. Point me at the results" in out


def test_known_places_are_looked_at_before_the_limit(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(find, "MAX_FILES", 5)
    for i in range(30):
        (tmp_path / "aaa" / f"note-{i:02d}.txt").parent.mkdir(exist_ok=True)
        (tmp_path / "aaa" / f"note-{i:02d}.txt").write_text("x")
    deepeval_project(tmp_path, split(20, 12))
    code, out, _ = run(capsys, tmp_path)
    assert "Your eval tool: DeepEval (.deepeval/.latest_run_full.json" in out
    assert "Stopped looking after 5 files." in out
    assert code == 0


def test_results_over_the_size_limit_are_listed_not_read(tmp_path, capsys, monkeypatch):
    path = promptfoo_project(tmp_path, split(20, 12))
    monkeypatch.setattr(find, "MAX_BYTES", path.stat().st_size - 1)
    code, out, _ = run(capsys, tmp_path)
    assert code == 2
    mb = path.stat().st_size / 1_000_000
    assert (f"results.json is {mb:,.0f} MB. Run judgekeeper start results.json to read it "
            "anyway.") in out
    assert "answers with a verdict" not in out
    code, out, _ = run(capsys, path)  # named on the command line: read
    assert code == 0 and "32 answers with a verdict" in out


def test_at_most_200_json_files_are_looked_into(tmp_path, monkeypatch):
    for i in range(find.MAX_JSON + 20):
        (tmp_path / f"config-{i:03d}.json").write_text('{"not": "results"}')
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
    big.write_text('{"items": [' + ",".join(['"x"'] * 100_000) + "]}")
    assert len(find._head(big)) == find.HEAD_BYTES == 64 * 1024


def test_a_dotenv_file_is_never_opened(tmp_path, capsys, monkeypatch):
    key = "sk-test-" + "k" * 40
    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={key}\n")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".env").write_text(f"OPENAI_API_KEY={key}\n")
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


def test_nothing_is_written_while_searching(tmp_path, capsys):
    promptfoo_project(tmp_path, split(3, 3))
    snapshot = sorted(str(p) for p in tmp_path.rglob("*"))
    run(capsys, tmp_path)
    assert sorted(str(p) for p in tmp_path.rglob("*")) == snapshot


# promptfoo -------------------------------------------------------------------------------

def test_a_promptfoo_config_without_results_prints_the_export_commands(tmp_path, capsys):
    (tmp_path / "promptfooconfig.yaml").write_text("description: support bot\n")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert f"{ok()} Your eval tool: promptfoo (promptfooconfig.yaml)" in out
    assert "  No promptfoo results file in this folder. promptfoo keeps them in its own" in out
    assert "    promptfoo list evals -n 10" in out
    assert "    promptfoo export eval <eval id from that list> -o promptfoo-results.json" in out
    assert "  If your last promptfoo run was in this folder, this is the same:" in out
    assert "    promptfoo export eval latest -o promptfoo-results.json" in out
    assert "Update promptfoo if this command is not found." in out
    assert "  Then run judgekeeper start again." in out
    assert "promptfoo eval" not in out  # that runs the eval again, and costs money


@pytest.mark.parametrize("config", ["promptfooconfig.yml", "promptfooconfig.json"])
def test_every_promptfoo_config_name_is_a_sign(tmp_path, capsys, config):
    (tmp_path / config).write_text("{}")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0 and f"Your eval tool: promptfoo ({config})" in out


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
    "grading": ("The judge's verdicts are missing from {f}. promptfoo leaves them out when "
                "PROMPTFOO_STRIP_GRADING_RESULT is on, in your environment or in the config's "
                "env: block. Turn it off and write the file again."),
}


@pytest.mark.parametrize("part", list(STRIPPED))
def test_stripped_promptfoo_results_say_which_setting_removed_what(tmp_path, capsys, part):
    from tests.start_projects import PROMPTFOO

    data = _strip(json.loads(PROMPTFOO.read_text(encoding="utf-8")), part)
    path = tmp_path / "promptfoo-results.json"
    path.write_text(json.dumps(data))
    code, out, err = run(capsys, tmp_path)
    assert code == 2
    assert STRIPPED[part].format(f="promptfoo-results.json") in out + err
    assert "answers with a verdict" not in out


@pytest.mark.parametrize("part", list(STRIPPED))
def test_import_promptfoo_gives_the_same_warning(tmp_path, capsys, part):
    from tests.start_projects import PROMPTFOO

    data = _strip(json.loads(PROMPTFOO.read_text(encoding="utf-8")), part)
    path = tmp_path / "promptfoo-results.json"
    path.write_text(json.dumps(data))
    main(["import", "promptfoo", str(path), "--metric", "helpfulness",
          "--out", str(tmp_path / "rep")])
    out, err = capsys.readouterr()
    assert STRIPPED[part].format(f="promptfoo-results.json") in out + err


def test_a_few_rows_without_an_answer_are_not_stripped_results(tmp_path, capsys):
    outputs = [f"Answer {i}." for i in range(32)]
    outputs[3] = None
    promptfoo_project(tmp_path, split(20, 12), outputs=outputs)
    code, out, _ = run(capsys, tmp_path)
    assert code == 0 and "missing" not in out


def test_the_run_date_is_when_the_eval_ran_else_the_file_time(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 12), created=None)
    path = tmp_path / "results.json"
    stamp = datetime(2026, 9, 1, 8, 30).astimezone().timestamp()
    os.utime(path, (stamp, stamp))
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert "(results.json, saved 2026-09-01 08:30)" in out


def test_the_newest_promptfoo_file_is_the_one_whose_eval_ran_last(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 12), name="a.json", created="2026-10-05T10:00:00Z")
    promptfoo_project(tmp_path, split(30, 10), name="b.json", created="2026-10-01T10:00:00Z")
    os.utime(tmp_path / "b.json")  # touched last, but its eval is older
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert f"(a.json, saved {local('2026-10-05T10:00:00Z')})" in out
    assert "32 answers with a verdict" in out


def test_results_from_another_project_ask_first(tmp_path, capsys, monkeypatch):
    promptfoo_project(tmp_path, split(20, 12), description="billing bot")
    from judgekeeper import start

    monkeypatch.setattr(start, "_interactive", lambda: True)
    answers = iter(["n"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": print(prompt) or next(answers))
    code, out, _ = run(capsys, tmp_path)
    assert code == 0
    assert ('results.json looks like it is from another project (its description is "billing '
            'bot"). Continue? [y/N]') in out
    assert "answers with a verdict" not in out

    answers = iter(["y"])
    code, out, _ = run(capsys, tmp_path)
    assert code == 0 and "32 answers with a verdict" in out


def test_another_project_without_a_terminal_stops(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 12), description="billing bot")
    code, out, _ = run(capsys, tmp_path)
    assert code == 2
    assert "looks like it is from another project" in out


def test_the_same_description_does_not_ask(tmp_path, capsys):
    promptfoo_project(tmp_path, split(20, 12), description="support bot")
    code, out, _ = run(capsys, tmp_path)
    assert code == 0 and "another project" not in out


def test_the_fixture_reads_as_promptfoo_data():
    data = promptfoo_data(split(1, 1))
    assert len(data["results"]["results"]) == 2
