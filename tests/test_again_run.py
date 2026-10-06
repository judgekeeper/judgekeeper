"""Asking your judge again, for real: promptfoo re-grades the labeled answers, or the user's
own judge command runs on them; then the numbers and the saved files.

No test calls a paid API and none needs Node or promptfoo: the one process function is
replaced by a fake promptfoo that reads the two files judgekeeper writes and answers as
promptfoo's `eval -o` would. One optional test runs the real promptfoo, when it is installed,
with a local fake grader.
"""

from __future__ import annotations

import builtins
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from judgekeeper import again, keys, start, start_label
from judgekeeper.again import AgainOptions, make_plan
from judgekeeper.again import promptfoo as pf
from judgekeeper.cli import main
from judgekeeper.judgments import read_run
from judgekeeper.start_label import StartSession, save_result
from tests.conftest import FIXTURES
from tests.start_projects import promptfoo_project, split, table_project

CONFIG = ".judgekeeper-regrade.promptfoo.json"
TESTS = ".judgekeeper-regrade.tests.json"
SECRET = "sk-proj-THISisAfakeKEYthatMUSTbeSCRUBBED0123456789"


def _quiet(line=""):
    pass


def _checked(root, n_pass=20, n_fail=16, maker=promptfoo_project, **kwargs):
    maker(root, split(n_pass, n_fail), **kwargs)
    ws = start_label.prepare(start.find_judge(root), say=_quiet)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"]})
    save_result(ws, session, say=_quiet)
    return ws


def _edit(root, change):
    path = root / "results.json"
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def _version(data):
    data.setdefault("metadata", {})["promptfooVersion"] = "0.123.1"


def _rendered(text="the grading prompt"):
    def change(data):
        for row in data["results"]["results"]:
            for c in row["gradingResult"]["componentResults"]:
                c.setdefault("metadata", {})["renderedGradingPrompt"] = (
                    f"{text} for {row['vars']['question']}")
    return change


class FakePromptfoo:
    """promptfoo, as far as judgekeeper sees it: `--version`, and `eval` reading the two files
    judgekeeper wrote and writing the -o file. `flips` maps (answer id, repeat) to the opposite
    of the saved verdict; `prompt_changed` holds ids whose grading prompt comes back
    different; `extra` is put into every reason (a planted secret)."""

    def __init__(self, ws, version="0.123.1"):
        self.ws, self.version = ws, version
        self.calls, self.files_seen = [], {}
        self.flips, self.prompt_changed, self.errors = set(), set(), set()
        self.code, self.stderr, self.extra, self.interrupt = None, "", "", False
        saved = json.loads((ws.root / "results.json").read_text())
        self.saved = {}
        for row in saved["results"]["results"]:
            comp = row["gradingResult"]["componentResults"][0]
            self.saved[row["vars"]["question"]] = (row["success"], (comp.get("metadata") or {})
                                                   .get("renderedGradingPrompt"))

    def __call__(self, argv, cwd, env=None, timeout=None):
        self.calls.append(SimpleNamespace(argv=list(argv), cwd=Path(cwd), env=dict(env or {})))
        if argv[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout=self.version + "\n", stderr="")
        assert "eval" in argv, argv
        cwd = Path(cwd)
        config = json.loads((cwd / argv[argv.index("-c") + 1]).read_text())
        tests = json.loads((cwd / config["tests"].removeprefix("file://")).read_text())
        self.files_seen = {"config": config, "tests": tests}
        if self.interrupt:
            raise KeyboardInterrupt
        if self.code not in (None, 0, 100):
            return SimpleNamespace(returncode=self.code, stdout="", stderr=self.stderr)
        times = int(argv[argv.index("--repeat") + 1])
        rows = []
        for r in range(times):
            for t in tests:
                saved, prompt = self.saved[t["vars"]["question"]]
                verdict = (not saved) if (t["description"], r) in self.flips else saved
                if t["description"] in self.prompt_changed:
                    prompt = "a different grading prompt"
                error = t["description"] in self.errors and r == 0
                comps = [{"assertion": a, "pass": None if error else verdict,
                          "score": None if error else int(verdict),
                          "reason": f"again {r}{self.extra}",
                          "metadata": {"renderedGradingPrompt": prompt} if prompt else {}}
                         for a in t["assert"]]
                rows.append({"testIdx": len(rows), "promptIdx": 0,
                             "description": t["description"],
                             "testCase": {"description": t["description"], "vars": t["vars"],
                                          "options": t.get("options", {})},
                             "vars": t["vars"], "prompt": {"raw": t["vars"]["judgekeeper_prompt"]},
                             "response": {"output": t["providerOutput"]},
                             "gradingResult": {"pass": verdict, "componentResults": comps},
                             "success": verdict})
        out = cwd / argv[argv.index("-o") + 1]
        out.write_text(json.dumps({"results": {"version": 3, "results": rows},
                                   "metadata": {"promptfooVersion": self.version},
                                   "config": config}))
        failed = any(not row["success"] for row in rows)
        return SimpleNamespace(returncode=100 if failed else 0, stdout="", stderr="")


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """A checked promptfoo project (36 labeled answers, version 0.123.1), the project's own
    promptfoo, and a fake behind the one process function."""
    ws = _checked(tmp_path)
    _edit(tmp_path, _version)
    binary = tmp_path / "node_modules" / ".bin" / "promptfoo"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    fp = FakePromptfoo(ws)
    monkeypatch.setattr(again, "run_process", fp)
    monkeypatch.setattr(again, "which", lambda name: None)
    for name in keys.all_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    return fp


