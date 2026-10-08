"""`baseline` and `gate` commands: files written, default paths, exit codes."""

import json
import shutil
from pathlib import Path

import pytest

from judgekeeper.cli import main

GATE = Path(__file__).parent / "fixtures" / "gate"


@pytest.fixture
def work(tmp_path, monkeypatch):
    """A clean working directory holding copies of the gate fixtures."""
    monkeypatch.chdir(tmp_path)
    for p in GATE.glob("*.json"):
        d = tmp_path / p.stem
        d.mkdir()
        shutil.copy(p, d / "report.json")
    return tmp_path


def gate(work, name, *extra):
    return main(["gate", str(work / name / "report.json"), *extra])


# --- baseline ------------------------------------------------------------------------------


def test_baseline_set_copies_to_default_path(work, capsys):
    assert main(["baseline", "set", str(work / "baseline" / "report.json")]) == 0
    dst = work / ".judgekeeper" / "baseline.json"
    assert dst.read_text(
        encoding="utf-8") == (work / "baseline" / "report.json").read_text(encoding="utf-8")
    # the path as the system writes it: .judgekeeper/baseline.json, or with \ on Windows
    assert str(Path(".judgekeeper") / "baseline.json") in capsys.readouterr().out


def test_baseline_set_custom_path(work):
    dst = work / "b" / "base.json"
    assert main(["baseline", "set", str(work / "pass" / "report.json"), "--path", str(dst)]) == 0
    assert json.loads(dst.read_text(
        encoding="utf-8"))["headline"]["kappa_mean"] == pytest.approx(0.8)


def test_baseline_set_rejects_non_report(work):
    bad = work / "bad.json"
    bad.write_text('{"hello": 1}', encoding="utf-8")
    assert main(["baseline", "set", str(bad)]) == 2
    assert main(["baseline", "set", str(work / "missing.json")]) == 2
    assert not (work / ".judgekeeper").exists()


def test_baseline_show(work, capsys):
    main(["baseline", "set", str(work / "baseline" / "report.json")])
    capsys.readouterr()
    assert main(["baseline", "show"]) == 0
    out = capsys.readouterr().out
    for needle in ["claude-haiku-4-5-20251001", "pairwise-v1", "a" * 64, "kappa", "0.80",
                   "0.78", "0.82", "TPR", "0.91", "TNR", "0.89", "runs: 3"]:
        assert needle in out
    assert "accuracy" not in out.lower()


def test_baseline_show_without_baseline_is_usage_error(work):
    assert main(["baseline", "show"]) == 2
    assert main(["baseline"]) == 2


# --- gate: exit codes and outputs ------------------------------------------------------------


@pytest.mark.parametrize("name,code", [
    ("pass", 0),
    ("kappa-drop-inside-band", 0),
    ("kappa-drop-outside-band", 1),
    ("passes-everything", 1),
    ("anchors-changed", 3),
    ("best-run-passes", 4),
    ("two-runs", 4),
    ("snapshot-changed", 5),
])
def test_gate_exit_codes(work, name, code):
    baseline = work / "baseline" / "report.json"
    extra = [] if name == "passes-everything" else ["--baseline", str(baseline)]
    assert gate(work, name, *extra) == code


@pytest.mark.parametrize("flaky_as,code", [("pass", 0), ("fail", 1)])
def test_gate_flaky_as(work, capsys, flaky_as, code):
    assert gate(work, "two-runs", "--flaky-as", flaky_as) == code
    assert "FLAKY" in capsys.readouterr().out
    assert json.loads((work / "two-runs" / "gate.json").read_text(
        encoding="utf-8"))["status"] == "FLAKY"


def test_gate_flaky_as_does_not_touch_other_statuses(work):
    assert gate(work, "passes-everything", "--flaky-as", "pass") == 1


def test_gate_bad_flaky_as_is_usage_error(work):
    assert gate(work, "pass", "--flaky-as", "maybe") == 2


def test_gate_writes_json_and_markdown_next_to_report(work, capsys):
    assert gate(work, "kappa-drop-outside-band", "--baseline",
                str(work / "baseline" / "report.json")) == 1
    out_dir = work / "kappa-drop-outside-band"
    result = json.loads((out_dir / "gate.json").read_text(encoding="utf-8"))
    assert result["status"] == "FAIL"
    assert result["exit_code"] == 1
    assert result["fingerprint"]["model"] == "claude-haiku-4-5-20251001"
    md = (out_dir / "gate.md").read_text(encoding="utf-8")
    assert md.startswith("## judgekeeper gate: FAIL")
    out = capsys.readouterr().out
    assert "FAIL" in out and "gate.md" in out


