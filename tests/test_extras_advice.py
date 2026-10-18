"""Reading MLflow or Inspect's .eval logs needs one of judgekeeper's extras. Started by uvx,
`pip install` would not reach uvx's own environment (and an unpinned install picks an older
judgekeeper during the beta): the advice is the uvx command that has the extra. Otherwise it
is `pip install "judgekeeper[<extra>]==<version>"`, pinned while the version is a beta.
Once started with an extra, every printed command keeps it."""

from __future__ import annotations

import sys

import pytest

from judgekeeper import __version__, textio
from tests.test_front import assert_one_next_at_the_end, run
from tests.test_uvx import CACHES

PIN = f"=={__version__}" if textio.is_prerelease() else ""


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def by_uvx(monkeypatch):
    monkeypatch.setenv("UV", "/Users/me/.local/bin/uv")
    monkeypatch.setattr(sys, "prefix", CACHES[0])
    monkeypatch.setattr(textio, "extras_here", lambda: ())


def _mlflow_store(root):
    (root / "mlruns" / "0").mkdir(parents=True)
    (root / "mlruns" / "0" / "meta.yaml").write_text("name: Default\n", encoding="utf-8")


def _eval_log(root):
    (root / "logs").mkdir()
    (root / "logs" / "2026-10-02_support.eval").write_bytes(b"PK\x03\x04 not read")


@pytest.mark.parametrize("module, extra, name, make", [
    ("mlflow", "mlflow", "MLflow", _mlflow_store),
    ("inspect_ai", "inspect", "Inspect AI", _eval_log),
])
def test_started_by_uvx_the_advice_is_the_uvx_command_with_the_extra(
        here, capsys, monkeypatch, by_uvx, module, extra, name, make):
    monkeypatch.setitem(sys.modules, module, None)
    make(here)
    code, out, _ = run(capsys)
    command = f'uvx --from "judgekeeper[{extra}]=={__version__}" judgekeeper'
    assert f"Reading {name} results needs judgekeeper's {extra} extra." in " ".join(out.split())
    assert " ".join(out.split()).count(command) == 1  # in the Next: line only
    assert "pip install" not in out
    assert assert_one_next_at_the_end(out) == f"Next: run `{command}`."
    assert code == 3  # the person is needed


@pytest.mark.parametrize("module, extra, name, make", [
    ("mlflow", "mlflow", "MLflow", _mlflow_store),
    ("inspect_ai", "inspect", "Inspect AI", _eval_log),
])
def test_otherwise_pip_install_with_the_version(here, capsys, monkeypatch, module, extra, name,
                                                make):
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.setitem(sys.modules, module, None)
    make(here)
    code, out, _ = run(capsys)
    install = f'pip install "judgekeeper[{extra}]{PIN}"'
    assert f"{name} found" in out
    assert " ".join(out.split()).count(install) == 1  # in the Next: line only
    assert install in assert_one_next_at_the_end(out)
    assert code == 3  # the person is needed


def test_a_beta_is_pinned():
    assert textio.is_prerelease("1.0.0b1")
    assert textio.is_prerelease("1.1.0rc2")
    assert not textio.is_prerelease("1.0.0")


def test_started_by_uvx_with_an_extra_every_command_keeps_it(monkeypatch, by_uvx):
    monkeypatch.setattr(textio, "extras_here", lambda: ("mlflow",))
    assert textio.program("mark") == (f'uvx --from "judgekeeper[mlflow]=={__version__}" '
                                      "judgekeeper mark")


def test_a_second_extra_keeps_the_first(monkeypatch, by_uvx):
    monkeypatch.setattr(textio, "extras_here", lambda: ("mlflow",))
    assert textio.uvx_with("inspect") == (f'uvx --from "judgekeeper[inspect,mlflow]=='
                                          f'{__version__}" judgekeeper')


def test_extras_here_names_the_extras_whose_module_is_installed(monkeypatch):
    found = {"mlflow"}
    monkeypatch.setattr("importlib.util.find_spec",
                        lambda name: object() if name in found else None)
    assert textio.extras_here() == ("mlflow",)


def test_started_by_uvx_with_an_extra_the_next_lines_keep_it(here, capsys, monkeypatch,
                                                            by_uvx):
    monkeypatch.setattr(textio, "extras_here", lambda: ("mlflow",))
    command = f'uvx --from "judgekeeper[mlflow]=={__version__}" judgekeeper'
    (here / "survey.csv").write_text("No,Question,Answer\n1,q,a\n", encoding="utf-8")
    code, out, _ = run(capsys, "survey.csv")
    assert f"`{command} <the CSV>`" in assert_one_next_at_the_end(out)
    assert "`judgekeeper " not in out
    assert code == 3