@pytest.fixture
def terminal(monkeypatch):
    answers: list[str] = []
    monkeypatch.setattr(start, "_interactive", lambda: True)

    def fake_input(prompt=""):
        print(prompt)
        return answers.pop(0) if answers else ""

    monkeypatch.setattr(builtins, "input", fake_input)
    return answers


def run(capsys, *argv):
    code = main(["start", *map(str, argv)])
    out, err = capsys.readouterr()
    return code, out, err


def _again_dir(ws):
    (folder,) = (ws.dir / "again").iterdir()
    return folder


# The two files and the command ---------------------------------------------------------------

def test_the_two_files_follow_promptfoos_shape(fake, capsys):
    ws = fake.ws
    code, _, _ = run(capsys, ws.root, "--ask-again", "--allow-calls", "72")
    assert code == 0
    config, tests = fake.files_seen["config"], fake.files_seen["tests"]
    assert config == {"description": "judgekeeper re-check (temporary file)",
                      "prompts": ["{{judgekeeper_prompt}}"], "providers": ["echo"],
                      "evaluateOptions": {"cache": False}, "tests": f"file://{TESTS}"}
    assert len(tests) == 36
    raw = {r["id"]: r for r in (json.loads(x) for x in ws.pool.read_text().splitlines())}
    for t in tests:
        assert t["description"] in raw
        assert t["providerOutput"] == raw[t["description"]]["output"]
        assert t["vars"]["question"] == raw[t["description"]]["input"]["question"]
        assert "judgekeeper_prompt" in t["vars"]
        assert t["options"]["provider"] == {"id": "openai:gpt-4.1-mini",
                                            "config": {"temperature": 0}}
        assert t["assert"] == [{"type": "llm-rubric",
                                "value": "Is polite and correct.\nSecond line of the rubric."}]


def test_the_command_has_every_flag_and_setting_and_never_grader(fake, capsys):
    ws = fake.ws
    run(capsys, ws.root, "--ask-again", "--allow-calls", "72")
    (call,) = [c for c in fake.calls if "eval" in c.argv]
    argv = call.argv
    assert argv[:4] == [str(ws.root / "node_modules" / ".bin" / "promptfoo"), "eval", "-c",
                        CONFIG]
    for flag in ("--no-cache", "--no-write", "--no-share", "--no-table", "--no-progress-bar"):
        assert flag in argv, flag
    assert argv[argv.index("--repeat") + 1] == "2"
    assert "--grader" not in argv
    out = argv[argv.index("-o") + 1]
    assert out.startswith(".judgekeeper/again/") and out.endswith("/promptfoo.json")
    assert call.cwd == ws.root
    for name, value in (("PROMPTFOO_CACHE_ENABLED", "false"),
                        ("PROMPTFOO_DISABLE_TELEMETRY", "1"), ("PROMPTFOO_DISABLE_UPDATE", "1"),
                        ("PROMPTFOO_DISABLE_SHARING", "1"), ("PROMPTFOO_DISABLE_DEBUG_LOG", "1"),
                        ("PROMPTFOO_DISABLE_ERROR_LOG", "1")):
        assert call.env[name] == value, name


def test_the_two_files_are_removed_after_success(fake, capsys):
    run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    assert not (fake.ws.root / CONFIG).exists() and not (fake.ws.root / TESTS).exists()