def test_gate_out_dir(work):
    assert gate(work, "pass", "--out", str(work / "o")) == 0
    assert (work / "o" / "gate.json").exists() and (work / "o" / "gate.md").exists()


def test_gate_uses_committed_baseline_by_default(work, capsys):
    main(["baseline", "set", str(work / "baseline" / "report.json")])
    assert gate(work, "kappa-drop-outside-band") == 1
    assert gate(work, "snapshot-changed") == 5
    assert gate(work, "snapshot-changed", "--allow-judge-change") == 0


def test_gate_without_any_baseline_uses_absolute_only(work):
    assert gate(work, "kappa-drop-outside-band") == 0


def test_gate_missing_explicit_baseline_is_usage_error(work):
    assert gate(work, "pass", "--baseline", str(work / "nope.json")) == 2


def test_gate_bad_report_is_usage_error(work):
    bad = work / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert main(["gate", str(bad)]) == 2
    assert main(["gate", str(work / "missing.json")]) == 2


# --- gate: config ----------------------------------------------------------------------------


def test_gate_config_flag(work):
    cfg = work / "strict.toml"
    cfg.write_text("[gate]\nkappa_min = 0.9\n", encoding="utf-8")
    assert gate(work, "pass", "--config", str(cfg)) == 1


def test_gate_reads_judgekeeper_toml_by_default(work):
    (work / "judgekeeper.toml").write_text("[gate]\nkappa_min = 0.9\n", encoding="utf-8")
    assert gate(work, "pass") == 1


def test_gate_unknown_config_key_is_usage_error(work, capsys):
    cfg = work / "judgekeeper.toml"
    cfg.write_text("[gate]\nkappa_minimum = 0.9\n", encoding="utf-8")
    assert gate(work, "pass") == 2
    assert "kappa_minimum" in capsys.readouterr().err
    assert not (work / "pass" / "gate.json").exists()


def test_gate_missing_explicit_config_is_usage_error(work):
    assert gate(work, "pass", "--config", str(work / "nope.toml")) == 2


# --- the path the GitHub Action runs ----------------------------------------------------------


def test_action_pipeline_replay(pairwise_dir, tmp_path, monkeypatch):
    """judge (replay) -> validate -> gate against the committed baseline, as action.yml does."""
    monkeypatch.chdir(tmp_path)
    anchors = str(pairwise_dir / "anchors.jsonl")
    out = tmp_path / "out"
    assert main(["judge", anchors, "--runner", "replay", "--runs", "3",
                 "--fixture", str(pairwise_dir / "replay-agree.jsonl"),
                 "--out", str(out / "runs")]) == 0
    assert main(["validate", anchors, str(out / "runs"), "--out", str(out)]) == 0
    assert main(["gate", str(out / "report.json"),
                 "--baseline", str(pairwise_dir / "baseline.json")]) == 0
    assert json.loads((out / "gate.json").read_text(encoding="utf-8"))["status"] == "PASS"

    # The disagreeing replay fixture fails the absolute kappa threshold (kappa .5).
    bad = tmp_path / "bad"
    assert main(["judge", anchors, "--runner", "replay", "--runs", "3",
                 "--fixture", str(pairwise_dir / "runs" / "run-01.jsonl"),
                 "--out", str(bad / "runs")]) == 0
    assert main(["validate", anchors, str(bad / "runs"), "--out", str(bad)]) == 0
    assert main(["gate", str(bad / "report.json"),
                 "--baseline", str(pairwise_dir / "baseline.json")]) == 1


def test_gate_md_escapes_a_hostile_anchor_hash(work):
    """A hostile anchor hash in report.json adds no heading and no link to gate.md."""
    path = work / "pass" / "report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["anchors"]["sha256"] = "abc |\n\n# INJECTED HEADING\n\n[click](https://evil.example/x)"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert gate(work, "pass") == 0
    md = (work / "pass" / "gate.md").read_text(encoding="utf-8")
    assert not [line for line in md.splitlines() if line.startswith("#") and "INJECTED" in line]
    assert "[click](" not in md
