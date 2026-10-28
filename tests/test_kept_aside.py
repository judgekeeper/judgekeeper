"""What `fix` says on simulated new rules (scripts/kept_aside_check.py runs it in full): the
committed report is the script's own, and the README, the site and the reference say only
what it shows."""

from __future__ import annotations

import importlib.util
import json
import random
import re
from pathlib import Path

from judgekeeper import fix

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "kept_aside_check.py"
FOLDER = ROOT / "docs" / "examples" / "kept-aside"
LINK = "docs/examples/kept-aside/report.md"


def _module():
    spec = importlib.util.spec_from_file_location("kept_aside_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result() -> dict:
    return json.loads((FOLDER / "results.json").read_text(encoding="utf-8"))


def _flat(text: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", "", text).split())


def test_the_report_is_the_scripts_own_on_the_committed_grid():
    module, result = _module(), _result()
    assert (FOLDER / "report.md").read_text(encoding="utf-8") == module.markdown(result)
    assert result["cases"] == module.CASES >= 20_000
    assert (result["hidden_tenths"], result["min_each"]) == (fix.HIDDEN_TENTHS, fix.MIN_EACH)
    assert re.fullmatch(r"[0-9a-f]{7,}", result["commit"]), result["commit"]
    grid = {(r["marks"], r["agree"], r["rule"]) for r in result["rows"]}
    assert grid == {(m, a, rule) for m in module.MARKS for a in module.AGREE
                    for rule in module.rules()}
    assert result["needed"] == module.needed(result["rows"])
    assert result["summary"] == module.summary(result["rows"])
    line = next(x for x in (ROOT / "docs" / "examples" / "README.md").read_text(
        encoding="utf-8").splitlines() if x.startswith("- **`kept-aside/`**"))
    assert f"`{result['commit']}`" in line


def test_a_case_goes_through_fixs_own_split_and_verdict():
    module = _module()
    for marks in (30, 80):
        rng = random.Random(marks)
        kind, kept = module.one_case(marks, 0.8, 0.5, 0.03, rng)
        assert kind in module.KINDS
        assert marks // 2 <= kept <= marks // 2 + 4  # half of each cell, rounded up
    # a rule that fixes every mistake kept aside and breaks none, on a clearly wrong rule
    assert module.one_case(80, 0.6, 1.0, 0.0, random.Random(1))[0] == "better"
    assert module.one_case(80, 0.9, 0.0, 1.0, random.Random(1))[0] == "worse"


def test_the_readme_the_site_and_the_reference_say_what_the_report_shows():
    result = _result()
    quarter, s = result["summary"]["quarter"], result["summary"]
    large = s["large"]
    n = quarter["marks"]
    # "for a rule that fixes about a quarter ... about N marks, usually safe to try, not better"
    assert quarter["rule"] == "fixes 25%, breaks 2%" and n is not None
    assert quarter["safe"][0] > 50 and quarter["better"][1] < quarter["safe"][0]
    # "a large fix of a clearly wrong rule (about 9 in 10 of its mistakes fixed) usually comes
    # out better with N marks"
    assert large["marks"] == n and large["rule"] == "fixes 90%, breaks 2%"
    assert large["agree"] < 0.8 and large["better"] > 50
    claim = (f"A rule that fixes about a quarter of its mistakes needs about {n} marks for a "
             f"clear answer, and usually reads \"safe to try\"")
    readme = _flat((ROOT / "README.md").read_text(encoding="utf-8"))
    site = _flat((ROOT / "website" / "start.html").read_text(encoding="utf-8")).replace("’", "'")
    assert claim in readme
    assert claim.replace('"', "") in site
    for page in ("README.md", "website/start.html"):
        assert LINK in (ROOT / page).read_text(encoding="utf-8"), page
    need = result["needed"]
    reference = _flat((ROOT / "docs" / "reference.md").read_text(encoding="utf-8"))
    assert "examples/kept-aside/report.md" in reference
    assert (f"gets a clear answer most of the time from about {n} marks, mostly \"Safe to "
            f"try\"; one that fixes almost all of them, from about "
            f"{need['fixes 90%, breaks 2%']['marks']}; one that fixes 1 in 10 and breaks 5 in "
            f"100 right answers, more than {_module().MARKS[-1]}") in reference
    assert need["fixes 10%, breaks 5%"]["marks"] is None
    # "by mistake is rare but not zero ... only for rules close to no change"
    assert "by mistake is rare but not zero, and happens only for rules close to no change" \
        in reference
    assert 0 < max(s["false_better"], s["false_worse"]) <= 0.5 and s["false_within"] <= 6
    for page in (readme, site, reference):
        assert not re.search(r"never (?:called|reads?|says?) \W?(?:better|safe)", page,
                             re.IGNORECASE)
    # "a worse rule often reads can't tell yet, and now and then safe to try"
    worse = s["worse_at_most"]
    assert worse["cant"][0] > 50 and 0 < worse["safe"][1] < 10


def test_the_marks_a_new_set_needs_come_from_the_report():
    """`fix` asks for about CLEAR new marks for a new set kept aside: the marks kept aside where
    a rule that fixes a quarter of the mistakes first gets a clear answer, rounded to 10. The
    reference links the report; the line on screen stays plain."""
    result = _result()
    quarter = result["summary"]["quarter"]
    kept = [r["kept_aside"] for r in result["rows"]
            if (r["rule"], r["marks"]) == (quarter["rule"], quarter["marks"])]
    assert kept and all(round(k, -1) == fix.CLEAR for k in kept), kept
    reference = _flat((ROOT / "docs" / "reference.md").read_text(encoding="utf-8"))
    report = "(examples/kept-aside/report.md)"
    assert f"Mark [about {fix.CLEAR} more answers for a clear answer]{report}" in reference
    assert f"[about {fix.CLEAR} for a clear answer]{report}" in reference
    assert "](" not in fix.CLEAR_LINE and "kept-aside" not in fix.CLEAR_LINE