def test_the_two_files_are_removed_after_an_error(fake, capsys):
    fake.code, fake.stderr = 1, f"Error: provider failed with key {SECRET}\n"
    code, out, _ = run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    assert code == 1
    assert "promptfoo did not finish: Error: provider failed with key [REDACTED]" in out
    assert SECRET not in out
    assert not (fake.ws.root / CONFIG).exists() and not (fake.ws.root / TESTS).exists()


def test_the_two_files_are_removed_after_ctrl_c(fake, capsys):
    fake.interrupt = True
    code, out, _ = run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    assert code == 130
    assert "Stopped. Nothing was saved." in out
    assert not (fake.ws.root / CONFIG).exists() and not (fake.ws.root / TESTS).exists()


def test_the_run_says_the_files_before_it_starts(fake, capsys):
    _, out, _ = run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    assert (f"Writing {CONFIG} and {TESTS} next to promptfooconfig.yaml; they are removed "
            "when promptfoo is done.") in out


def test_exit_100_is_finished(fake, capsys):
    fake.flips = {(a["id"], 0) for a in again.labeled_answers(fake.ws)[:3]}
    code, out, _ = run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    assert code == 0 and "promptfoo did not finish" not in out


# Which promptfoo ---------------------------------------------------------------------------

def test_npx_is_asked_about_and_defaults_to_no(fake, capsys, terminal, monkeypatch):
    (fake.ws.root / "node_modules").rename(fake.ws.root / "node_modules-gone")
    monkeypatch.setattr(again, "which", lambda name: "/usr/bin/npx" if name == "npx" else None)
    terminal += ["y", ""]  # yes to spending, then Enter at the download question
    code, out, _ = run(capsys, fake.ws.root, "--ask-again")
    assert code == 0
    assert ("promptfoo 0.123.1 is not installed here. Download it with npx --yes "
            "promptfoo@0.123.1? [y/N]") in out
    assert "Your judge was not called; nothing was spent." in out
    assert not any("eval" in c.argv for c in fake.calls)


def test_npx_runs_after_a_yes(fake, capsys, terminal, monkeypatch):
    (fake.ws.root / "node_modules").rename(fake.ws.root / "node_modules-gone")
    monkeypatch.setattr(again, "which", lambda name: "/usr/bin/npx" if name == "npx" else None)
    terminal += ["y", "y"]
    code, _, _ = run(capsys, fake.ws.root, "--ask-again")
    (call,) = [c for c in fake.calls if "eval" in c.argv]
    assert code == 0 and call.argv[:4] == ["/usr/bin/npx", "--yes", "promptfoo@0.123.1", "eval"]


def test_npx_needs_a_terminal(fake, capsys, monkeypatch):
    (fake.ws.root / "node_modules").rename(fake.ws.root / "node_modules-gone")
    monkeypatch.setattr(again, "which", lambda name: "/usr/bin/npx" if name == "npx" else None)
    code, out, _ = run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    assert code == 2
    assert "npm install --save-dev promptfoo@0.123.1" in out


# The spending question ---------------------------------------------------------------------

def test_no_spends_nothing(fake, capsys, terminal):
    code, out, _ = run(capsys, fake.ws.root, "--ask-again")
    assert code == 0
    assert "Go ahead? [y/N]" in out
    assert out.rstrip().endswith("Your judge was not called; nothing was spent.")
    assert not any("eval" in c.argv for c in fake.calls)
    assert not (fake.ws.dir / "again").exists()


def test_yes_at_the_terminal_runs(fake, capsys, terminal):
    terminal += ["y"]
    code, out, _ = run(capsys, fake.ws.root, "--ask-again")
    assert code == 0 and "Asked twice more" in out


def test_without_a_terminal_allow_calls_is_needed(fake, capsys):
    code, out, _ = run(capsys, fake.ws.root, "--ask-again", "--yes")
    assert code == 2
    assert "To go ahead without a terminal: judgekeeper start --ask-again --allow-calls 72" in out
    assert not any("eval" in c.argv for c in fake.calls)


def test_allow_calls_below_the_count_refuses(fake, capsys):
    code, out, _ = run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "50")
    assert code == 2 and ("--allow-calls 50 is below the 72 calls planned. Your judge was not "
                          "called; nothing was spent.") in out


def test_the_menu_choice_asks_too(fake, capsys, terminal):
    terminal += ["1", ""]  # ask again; then Enter at Go ahead? (No)
    code, out, _ = run(capsys, fake.ws.root)
    assert code == 0 and "Go ahead? [y/N]" in out
    assert "Your judge was not called; nothing was spent." in out


# The numbers --------------------------------------------------------------------------------

