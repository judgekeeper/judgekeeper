import json

from judgekeeper.anchors import freeze
from judgekeeper.cli import main

PAIRWISE_PROMPT = """---
rubric_version: test-v1
---
{{input}} / {{output_a}} / {{output_b}}
"""


def test_usage_errors_exit_2(pairwise_dir, tmp_path):
    assert main(["validate", str(pairwise_dir / "anchors.jsonl")]) == 2
    assert main(["judge", str(pairwise_dir / "anchors.jsonl"), "--runner", "bogus"]) == 2
    assert main(["validate", str(tmp_path / "missing.jsonl"), str(pairwise_dir / "runs"),
                 "--out", str(tmp_path / "r")]) == 2


def test_validate_empty_runs_dir_exit_2(pairwise_dir, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["validate", str(pairwise_dir / "anchors.jsonl"), str(empty),
                 "--out", str(tmp_path / "r")]) == 2


def test_anchor_hash_mismatch_exit_3(pairwise_dir, tmp_path):
    anchors = pairwise_dir / "anchors.jsonl"
    anchors.write_text(anchors.read_text(
        encoding="utf-8").replace('"human_label": "A"', '"human_label": "B"', 1),
                       encoding="utf-8")
    out = tmp_path / "r"
    assert main(["validate", str(anchors), str(pairwise_dir / "runs"), "--out", str(out)]) == 3
    assert not (out / "report.json").exists()
    assert main(["judge", str(anchors), "--runner", "replay",
                 "--fixture", str(pairwise_dir / "runs" / "run-01.jsonl"),
                 "--out", str(tmp_path / "runs")]) == 3


def test_runs_recorded_against_other_anchors_exit_3(pairwise_dir, tmp_path):
    run = pairwise_dir / "runs" / "run-02.jsonl"
    lines = run.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    header["anchors_sha256"] = "0" * 64
    run.write_text("\n".join([json.dumps(header)] + lines[1:]) + "\n", encoding="utf-8")
    assert main(["validate", str(pairwise_dir / "anchors.jsonl"), str(pairwise_dir / "runs"),
                 "--out", str(tmp_path / "r")]) == 3


def test_mixed_judges_rejected(pairwise_dir, tmp_path):
    run = pairwise_dir / "runs" / "run-02.jsonl"
    run.write_text(run.read_text(encoding="utf-8").replace('"rubric_version": "pairwise-v1"',
                                           '"rubric_version": "pairwise-v2"'), encoding="utf-8")
    assert main(["validate", str(pairwise_dir / "anchors.jsonl"), str(pairwise_dir / "runs"),
                 "--out", str(tmp_path / "r")]) == 2


def test_judge_with_replay_then_validate(pairwise_dir, tmp_path):
    runs = tmp_path / "runs"
    code = main(["judge", str(pairwise_dir / "anchors.jsonl"), "--runner", "replay",
                 "--fixture", str(pairwise_dir / "runs" / "run-01.jsonl"),
                 "--runs", "2", "--out", str(runs)])
    assert code == 0
    files = sorted(p.name for p in runs.glob("*.jsonl"))
    assert files == ["run-01.jsonl", "run-02.jsonl"]
    lines = (runs / "run-01.jsonl").read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    assert header["type"] == "header"
    assert header["fingerprint"]["model"] == "claude-haiku-4-5-20251001"
    records = [json.loads(line) for line in lines[1:]]
    assert len(records) == 8
    # every judgment written to disk carries the fingerprint
    for rec in records:
        assert rec["fingerprint"]["prompt_hash"] == header["fingerprint"]["prompt_hash"]
        assert rec["fingerprint"]["created_at"]
    out = tmp_path / "report"
    assert main(["validate", str(pairwise_dir / "anchors.jsonl"), str(runs), "--out", str(out)]) == 0
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["noise_floor"]["items_flipped_fraction"] == 0.0


def test_judge_single_output_end_to_end(tmp_path):
    """Single-output anchors with the 'judge passes everything' degenerate replay."""
    anchors = tmp_path / "anchors.jsonl"
    items = [{"id": f"s{i}", "input": "q", "output": "o",
              "human_label": "pass" if i < 9 else "fail"} for i in range(10)]
    anchors.write_text("\n".join(json.dumps(i) for i in items) + "\n", encoding="utf-8")
    freeze(anchors)
    sha = json.loads((tmp_path / "anchors.manifest.json").read_text(encoding="utf-8"))["sha256"]
    fp = {"provider": "replay", "model": "m", "snapshot": "m", "prompt_hash": "h",
          "rubric_version": "single-v1", "temperature": 0.0, "created_at": "2026-10-01T00:00:00Z"}
    fixture = tmp_path / "fixture.jsonl"
    rows = [{"type": "header", "run": 1, "anchors_sha256": sha, "fingerprint": fp}]
    rows += [{"type": "judgment", "id": i["id"], "verdict": "pass", "raw_score": None,
              "rationale": "looks fine", "fingerprint": fp} for i in items]
    fixture.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    runs = tmp_path / "runs"
    assert main(["judge", str(anchors), "--runner", "replay", "--fixture", str(fixture),
                 "--out", str(runs)]) == 0
    out = tmp_path / "report"
    assert main(["validate", str(anchors), str(runs), "--out", str(out)]) == 0
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["position_bias"] is None
    assert report["headline"]["accuracy_mean"] == 0.9
    assert report["headline"]["kappa_mean"] == 0.0
    assert report["headline"]["tnr_mean"] == 0.0
    codes = {f["code"] for f in report["verdict"]["flags"]}
    assert "low_kappa" in codes and "single_run" in codes


