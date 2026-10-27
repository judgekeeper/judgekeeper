"""Odd files a project can hold never hang judgekeeper or send people to report a bug.

- A folder or a named pipe (FIFO) where judgekeeper keeps a file of its own is said plainly,
  and a lock mark from the future is old.
- A table of a million tiny rows is read up to MAX_ROWS answers, and that is said once.
- A lone surrogate (\\ud800) in a results file, a judgekeeper.toml nested thousands deep and
  a promptfoo export nested thousands deep are said in one plain line; nothing is written.
- One table that can't be read never stops the folder scan.
- record() never writes in the home folder.
No test calls an AI API.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from judgekeeper import page, recorder, start_export, table, textio
from judgekeeper.table import derive_id
from tests.start_projects import promptfoo_project, split, table_project
from tests.test_front import run

ROOT = Path(__file__).resolve().parent.parent
LINK = page.LINK
UNEXPECTED = "Please report it"
no_fifo = pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no named pipes here")


@pytest.fixture
def here(tmp_path, monkeypatch):
    project = tmp_path / "support-bot"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


def in_time(fn, seconds: float = 10):
    """fn(), which must finish within `seconds`: a hang fails the test instead of the run."""
    box = {}

    def go():
        try:
            box["value"] = fn()
        except Exception as e:  # noqa: BLE001 - raised again in the test's own thread
            box["error"] = e

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), "judgekeeper hung"
    if "error" in box:
        raise box["error"]
    return box["value"]


def files(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in folder.rglob("*") if p.is_file()} if folder.is_dir() else {}


# Lock names that are not files ------------------------------------------------------------------

def test_a_folder_named_opening_is_said_not_waited_for(here, capsys):
    promptfoo_project(here, split(20, 16))
    opening = here / ".judgekeeper" / "opening"
    (opening / "x").parent.mkdir(parents=True)
    (opening / "x").write_text("cloned", encoding="utf-8")
    old = time.time() - 600
    os.utime(opening, (old, old))
    code, out, err = in_time(lambda: run(capsys, "--no-browser", "--port", "0"))
    assert code == 2, out + err
    flat = " ".join((out + err).split())
    assert ("error: .judgekeeper/opening is a folder, but judgekeeper keeps a file of its own "
            "there.") in flat
    assert "Next: move or rename .judgekeeper/opening, then run `judgekeeper" in flat
    assert page.OPENING_NOW not in flat and UNEXPECTED not in flat
    assert (opening / "x").is_file()  # nothing removed


def test_an_opening_mark_from_the_future_is_old(here, capsys):
    promptfoo_project(here, split(20, 16))
    (here / ".judgekeeper").mkdir()
    opening = here / ".judgekeeper" / "opening"
    opening.write_text("from a zip", encoding="utf-8")
    future = time.time() + 10 * 365 * 24 * 3600
    os.utime(opening, (future, future))
    code, out, err = in_time(lambda: run(capsys, "--no-browser", "--port", "0"))
    assert code == 0, out + err
    assert LINK in out and page.OPENING_NOW not in out
    assert not opening.exists()


@pytest.mark.parametrize("name", ["server.json", "page.json"])
def test_a_folder_at_the_pages_lock_is_said_not_blamed_on_the_port(here, capsys, name, pages):
    promptfoo_project(here, split(20, 16))
    (here / ".judgekeeper" / name).mkdir(parents=True)
    code, out, err = in_time(lambda: run(capsys, "--no-browser", "--port", "0"))
    assert code == 2, out + err
    flat = " ".join((out + err).split())
    assert f".judgekeeper/{name} is a folder, but judgekeeper keeps a file of its own there." \
        in flat
    assert "in use" not in flat and "page.log" not in flat
    assert pages[0] == []  # no page was started


# Named pipes ----------------------------------------------------------------------------------

CHILD = "import sys; from judgekeeper.cli import main; sys.exit(main(sys.argv[1:]))"


@no_fifo
@pytest.mark.parametrize("name, said", [
    ("results.json", ("results.json is not a regular file (a named pipe or a device), so it "
                      "was left out.")),
    (".judgekeeper/judge.json", ("error: .judgekeeper/judge.json is a named pipe, but "
                                 "judgekeeper keeps a file of its own there.")),
])
def test_a_named_pipe_never_hangs_judgekeeper(tmp_path, name, said):
    project = tmp_path / "p"
    project.mkdir()
    promptfoo_project(project, split(20, 16))
    if name == "results.json":
        (project / name).unlink()
    pipe = project / name
    pipe.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(pipe)
    began = time.monotonic()
    done = subprocess.run([sys.executable, "-c", CHILD, "--no-browser", "--port", "0"],
                          cwd=project, capture_output=True, text=True, timeout=60,
                          stdin=subprocess.DEVNULL, check=False)
    assert time.monotonic() - began < 30
    out = " ".join((done.stdout + done.stderr).split())
    assert done.returncode in (0, 2, 3), out
    assert UNEXPECTED not in out and "Traceback" not in out
    assert said in out
    subprocess.run([sys.executable, "-c", CHILD, "--stop"], cwd=project, capture_output=True,
                   timeout=60, stdin=subprocess.DEVNULL, check=False)


@no_fifo
def test_read_utf8_refuses_a_named_pipe_at_once(tmp_path):
    pipe = tmp_path / "results.csv"
    os.mkfifo(pipe)
    with pytest.raises(table.TableError, match="results.csv is a named pipe, not a file"):
        in_time(lambda: textio.read_utf8(pipe, table.TableError), 5)


@no_fifo
def test_a_named_pipe_at_env_is_never_waited_for(tmp_path):
    from judgekeeper import keys

    pipe = tmp_path / ".env"
    os.mkfifo(pipe)
    assert in_time(lambda: keys.names_in(pipe), 5) == set()


# A big table ------------------------------------------------------------------------------------

def _million(path: Path) -> Path:
    rows = "".join(f"{i},{i},{'pass' if i % 2 else 'fail'}\n" for i in range(1_000_000))
    path.write_text("input,output,verdict\n" + rows, encoding="utf-8")
    return path


def test_a_table_of_a_million_rows_is_read_up_to_the_cap(here, capsys):
    _million(here / "results.csv")
    began = time.monotonic()
    code, out, err = run(capsys, "--no-browser", "--port", "0")
    seconds = time.monotonic() - began
    assert code == 0, out + err
    said = "Read the first 100,000 answers of results.csv; the rest are left out."
    assert (out + err).count(said) == 1, out + err
    pool = (here / ".judgekeeper" / "pool.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(pool) == table.MAX_ROWS
    assert seconds < 60, seconds  # it took 100 seconds and 4 GB before the cap


@pytest.mark.skipif(sys.platform == "win32", reason="resource is POSIX only")
def test_reading_a_million_rows_stays_small(tmp_path):
    import resource

    _million(tmp_path / "results.csv")
    script = ("import resource, sys, time; from judgekeeper.table import read_table; "
              "t = time.monotonic(); rows = read_table(sys.argv[1]); "
              "print(len(rows), time.monotonic() - t, "
              "resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)")
    done = subprocess.run([sys.executable, "-c", script, str(tmp_path / "results.csv")],
                          capture_output=True, text=True, timeout=120, check=True)
    n, seconds, rss = done.stdout.split()
    megabytes = int(rss) / (1 if sys.platform != "darwin" else 1024) / 1024
    assert int(n) == table.MAX_ROWS
    assert float(seconds) < 10 and megabytes < 400, (seconds, megabytes)
    assert done.stderr.count("Read the first 100,000 answers") == 1
    del resource


# Unreadable input: a plain line, nothing written --------------------------------------------

def test_a_lone_surrogate_in_promptfoo_results_is_said_plainly(here, capsys):
    promptfoo_project(here, split(20, 16))
    path = here / "results.json"
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    first = data["results"]["results"][0]
    first["response"]["output"] = "SURROGATE_HERE lone"
    path.write_text(json.dumps(data).replace("SURROGATE_HERE", "\\ud800"), encoding="utf-8")
    code, out, err = run(capsys, "--no-browser", "--port", "0")
    assert code == 2, out + err
    flat = " ".join((out + err).split())
    assert "results.json holds a character that isn't text (a lone surrogate such as " \
           "\\ud800)" in flat
    assert UNEXPECTED not in flat
    assert files(here / ".judgekeeper") == {}


def test_a_lone_surrogate_in_a_table_without_ids_is_said_plainly(here, capsys):
    path = here / "surr_results.jsonl"
    path.write_text('{"input":"q\\ud800x","output":"a","verdict":"pass"}\n'
                    '{"input":"q2","output":"a2","verdict":"fail"}\n', encoding="utf-8")
    code, out, err = run(capsys, "surr_results.jsonl", "--no-browser", "--port", "0")
    assert code == 2, out + err
    flat = " ".join((out + err).split())
    assert "surr_results.jsonl: line 1 holds a character that isn't text" in flat
    assert UNEXPECTED not in flat
    assert files(here / ".judgekeeper") == {}


def test_an_id_is_made_from_text_with_a_lone_surrogate():
    assert len(derive_id({"input": "q\ud800", "output": "a"})) == 16


def test_a_judgekeeper_toml_nested_thousands_deep_is_said_plainly(here, capsys):
    promptfoo_project(here, split(20, 16))
    deep = "x = " + "{a=" * 5000 + "1" + "}" * 5000
    (here / "judgekeeper.toml").write_text(f"[start]\n{deep}\n", encoding="utf-8")
    code, out, err = run(capsys, "--no-browser", "--port", "0")
    assert code == 2, out + err
    flat = " ".join((out + err).split())
    assert "judgekeeper.toml: invalid TOML: it is nested too deep to read" in flat
    assert UNEXPECTED not in flat
    assert files(here / ".judgekeeper") == {}


# One bad table in the folder ------------------------------------------------------------------

def test_a_nul_byte_table_next_to_promptfoo_results_is_left_out(here, capsys):
    promptfoo_project(here, split(20, 16))
    (here / "data").mkdir()
    (here / "data" / "nul_results.csv").write_bytes(b"input,output,verdict\nq\x00,a,pass\n")
    code, out, err = run(capsys, "--no-browser", "--port", "0")
    assert code == 0, out + err
    flat = " ".join(out.split())
    assert "data/nul_results.csv is not saved as UTF-8, so it was left out." in flat
    assert "Eval tool: promptfoo" in flat and LINK in out


def test_bad_tables_are_counted_once_and_the_good_one_is_read(here, capsys):
    table_project(here, split(20, 16), name="t/good_results.csv")
    (here / "t" / "nul_results.csv").write_bytes(b"input,output,verdict\nq\x00,a,pass\n")
    (here / "t" / "quote_results.csv").write_text(
        'input,output,verdict\n"open,a,pass\nq,a,fail\n', encoding="utf-8")
    code, out, err = run(capsys, "--no-browser", "--port", "0")
    assert code == 0, out + err
    flat = " ".join(out.split())
    assert ("2 tables can't be read, so they were left out; the first, t/nul_results.csv, "
            "is not saved as UTF-8.") in flat
    assert flat.count("can't be read") == 1
    assert LINK in out


def test_a_bad_table_named_on_the_command_line_still_stops(here, capsys):
    (here / "nul_results.csv").write_bytes(b"input,output,verdict\nq\x00,a,pass\n")
    code, out, err = run(capsys, "nul_results.csv", "--no-browser", "--port", "0")
    assert code == 2
    assert "nul_results.csv is not saved as UTF-8" in " ".join((out + err).split())


# The promptfoo export -------------------------------------------------------------------------

class Talk:
    def __init__(self):
        self.said = []

    def say(self, line=""):
        self.said.append(line)

    def confirm(self, *a, **k):
        return True


def test_a_deeply_nested_export_is_refused_and_removed(here, monkeypatch):
    from judgekeeper import again, start

    (here / "promptfooconfig.yaml").write_text("description: support bot\n", encoding="utf-8")
    monkeypatch.setattr(start, "_interactive", lambda: True)
    monkeypatch.setattr(start_export, "_promptfoo", lambda root: "/usr/bin/promptfoo")

    def export(argv, cwd, env=None, timeout=None):
        out = Path(argv[argv.index("-o") + 1])
        out.write_text("[" * 3000 + "]" * 3000, encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(again, "run_process", export)
    talk = Talk()
    assert start_export.offer(talk, here, "promptfooconfig.yaml") == "commands"
    assert not (here / start_export.LATEST).exists()
    assert talk.said == [start_export.UNREADABLE]
    assert "removed it (.judgekeeper/promptfoo-latest.json)" in start_export.UNREADABLE


# record() at home --------------------------------------------------------------------------------

def test_record_never_writes_in_the_home_folder(tmp_path, monkeypatch, caplog):
    import judgekeeper

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JUDGEKEEPER_RECORD", raising=False)
    recorder._reset()
    with caplog.at_level(logging.WARNING, logger="judgekeeper"):
        judgekeeper.record("q", "a", verdict="pass")
        judgekeeper.record("q2", "a2", verdict="fail")
    recorder._reset()
    assert not (tmp_path / ".judgekeeper").exists()
    warnings = [r.getMessage() for r in caplog.records if r.name == "judgekeeper"]
    assert len(warnings) == 1 and "never writes in your home folder" in warnings[0]