def test_steadiness_agreement_and_matches(fake, capsys):
    ids = [a["id"] for a in again.labeled_answers(fake.ws)]
    # three answers change their mind in the second repeat; one in the first (and so also
    # differs from its saved verdict)
    fake.flips = {(ids[0], 1), (ids[1], 1), (ids[2], 1), (ids[3], 0)}
    code, out, _ = run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    assert code == 0
    assert "Asked twice more, your judge changed its verdict on 4 of your 36 answers." in out
    assert "Across all your answers that is about" in out
    assert ("Of the answers you marked Correct, your judge passed about 100% before and about "
            in out)
    assert "Its first new verdict matched the saved one on 35 of 36 answers (97%)." in out
    block = json.loads(fake.ws.result_json.read_text())["again"]
    assert block["steadiness"]["changed"] == 4 and block["matches_saved"] == pytest.approx(35 / 36)
    assert block["status"] == "exact" and block["times"] == 2


def test_when_every_answer_agrees_the_ranges_keep_their_width(fake, capsys):
    run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    for block in (json.loads(fake.ws.result_json.read_text())["again"],
                  json.loads((_again_dir(fake.ws) / "again.json").read_text())):
        today = block["today"]
        for key in ("tpr", "tnr"):
            lo, hi = today[f"{key}_interval"]
            assert today[key] == 1.0 and lo < hi == 1.0
        assert today["interval_methods"]["tpr"] == "wilson corners"


def test_below_ninety_percent_asks_if_the_judge_changed(fake, capsys):
    ids = [a["id"] for a in again.labeled_answers(fake.ws)]
    fake.flips = {(i, r) for i in ids[:6] for r in (0, 1)}
    _, out, _ = run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    assert ("Your judge answers differently than when your eval ran. Did its model or prompt "
            "change?") in out


def test_a_changed_grading_prompt_drops_that_answer(fake, capsys, tmp_path):
    _edit(fake.ws.root, _rendered())
    fake.saved = FakePromptfoo(fake.ws).saved
    first = again.labeled_answers(fake.ws)[0]["id"]
    fake.prompt_changed = {first}
    _, out, _ = run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    assert ("1 answer was not counted: its grading prompt differs from the saved one, so it "
            "was not the same judge input.") in out
    block = json.loads(fake.ws.result_json.read_text())["again"]
    assert block["counted"] == 35
    assert block["not_counted"] == [{"id": first, "why": "grading prompt differs"}]


def test_an_error_is_not_counted(fake, capsys):
    first = again.labeled_answers(fake.ws)[0]["id"]
    fake.errors = {first}
    _, out, _ = run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    assert "1 answer was not counted: the judge gave no clear verdict." in out


def test_a_close_copy_says_why_once_and_so_on_every_line(fake, capsys):
    _edit(fake.ws.root, lambda d: d.pop("metadata"))  # no promptfoo version recorded
    fake.saved = FakePromptfoo(fake.ws).saved
    _, out, _ = run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    after = out.split("Asking your judge")[-1] if "Asking your judge" in out else \
        out.split("Go ahead")[-1]
    after = after[after.index("This was a close copy"):]
    assert after.count("promptfoo version not recorded") == 1
    assert after.startswith("This was a close copy of your judge: promptfoo version not "
                            "recorded.\n")
    lines = [x for x in after.splitlines() if x.startswith((
        "Asked twice", "Of the answers you", "Its first new verdict"))]
    assert len(lines) == 4 and all(x.endswith(" (close copy)") for x in lines)
    page = fake.ws.result_html.read_text()
    assert page.count("promptfoo version not recorded") == 1 and "(close copy)" in page


def test_exactly_your_judge_has_no_close_copy_words(fake, capsys):
    _, out, _ = run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    assert "close copy" not in out


def test_one_time_says_steadiness_needs_two(fake, capsys):
    _, out, _ = run(capsys, fake.ws.root, "--ask-again", "--times", "1", "--allow-calls", "36")
    assert "Asked once more: ask at least twice to see whether it changes its mind." in out


# The saved files ----------------------------------------------------------------------------