def test_judge_anthropic_without_key_is_usage_error(pairwise_dir, tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    prompt = tmp_path / "p.md"
    prompt.write_text(PAIRWISE_PROMPT, encoding="utf-8")
    assert main(["judge", str(pairwise_dir / "anchors.jsonl"), "--runner", "anthropic",
                 "--model", "claude-haiku-4-5-20251001", "--prompt", str(prompt),
                 "--out", str(tmp_path / "runs")]) == 2


# --- terminal escape sequences from input files (security review, finding 7) --------------------

ESCAPES = "\x1b]0;PWNED-TITLE\x07\x1b[2J\x1b[H cleared\r\x9b31m\x7f"
CONTROL = [chr(c) for c in (*range(0x09), *range(0x0b, 0x20), *range(0x7f, 0xa0))]


def _no_control(*texts):
    for text in texts:
        assert not [c for c in CONTROL if c in text], repr(text)


def test_printable_strips_control_characters_but_keeps_newline_and_tab():
    from judgekeeper.redact import printable

    assert printable("a\x1b[31mb\tc\nd\re\x7f\x9b\x00f é") == "a[31mb\tc\ndef é"
    assert printable(ESCAPES) == "]0;PWNED-TITLE[2J[H cleared31m"


def _hostile_runs(pairwise_dir):
    for run in (pairwise_dir / "runs").glob("run-*.jsonl"):
        lines = run.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
        header["source"] = {"kind": "records", "file": None, "metric": None,
                            "warnings": [ESCAPES], "notes": [ESCAPES]}
        header["fingerprint"]["model"] = f"model{ESCAPES}"
        run.write_text("\n".join([json.dumps(header), *lines[1:]]) + "\n", encoding="utf-8")


def test_validate_prints_no_escape_sequence_from_a_run_header(pairwise_dir, tmp_path, capsys):
    _hostile_runs(pairwise_dir)
    out = tmp_path / "r"
    assert main(["validate", str(pairwise_dir / "anchors.jsonl"), str(pairwise_dir / "runs"),
                 "--out", str(out)]) == 0
    printed = capsys.readouterr()
    assert "PWNED-TITLE" in printed.out  # the flag is shown, as text
    _no_control(printed.out, printed.err)

    capsys.readouterr()
    assert main(["baseline", "set", str(out / "report.json"), "--path", str(tmp_path / "b.json")]) == 0
    assert main(["baseline", "show", "--path", str(tmp_path / "b.json")]) == 0
    assert main(["gate", str(out / "report.json")]) in (0, 1, 4)
    printed = capsys.readouterr()
    assert "PWNED-TITLE" in printed.out
    _no_control(printed.out, printed.err)


def test_import_prints_no_escape_sequence_in_warnings_and_notes(pairwise_dir, tmp_path, capsys,
                                                                monkeypatch):
    from judgekeeper import readers
    from judgekeeper.report import build_report

    _hostile_runs(pairwise_dir)
    report = build_report(pairwise_dir / "anchors.jsonl", pairwise_dir / "runs")
    monkeypatch.setattr(readers, "import_results", lambda *a, **kw: report)
    assert main(["import", "records", "x.jsonl", "--out", str(tmp_path / "o")]) == 0
    printed = capsys.readouterr()
    assert "warning: ]0;PWNED-TITLE" in printed.err and "note: ]0;PWNED-TITLE" in printed.out
    _no_control(printed.out, printed.err)


def test_error_messages_print_no_escape_sequence(tmp_path, capsys):
    table = tmp_path / "t.csv"
    table.write_text(f'"id{ESCAPES}",verdict\na,pass\n', encoding="utf-8")
    assert main(["check", str(table), "--out", str(tmp_path / "o")]) == 2
    printed = capsys.readouterr()
    assert "PWNED-TITLE" in printed.err
    _no_control(printed.out, printed.err)


def test_ctrl_c_stops_with_one_line_and_no_traceback(monkeypatch, capsys):
    from judgekeeper import cli

    def stopped(args):
        raise KeyboardInterrupt

    monkeypatch.setitem(cli.COMMANDS, "start", stopped)
    assert main(["start"]) == 130
    out = capsys.readouterr()
    assert "Traceback" not in out.out + out.err
    assert out.out == "\nStopped.\n"

