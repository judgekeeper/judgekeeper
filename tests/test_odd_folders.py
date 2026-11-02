"""`judgekeeper` run in a folder of devices, pipes and entries that can't be looked at (`/`,
`/dev`): every walk skips what isn't a plain file or folder, and the run says what it says in
a folder with no results."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

from judgekeeper import find, own_format, start
from judgekeeper.cli import main

posix = pytest.mark.skipif(sys.platform == "win32", reason="no /dev, FIFOs or sockets there")
NO_RESULTS = "No eval results found in this folder"


def _run(capsys, *argv) -> tuple[int, str]:
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out + err


class _Broken:
    """A folder entry that can't be told what it is (/dev/fd/3 when its folder is read)."""

    def __init__(self, entry):
        self.name, self.path = entry.name, entry.path

    def _fail(self, *args, **kwargs):
        raise OSError(9, "Bad file descriptor")

    is_symlink = is_dir = is_file = stat = inode = _fail


@pytest.fixture
def broken(monkeypatch):
    """os.scandir, with each entry named fd3* made one that can't be looked at."""
    real = os.scandir

    class Entries(list):  # as os.scandir's iterator: also a context manager
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def close(self):
            pass

    def scandir(path="."):
        with real(path) as entries:
            return Entries(_Broken(e) if e.name.startswith("fd3") else e for e in entries)

    monkeypatch.setattr(os, "scandir", scandir)


def _odd_folder(root: Path) -> Path:
    """A folder of odd entries: one that can't be looked at, at each depth, a FIFO and a
    socket named like results, and a link to a results file."""
    for folder in (root, root / "fd", root / "fd" / "deeper" / "and" / "deeper" / "still"):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "fd3.json").write_text("{}", encoding="utf-8")
        (folder / "fd3").mkdir(exist_ok=True)
    os.mkfifo(root / "fd" / "results.json")  # opening it would wait for a writer forever
    os.mkfifo(root / "promptfooconfig.yaml")
    sock = socket.socket(socket.AF_UNIX)
    try:
        sock.bind(str(root / "fd" / "results.csv"))
    except OSError:
        pass  # too long a path for a socket on this system: the FIFO is enough
    finally:
        sock.close()
    return root


@posix
def test_a_folder_of_odd_entries_reads_as_one_with_no_results(tmp_path, monkeypatch, capsys,
                                                             broken):
    folder = _odd_folder(tmp_path / "odd")
    monkeypatch.chdir(folder)
    code, out = _run(capsys, "--no-browser")
    assert code == 3 and NO_RESULTS in out, out
    assert "cannot use" not in out and "Bad file descriptor" not in out
    assert not (folder / ".judgekeeper").exists()


@posix
def test_each_walk_skips_what_it_cant_look_at(tmp_path, broken):
    folder = _odd_folder(tmp_path / "odd")
    assert own_format.search(folder) is None
    assert start._promptfoo_configs(folder) == {}
    found = find.search(folder)
    assert not found.results


@posix
@pytest.mark.parametrize("folder", ["/dev", "/"])
def test_judgekeeper_from_a_system_folder_never_stops_on_an_entry(monkeypatch, capsys, folder):
    """`cd / && judgekeeper` and `cd /dev && judgekeeper`: from /dev the walk skips devices and
    /dev/fd's entries and says there are no results; from / it searches nothing and says to
    go to the project folder. No error about an entry."""
    if not Path(folder).is_dir():
        pytest.skip(f"no {folder} here")
    monkeypatch.chdir(folder)
    code, out = _run(capsys, "--no-browser")
    assert "cannot use" not in out and "Bad file descriptor" not in out, out
    assert "Traceback" not in out
    if folder == "/dev":
        assert code == 3 and NO_RESULTS in out, out
    else:
        assert code == 3 and "Go to it (`cd <your project folder>`)" in " ".join(out.split()), out


@posix
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads any folder")
def test_a_folder_that_cant_be_read_below_is_skipped(tmp_path, monkeypatch, capsys):
    """A folder right below that can't be read (as /lost+found from `/`): the run never stops
    on it, and an error about it is never said as one about .judgekeeper/."""
    from judgekeeper import front, textio

    locked = tmp_path / "lost+found"
    locked.mkdir()
    locked.chmod(0)
    try:
        assert front._sessions_below(tmp_path) == []
        e = PermissionError(13, "Permission denied", "lost+found/.judgekeeper/start.json")
        monkeypatch.chdir(tmp_path)
        assert textio.workspace_problem(e) is None
        code, out = _run(capsys, "--no-browser")
        assert "Traceback" not in out and "Permission denied" not in out, out
        assert code == 3 and NO_RESULTS in out, out
    finally:
        locked.chmod(0o700)