def test_every_line_carries_the_full_fingerprint(fake, capsys):
    fake.extra = f" (key {SECRET})"
    run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    folder = _again_dir(fake.ws)
    assert (folder / "promptfoo.json").is_file()
    runs = sorted(folder.glob("judge-again-*.jsonl"))
    assert [p.name for p in runs] == ["judge-again-1.jsonl", "judge-again-2.jsonl"]
    for path in runs:
        header, records = read_run(path)
        assert header["source"]["kind"] == "promptfoo"
        assert len(records) == 36
        for rec in records.values():
            fp = rec["fingerprint"]
            assert fp["provider"] == "openai" and fp["model"] == "openai:gpt-4.1-mini"
            assert fp["temperature"] == 0.0 and fp["prompt_hash"] and fp["created_at"]
            assert fp["tool"] == "promptfoo" and fp["tool_version"] == "0.123.1"
            assert fp["judge_copy"] == "exact" and fp["judge_copy_why"] == []
            assert fp["settings"] == []
    every = "".join(p.read_text() for p in folder.iterdir())
    every += fake.ws.result_json.read_text() + fake.ws.result_html.read_text()
    assert SECRET not in every and "[REDACTED]" in every


def test_setting_names_go_into_the_fingerprint(fake, capsys, monkeypatch):
    monkeypatch.setenv("OPENAI_TEMPERATURE", "0.9")
    run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    _, records = read_run(_again_dir(fake.ws) / "judge-again-1.jsonl")
    assert all(r["fingerprint"]["settings"] == ["OPENAI_TEMPERATURE"] for r in records.values())


def test_an_earlier_again_block_goes_to_history(fake, capsys):
    run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    first = json.loads(fake.ws.result_json.read_text())["again"]
    run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    kept = list(fake.ws.history.glob("again-*.json"))
    assert len(kept) == 1 and json.loads(kept[0].read_text()) == first


def test_the_result_page_shows_the_again_lines(fake, capsys):
    run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    page = fake.ws.result_html.read_text()
    assert "Your judge, asked again" in page and "Asked twice more" in page


def test_the_main_result_does_not_change(fake, capsys):
    before = json.loads(fake.ws.result_json.read_text())
    labels = fake.ws.labels.read_bytes()
    run(capsys, fake.ws.root, "--ask-again", "--allow-calls", "72")
    after = json.loads(fake.ws.result_json.read_text())
    for key in ("tpr", "tnr", "kappa", "made_at", "labels"):
        assert after[key] == before[key]
    assert fake.ws.labels.read_bytes() == labels


# Your own judge command ----------------------------------------------------------------------

EXEC = FIXTURES / "exec"


def test_the_judge_command_runs_through_exec(tmp_path, capsys, monkeypatch):
    ws = _checked(tmp_path, maker=table_project)
    command = f"{sys.executable} {EXEC / 'bare.py'}"
    code, out, _ = run(capsys, ws.root, "--ask-again", "--judge-command", command,
                       "--allow-calls", "72")
    assert code == 0
    assert f"This runs `{command}` 72 times." in out
    assert "Asked twice more" in out
    _, records = read_run(_again_dir(ws) / "judge-again-1.jsonl")
    assert len(records) == 36
    assert all(r["fingerprint"]["tool"] == "command" for r in records.values())


def test_a_judge_command_that_fails_is_not_counted(tmp_path, capsys):
    ws = _checked(tmp_path, maker=table_project)
    command = f"{sys.executable} {EXEC / 'fails_some.py'}"
    code, out, _ = run(capsys, ws.root, "--ask-again", "--judge-command", command,
                       "--allow-calls", "72")
    assert code == 0 and "not counted" in out


# Next lines ----------------------------------------------------------------------------------

def test_next_says_how_to_ask_again(tmp_path):
    ws = _checked(tmp_path)
    r = json.loads(ws.result_json.read_text())
    assert "  Ask your judge again:  judgekeeper start --ask-again" in start_label.result_lines(r)
    page = ws.result_html.read_text()
    assert "Ask your judge again" in page and "<code>judgekeeper start --ask-again</code>" in page


# The real promptfoo (optional) -----------------------------------------------------------------

@pytest.mark.skipif(shutil.which("promptfoo") is None, reason="promptfoo is not installed")
def test_a_real_regrade_matches_every_grading_prompt(tmp_path, monkeypatch):
    real = FIXTURES / "promptfoo" / "real"
    project = tmp_path / "real"
    shutil.copytree(real, project)
    (project / "labels.csv").unlink()
    ws = start_label.prepare(start.find_judge(project), say=_quiet)
    session = StartSession(ws)
    for q in ws.data()["queue"]:
        session.update({"id": q["id"], "label": q["group"]})
    save_result(ws, session, say=_quiet)
    monkeypatch.setattr(pf, "_code", lambda values: False)  # the fake grader is exec: code
    plan = make_plan(ws, AgainOptions(times=1))
    assert plan.status != "cant", plan.why
    fresh = pf.run(ws, plan, start.Talk(quiet=True))
    assert fresh.not_counted == {}
    assert len(fresh.verdicts) == plan.answers
