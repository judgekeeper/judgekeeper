"""`judgekeeper import records FILE --check`: say what judgekeeper reads in a records file,
without writing a report. Exit 0 when the file is usable, 2 when it is not.

It prints the number of records, the pass/fail split per judge, the first 3 records in plain
words, the fields it kept without knowing them, and every problem with its line number.
"""

import json
import re
from pathlib import Path

import pytest

from judgekeeper.cli import main

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "docs" / "examples" / "records"


def write_jsonl(path, rows):
    path.write_text("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows),
                    encoding="utf-8")
    return path


def check(capsys, *argv):
    code = main(["import", "records", *map(str, argv), "--check"])
    out, err = capsys.readouterr()
    return code, out + err


def judged(i, label, name="Safe wording", **extra):
    return {"name": name, "input": f"Question {i}?", "output": f"Answer {i}.", "label": label,
            **extra}


@pytest.mark.parametrize("name", ["minimal.jsonl", "full.jsonl", "with-human-labels.jsonl"])
def test_every_example_file_is_usable(capsys, name):
    code, out = check(capsys, EXAMPLES / name)
    assert code == 0, out
    assert "judgekeeper can read this file." in out
    assert not re.search(r"^\s+\d+ problems?:", out, re.MULTILINE)


def test_the_minimal_example_has_four_fields_per_line():
    lines = (EXAMPLES / "minimal.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines and all(len(json.loads(line)) == 4 for line in lines)


def test_the_full_example_uses_every_field():
    rows = [json.loads(line) for line in
            (EXAMPLES / "full.jsonl").read_text(encoding="utf-8").splitlines()]
    used = {k for r in rows for k in r}
    for name in ("schema_version", "target_id", "name", "annotator_kind", "label", "score",
                 "explanation", "run", "input", "output", "evaluator", "created_at",
                 "metadata", "trajectory", "outcome", "app_version"):
        assert name in used, name
    assert any("rule" in (r.get("evaluator") or {}) for r in rows)


def test_the_human_label_example_holds_human_labels():
    rows = [json.loads(line) for line in
            (EXAMPLES / "with-human-labels.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(r.get("annotator_kind") == "HUMAN" for r in rows)


def test_counts_and_the_split_per_judge(tmp_path, capsys):
    rows = [judged(1, "pass"), judged(2, "pass"), judged(3, "pass"), judged(4, "fail"),
            judged(5, "pass", name="Kind tone"), judged(6, "pass", name="Kind tone"),
            {**judged(1, "pass"), "annotator_kind": "HUMAN"}]
    code, out = check(capsys, write_jsonl(tmp_path / "r.jsonl", rows))
    assert code == 0
    assert "7 records, records format version 1." in out
    assert 'Judge "Safe wording": 3 pass, 1 fail.' in out
    assert 'Judge "Kind tone": 2 pass, 0 fail.' in out
    assert "Human labels: 1 (1 pass, 0 fail)." in out


def test_the_first_three_records_in_plain_words(tmp_path, capsys):
    rows = [judged(i, "pass", explanation=f"Reason {i}.") for i in range(1, 6)]
    rows[1]["score"] = 0.9
    code, out = check(capsys, write_jsonl(tmp_path / "r.jsonl", rows))
    assert code == 0
    assert "The first 3 records:" in out
    assert "line 1: Safe wording said pass." in out
    assert "line 2: Safe wording said pass (score 0.9)." in out
    assert "Input: Question 1?" in out and "Output: Answer 1." in out
    assert "Reason: Reason 1." in out
    assert "Question 4?" not in out


def test_agent_fields_are_described_in_plain_words(tmp_path, capsys):
    steps = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
    rows = [judged(1, "pass", trajectory=steps, app_version="2.3",
                   outcome={"passed": True, "source": "unit tests"})]
    code, out = check(capsys, write_jsonl(tmp_path / "r.jsonl", rows))
    assert code == 0
    assert "2 agent steps" in out
    assert "unit tests: passed" in out
    assert "app version 2.3" in out


def test_every_problem_is_listed_with_its_line(tmp_path, capsys):
    rows = [judged(1, "pass"), {**judged(2, "pass"), "score": "high"}, "not json",
            "[1, 2]", judged(5, "fail"), {**judged(6, "pass"), "outcome": {"passed": "yes"}}]
    code, out = check(capsys, write_jsonl(tmp_path / "r.jsonl", rows))
    assert code == 2
    assert "4 problems:" in out
    assert "line 2: score 'high' is not a number" in out
    assert "line 3: not valid JSON" in out
    assert "line 4: each line must be a JSON object" in out
    assert "line 6: outcome" in out
    assert "judgekeeper cannot read this file until these are fixed." in out


def test_problems_in_a_csv_name_their_line(tmp_path, capsys):
    path = tmp_path / "r.csv"
    path.write_text("name,input,output,label,score\nj,q1,a1,pass,0.9\nj,q2,a2,,high\n",
                    encoding="utf-8")
    code, out = check(capsys, path)
    assert code == 2
    assert "line 3: score 'high' is not a number" in out


def test_fields_it_does_not_know_are_kept_and_named(tmp_path, capsys):
    rows = [judged(1, "pass"), {**judged(2, "fail"), "colour": "blue"}]
    code, out = check(capsys, write_jsonl(tmp_path / "r.jsonl", rows))
    assert code == 0
    assert "Kept 1 field judgekeeper does not know: colour (line 2)." in out


def test_a_newer_version_is_read_with_one_warning(tmp_path, capsys):
    rows = [{**judged(i, "pass" if i % 2 else "fail"), "schema_version": 3,
             "judge_cost": {"usd": 0.01}} for i in range(1, 5)]
    code, out = check(capsys, write_jsonl(tmp_path / "v3.jsonl", rows))
    assert code == 0
    assert out.count("version 3") == 2  # the count line and the one warning
    assert "update judgekeeper" in out.lower()
    assert "judge_cost" in out


def test_scores_without_a_pass_mark_need_pass_if(tmp_path, capsys):
    rows = [{"name": "j", "input": f"q{i}", "output": "a", "score": s}
            for i, s in enumerate((0.9, 0.2, 0.7))]
    path = write_jsonl(tmp_path / "r.jsonl", rows)
    code, out = check(capsys, path)
    assert code == 2
    assert "3 scores with no pass mark" in out and "--pass-if" in out
    code, out = check(capsys, path, "--pass-if", "score>=0.5")
    assert code == 0
    assert 'Judge "j": 2 pass, 1 fail.' in out


def test_no_judge_records_is_not_usable(tmp_path, capsys):
    rows = [{**judged(1, "pass"), "annotator_kind": "HUMAN"}]
    code, out = check(capsys, write_jsonl(tmp_path / "r.jsonl", rows))
    assert code == 2
    assert "no judge records" in out


def test_an_empty_file_is_not_usable(tmp_path, capsys):
    path = tmp_path / "r.jsonl"
    path.write_text("\n", encoding="utf-8")
    code, out = check(capsys, path)
    assert code == 2
    assert "0 records" in out


def test_check_writes_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = write_jsonl(tmp_path / "r.jsonl", [judged(1, "pass"), judged(2, "fail")])
    before = set(tmp_path.iterdir())
    code, _ = check(capsys, path)
    assert code == 0
    assert set(tmp_path.iterdir()) == before


def test_check_works_with_map(tmp_path, capsys):
    path = tmp_path / "r.csv"
    path.write_text("metric,question,answer,value\nj,q1,a1,pass\nj,q2,a2,fail\n",
                    encoding="utf-8")
    code, out = check(capsys, path, "--map", "name=metric,input=question,output=answer,"
                                             "label=value")
    assert code == 0
    assert 'Judge "j": 1 pass, 1 fail.' in out


def test_check_is_for_records_only(tmp_path, capsys):
    path = write_jsonl(tmp_path / "r.jsonl", [judged(1, "pass")])
    assert main(["import", "promptfoo", str(path), "--check"]) == 2
    assert "--check" in capsys.readouterr().err


def test_what_is_printed_is_scrubbed(tmp_path, capsys):
    secret = "sk-" + "a1b2c3d4" * 4
    rows = [judged(1, "pass", explanation=f"used {secret}"), judged(2, "fail")]
    code, out = check(capsys, write_jsonl(tmp_path / "r.jsonl", rows))
    assert code == 0
    assert secret not in out


# The pass mark, the judge's model and the ids, per judge -------------------------------------

def test_each_judge_says_its_pass_mark_model_and_ids(tmp_path, capsys):
    rows = [judged(i, "pass" if i % 2 else "fail", target_id=f"q0{i}A", score=0.6 + i / 10,
                   metadata={"pass_mark": 0.7}, evaluator={"model": "claude-haiku-4-5"})
            for i in range(1, 5)]
    code, out = check(capsys, write_jsonl(tmp_path / "r.jsonl", rows))
    assert code == 0
    assert ("    Pass mark: 0.7. Judge's model: claude-haiku-4-5. Ids: 4 unique (q01A, q02A, "
            "q03A, …).") in out
    assert "line 1 (id q01A): Safe wording said pass (score 0.7, pass mark 0.7)." in out


def test_no_ids_no_model_and_verdicts_without_a_pass_mark(tmp_path, capsys):
    rows = [judged(i, "pass") for i in range(1, 4)]
    code, out = check(capsys, write_jsonl(tmp_path / "r.jsonl", rows))
    assert code == 0
    assert ("    Pass mark: none (the verdicts are pass or fail). Judge's model: not in the "
            "records. Ids: none (judgekeeper makes one from each input and output).") in out


def test_repeated_ids_and_several_pass_marks(tmp_path, capsys):
    rows = [judged(1, "pass", target_id="a", metadata={"pass_mark": 0.5}),
            judged(2, "pass", target_id="a", metadata={"pass_mark": 0.7}),
            judged(3, "fail", target_id="b", evaluator={"model": "m1"}),
            judged(4, "fail", evaluator={"model": "m2"})]
    code, out = check(capsys, write_jsonl(tmp_path / "r.jsonl", rows))
    assert code == 0
    assert ("    Pass marks: 0.5 and 0.7. Judge's models: m1 and m2. Ids: 2 unique in 3 "
            "records with an id (a, b).") in out


def test_several_files_say_how_start_reads_them(tmp_path, capsys):
    folder = tmp_path / "records"
    folder.mkdir()
    write_jsonl(folder / "Safe-wording-2026-10-06-925.jsonl", [judged(1, "pass")])
    write_jsonl(folder / "Safe-wording-2026-10-06-930.jsonl", [judged(1, "fail")])
    code, out = check(capsys, folder)
    assert code == 0
    assert out.rstrip().endswith(
        "judgekeeper start reads the files of the same judge together, as one set: an answer "
        "saved in more than one file counts once, with the verdict from the newest file.")


def test_one_file_says_nothing_about_several(tmp_path, capsys):
    _, out = check(capsys, write_jsonl(tmp_path / "r.jsonl", [judged(1, "pass")]))
    assert "as one set" not in out
