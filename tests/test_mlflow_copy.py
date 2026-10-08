"""An MLflow `mlflow.db` store is read through a temporary copy, on every system.

judgekeeper never opens the user's own store file through MLflow: it copies `mlflow.db` (and
`mlflow.db-wal` and `mlflow.db-shm` when present) into a temporary folder once per process,
reads the copy with a plain `sqlite:///` address, and removes the folder when the process
ends. A read-only address (`sqlite:///file:...?mode=ro&uri=true`) would be taken as a file
name on Windows. A folder store (`mlruns/`) is read where it is.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from judgekeeper import start
from judgekeeper.readers import mlflow_store


@pytest.fixture(autouse=True)
def no_copies_left():
    yield
    mlflow_store.remove_copies()


def _store(folder: Path, wal: bool = True) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    db = folder / "mlflow.db"
    db.write_bytes(b"SQLite format 3\x00" + b"x" * 100)
    if wal:
        (folder / "mlflow.db-wal").write_bytes(b"wal bytes")
        (folder / "mlflow.db-shm").write_bytes(b"shm bytes")
    old = time.time() - 3600
    for p in folder.iterdir():
        os.utime(p, (old, old))
    return db


def _state(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(folder.rglob("*")) if p.is_file()}


def test_the_copy_is_made_used_and_removed(tmp_path):
    db = _store(tmp_path / "project")
    before = _state(db.parent)
    uri = mlflow_store.store_uri(db)
    assert uri.startswith("sqlite:///") and "mode=ro" not in uri
    copy = Path(uri.removeprefix("sqlite:///"))
    assert copy.name == "mlflow.db" and copy.parent != db.parent
    assert copy.read_bytes() == db.read_bytes()
    assert (copy.parent / "mlflow.db-wal").read_bytes() == b"wal bytes"
    assert (copy.parent / "mlflow.db-shm").read_bytes() == b"shm bytes"
    assert mlflow_store.store_uri(db) == uri  # one copy per process
    mlflow_store.remove_copies()
    assert not copy.parent.exists()
    assert _state(db.parent) == before  # the user's files: same bytes, same times


def test_a_changed_store_is_copied_again(tmp_path):
    db = _store(tmp_path / "project", wal=False)
    first = mlflow_store.store_uri(db)
    db.write_bytes(db.read_bytes() + b"more")
    assert mlflow_store.store_uri(db) != first


def test_a_folder_store_is_read_where_it_is(tmp_path):
    folder = tmp_path / "mlruns"
    folder.mkdir()
    assert mlflow_store.store_uri(folder) == str(folder)


def test_a_big_store_says_so_first(tmp_path, monkeypatch):
    db = _store(tmp_path / "project", wal=False)
    monkeypatch.setattr(mlflow_store, "BIG_STORE", 10)
    said = []
    mlflow_store.store_uri(db, say=said.append)
    assert said == ["Reading a copy of mlflow.db (0.0 GB)…"]
    said.clear()
    monkeypatch.setattr(mlflow_store, "BIG_STORE", 10**12)
    mlflow_store.remove_copies()
    mlflow_store.store_uri(db, say=said.append)
    assert said == []


def test_start_reads_a_real_store_through_a_copy(tmp_path, monkeypatch):
    from tests.conftest import build_mlflow_store

    build_mlflow_store(tmp_path)
    db = tmp_path / "mlflow.db"
    before = _state(tmp_path)
    seen = []
    real = start.read_mlflow

    def spy(*args, **kwargs):
        seen.append(kwargs["tracking_uri"])
        return real(*args, **kwargs)

    monkeypatch.setattr(start, "read_mlflow", spy)
    found = start.find_judge(tmp_path, metric="correctness")
    assert len(found.pool.answers) == 8
    assert seen and all(u.startswith("sqlite:///") and "mode=ro" not in u for u in seen)
    assert all(Path(u.removeprefix("sqlite:///")) != db for u in seen)
    after = _state(tmp_path)
    assert {k: after[k] for k in before} == before  # nothing the user had is touched


def test_asking_again_reads_a_real_store_through_a_copy(tmp_path):
    from judgekeeper import start_label
    from judgekeeper.again import mlflow as mf
    from tests.conftest import build_mlflow_store

    build_mlflow_store(tmp_path)
    info = mf.assessment_info(start_label.Workspace(tmp_path), "correctness")
    assert info["uri"].startswith("sqlite:///") and "mode=ro" not in info["uri"]
    assert Path(info["uri"].removeprefix("sqlite:///")) != tmp_path / "mlflow.db"
    assert Path(info["uri"].removeprefix("sqlite:///")).is_file()  # kept for the worker


def test_a_folder_store_reads_and_stays_as_it_was(tmp_path, monkeypatch):
    """judgekeeper reads an mlruns/ folder in place, and nothing in it changes."""
    from tests.conftest import build_mlflow_folder_store

    folder = build_mlflow_folder_store(tmp_path / "project" / "mlruns")
    before = _state(folder)
    monkeypatch.delenv("MLFLOW_ALLOW_FILE_STORE", raising=False)
    found = start.find_judge(tmp_path / "project")
    assert found.tool == "mlflow" and len(found.pool.answers) == 4
    assert _state(folder) == before
