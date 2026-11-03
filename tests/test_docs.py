"""The README and the docs folder: what each holds, in plain words. The README's numbers come
from the committed reports in docs/examples/.
"""

from __future__ import annotations

import importlib.util
import re

import pytest

from tests.website_pages import ROOT

README = ROOT / "README.md"
STEPS = (("Find", "`judgekeeper`"), ("Mark", "a page opens in your browser"),
         ("Measure", "`judgekeeper`"), ("Fix", "`judgekeeper fix`"),
         ("Re-check", "`judgekeeper check <new results file>`"))


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _sections(text: str) -> dict[str, str]:
    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    return {part.splitlines()[0].strip(): part for part in parts[1:]}


def _flat(text: str) -> str:
    return " ".join(text.split())


# The README --------------------------------------------------------------------------------

def test_the_readme_is_short_and_in_order():
    text = _readme()
    assert text.startswith('<div align="center">\n  <img ')  # one centered header block
    body = text.split("\n</div>\n", 1)[1]
    assert len(body.splitlines()) < 61  # the text under the header stays short
    top = text[:text.index("\n## ")]
    for needed in ("<strong>Check your LLM-as-a-judge in 5 steps.</strong>",
                   "Find. Mark. Measure. Fix. Re-check.", "docs/assets/demo.webp"):
        assert needed in top, needed
    assert (ROOT / "docs" / "assets" / "demo.webp").stat().st_size < 1_000_000
    heads = list(_sections(text))
    wanted = ["Install", "The 5 steps", "The numbers", "Checked on public data",
              "More", "License"]
    assert [h for h in heads if h in wanted] == wanted


def test_the_readme_has_each_step_with_its_command():
    steps = _sections(_readme())["The 5 steps"]
    for n, (step, command) in enumerate(STEPS, 1):
        line = next(x for x in steps.splitlines() if x.startswith(f"{n}. **{step}:**"))
        assert command in line, step


EXAMPLES = "https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/"


def test_the_readme_numbers_are_in_the_reports_they_link():
    """Each public-data line links its report, and every % and decimal on the line is in it."""
    lines = [x for x in _sections(_readme())["Checked on public data"].splitlines()
             if x.startswith("- ")]
    linked = {}
    for line in lines:
        found = re.findall(rf"\]\({re.escape(EXAMPLES)}([\w./-]+)\)", line)
        if not found:
            continue
        reports = "\n".join((ROOT / "docs" / "examples" / f).read_text(encoding="utf-8")
                            for f in found)
        for figure in re.findall(r"\d+\.\d+|\d+%", line):
            assert figure in reports, (found, figure)
        linked[found[0]] = line
    assert sorted(linked) == ["coverage/coverage.md", "jailbreakbench-setups/report.md",
                              "jailbreakbench/report.md", "probes/report.md", "ragtruth-qa/report.md",
                              "ragtruth/report.md"]
    import json

    draws = (ROOT / "docs" / "examples" / "jailbreakbench" / "hundred-marks" / "draws.csv")
    summary = json.loads(draws.with_name("summary.json").read_text(encoding="utf-8"))
    n, each = summary["draws"], summary["inside_each"]
    jbb = next(x for x in _sections((ROOT / "docs" / "reference.md").read_text(
        encoding="utf-8"))["Checked on public data"].splitlines() if x.startswith("- **JailbreakBench"))
    assert f"In {n} tests with {summary['marks_per_draw']} marks each" in jbb
    assert (f"TPR in {each['tpr']}, the true TNR in {each['tnr']} and the true kappa in "
            f"{each['kappa']}; all three at once in {summary['all_three_inside']}") in jbb
    rows = [x.split(",") for x in draws.read_text(encoding="utf-8").splitlines()
            if re.match(r"d\d", x)]
    assert len(rows) == n == 100 and {r[4] for r in rows} == {"100"}  # marks_counted
    assert summary["rows"] == 300 and summary["every_draw_counted_its_marks_and_showed_no_text"]
    assert "needs work" in linked["ragtruth/report.md"]
    for gone in ("LLMBar", "MT-Bench", "real-data-check"):
        assert gone not in _readme(), gone


def test_the_jailbreakbench_counts_are_in_draw_counts():
    """report.md's counts of what each draw showed are in hundred-marks/draw-counts.csv, which
    agrees with draws.csv on every draw's seed and disagreements."""
    import csv

    folder = ROOT / "docs" / "examples" / "jailbreakbench"
    md = " ".join((folder / "report.md").read_text(encoding="utf-8").split())

    def rows(name: str) -> dict[str, dict]:
        with (folder / "hundred-marks" / name).open(encoding="utf-8", newline="") as f:
            return {r["draw"]: r for r in csv.DictReader(x for x in f if not x.startswith("#"))}

    counts, draws = rows("draw-counts.csv"), rows("draws.csv")
    assert sorted(counts) == sorted(draws) and len(counts) == 100
    for d, r in counts.items():
        c = {k: int(v) for k, v in r.items() if k != "draw"}
        assert c["seed"] == int(draws[d]["seed"]), d
        assert c["judge_pass_experts_fail"] + c["judge_fail_experts_pass"] == int(
            draws[d]["disagreements"]), d
        assert c["shown_judge_pass"] == c["judge_pass_experts_pass"] + c["judge_pass_experts_fail"]
        assert c["shown_judge_fail"] == c["judge_fail_experts_pass"] + c["judge_fail_experts_fail"]
    assert {r["shown_judge_pass"] for r in counts.values()} == {"58", "59"}
    assert {r["shown_judge_fail"] for r in counts.values()} == {"41", "42"}
    assert "held 58 or 59 answers the LLM-as-a-judge passed and 41 or 42 it failed" in md
    assert (counts["d060"]["judge_fail_experts_pass"], counts["d060"]["shown_judge_fail"]) == (
        "12", "41") and "In d060, 12 of the 41 answers GPT-4 failed" in md
    assert (counts["d065"]["judge_fail_experts_pass"], counts["d065"]["shown_judge_fail"]) == (
        "11", "41") and "in d065, 11 of 41" in md
    assert (counts["d071"]["judge_pass_experts_fail"], counts["d071"]["shown_judge_pass"]) == (
        "0", "59") and "The 59 answers GPT-4 passed that it showed held none of the 10" in md
    assert "`hundred-marks/draw-counts.csv`" in md


def _table(md: str, heading: str) -> list[dict[str, str]]:
    """The first table under `heading` in a Markdown report, one dict per row."""
    lines = md.split(f"\n{heading}\n", 1)[1].splitlines()
    rows = lines[next(i for i, x in enumerate(lines) if x.startswith("|")):]
    rows = rows[:next((i for i, x in enumerate(rows) if not x.startswith("|")), len(rows))]
    cells = [[c.strip() for c in x.strip("|").split("|")] for x in rows]
    return [dict(zip(cells[0], row, strict=True)) for row in cells[2:]]


def test_the_readme_says_where_its_coverage_figures_are():
    """The Simulation line's average is the chosen level's "Average" in the report's first
    table, and its lowest is the lowest TPR or TNR at 15 + 15 in "The real stopping rule":
    both read from the report and from coverage.json, so they can't drift apart."""
    import json

    folder = ROOT / "docs" / "examples" / "coverage"
    md = (folder / "coverage.md").read_text(encoding="utf-8")
    grid = json.loads((folder / "coverage.json").read_text(encoding="utf-8"))
    level = grid["corrected"]["chosen_level"]
    chosen = f"{level * 100:.0f}%"
    first = _table(md, "## `judgekeeper`: the level")
    average = next(r["Average"] for r in first if r["Level"] == chosen)
    assert average == f"{grid['corrected']['levels'][str(level)]['mean'] * 100:.1f}"
    stopping = _table(md, "### The real stopping rule")
    lowest = min((r[k] for r in stopping if r["stop"] == "15 + 15" for k in ("TPR", "TNR")),
                 key=float)
    from_json = min(r["coverage"][k] for r in grid["accuracy"]["stopping"] if r["each"] == 15
                    for k in ("tpr", "tnr"))
    assert lowest == f"{from_json * 100:.1f}"
    line = next(x for x in _readme().splitlines() if x.startswith("- [Simulation]"))
    assert f"held the true value {average} times in 100 on average" in line
    assert "never fewer" not in line
    # the reference quotes the average and says where the lowest are
    reference = _flat((ROOT / "docs" / "reference.md").read_text(encoding="utf-8"))
    again = min(grid["batches"]["general"]["per_metric"].values())
    assert (f"{average} times in 100 on average (the report's first table). The lowest, "
            f"{again * 100:.1f}, is after grading again with 10 marks in each group, in batches "
            "(table \"Batches\"). Before grading again, the lowest is "
            f"{lowest}, when marking stops as early as it can: 15 of your Passes, 15 of "
            "your Fails, and 20 marks on answers your LLM-as-a-judge passed and 20 on "
            "answers it failed (table \"The real stopping rule\").") in reference


def test_the_readme_keeps_to_the_agreed_words():
    text = _readme()
    assert "(https://www.judgekeeper.com)" in text
    for word in (r"luck(y)?", r"chance", r"integrates? with", r"rough(ly)?",
                 r"AI judges?", r"trusted", r"proven", r"judgekeeper start"):
        assert not re.search(rf"\b{word}\b", text, re.IGNORECASE), word


def test_the_guide_and_the_tool_pages_are_gone_and_nothing_links_them():
    assert not (ROOT / "docs" / "guide.md").exists()
    assert not (ROOT / "docs" / "integrations").exists()
    sources = [README, ROOT / "SECURITY.md", ROOT / "pyproject.toml",
               *(ROOT / "docs").glob("*.md"), *(ROOT / ".github").rglob("*.*"),
               *(ROOT / "src").rglob("*.py")]
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for gone in ("guide.md", "docs/integrations"):
            assert gone not in text, (path.relative_to(ROOT).as_posix(), gone)


def test_checking_names_the_llm_as_a_judge_in_full():
    """"Judge" alone can read like a court judge, so checking it names the LLM-as-a-judge."""
    sources = [README, *(ROOT / "docs").glob("*.md"), *(ROOT / "src").rglob("*.py")]
    for path in sources:
        text = _flat(path.read_text(encoding="utf-8")).lower()
        for words in ("check your judge", "checks your judge", "check a judge"):
            assert words not in text, (path.relative_to(ROOT).as_posix(), words)


def test_the_readme_has_three_badges_version_tests_and_licence():
    badges = re.findall(r'<img src="([^"]+)" alt="([^"]+)">', README.read_text(encoding="utf-8"))
    assert [alt for src, alt in badges if "shields.io" in src or "badge.svg" in src] == [
        "PyPI version", "Tests", "Apache-2.0 license"]


def test_the_reference_numbers_for_the_credit_runs_are_in_the_reports_they_link():
    """Each public-data bullet of the reference that links a report: every % on it is in the
    reports it links (the ones with several links, in any of them)."""
    section = _sections((ROOT / "docs" / "reference.md").read_text(
        encoding="utf-8"))["Checked on public data"]
    checked = 0
    for bullet in (x for x in section.splitlines() if x.startswith("- **")):
        found = re.findall(r"\]\(examples/([\w./-]+)\)", bullet)
        if not found:
            continue
        reports = "\n".join((ROOT / "docs" / "examples" / f).read_text(encoding="utf-8")
                            for f in found)
        for figure in re.findall(r"\d+\.\d+%|\d+%", bullet):
            assert figure in reports, (found, figure)
        checked += 1
    assert checked >= 6


# The demo ------------------------------------------------------------------------------------

OUTLINE = (38, 42, 48)  # the window's 1 pixel outline (#262a30)


def _demo_frames():
    Image = pytest.importorskip("PIL.Image")
    np = pytest.importorskip("numpy")
    demo = Image.open(ROOT / "docs" / "assets" / "demo.webp")
    for n in range(demo.n_frames):
        demo.seek(n)
        yield n, np.array(demo.convert("RGB")).astype(int)


def test_every_demo_frame_has_the_window_outline_on_all_four_sides():
    for n, frame in _demo_frames():
        for side, edge in (("left", frame[:, 0]), ("right", frame[:, -1]),
                           ("top", frame[0]), ("bottom", frame[-1])):
            assert abs(edge - OUTLINE).max() <= 12, f"frame {n}: no outline on the {side}"


def test_the_marking_page_in_the_demo_has_the_same_margin_on_both_sides():
    """In the header band of a frame showing the marking page, the first ink is as far from the
    left as the last ink is from the right (the page is laid out wide, then scaled)."""
    seen = 0
    for n, frame in _demo_frames():
        band = frame[50:100, 3:997]
        ink = abs(band - (11, 12, 14)).sum(axis=2) > 60
        columns = ink.any(axis=0).nonzero()[0]
        left, right = columns.min() + 3, 997 - (columns.max() + 3)
        if right > 100:  # a terminal frame: its text is not the page's header
            continue
        seen += 1
        assert abs(left - right) <= 3, f"frame {n}: {left} px on the left, {right} on the right"
    assert seen >= 10


def test_the_demo_script_checks_the_outline_of_every_frame():
    pytest.importorskip("termios")  # the script drives a pseudo-terminal: macOS and Linux only
    Image = pytest.importorskip("PIL.Image")
    spec = importlib.util.spec_from_file_location("make_demo_for_test",
                                                  ROOT / "scripts" / "make_demo.py")
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))  # make_demo imports make_site_shots
    try:
        make_demo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(make_demo)
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    whole = Image.new("RGB", (40, 30), "#07080a")
    for x in range(40):
        whole.putpixel((x, 0), OUTLINE)
        whole.putpixel((x, 29), OUTLINE)
    for y in range(30):
        whole.putpixel((0, y), OUTLINE)
        whole.putpixel((39, y), OUTLINE)
    make_demo.check_outline(whole)  # all four sides: no error
    whole.putpixel((39, 12), (7, 8, 10))  # a gap in the right side
    with pytest.raises(SystemExit, match="missing on the right"):
        make_demo.check_outline(whole)


def test_no_ghost_of_the_first_time_card_stays_in_the_marking_page_frames():
    """The card (centred over the answer area) is shown in the first marking frames, then it is
    gone: from then on the part of the answer area below any answer text (the card's second
    headline line and its button, rows 358 to 455) is the page's background, to within 4 levels."""
    background = (11, 12, 14)
    states = []
    for n, frame in _demo_frames():
        header = frame[50:100, 3:997]
        columns = (abs(header - background).sum(axis=2) > 60).any(axis=0).nonzero()[0]
        if 997 - (columns.max() + 3) > 100:  # a terminal frame
            continue
        worst = abs(frame[358:455, 330:680] - background).max()
        states.append("card" if worst > 100 else "clean" if worst <= 4 else f"ghost {worst} (frame {n})")
    assert states and states[0] == "card", states
    assert 1 <= states.count("card") <= 4 and set(states) <= {"card", "clean"}, states
    assert states == sorted(states, key=lambda state: state != "card"), states  # card, then none


# Lines the README and the Guide keep -----------------------------------------------------------

def _step(n: int) -> str:
    """Step n's line, with the short lines indented under it."""
    lines = _sections(_readme())["The 5 steps"].splitlines()
    at = next(i for i, x in enumerate(lines) if x.startswith(f"{n}. "))
    under = []
    for x in lines[at + 1:]:
        if not x.startswith("   - "):
            break
        under.append(x.strip())
    return " ".join([lines[at], *under])


def _guide(wanted: str) -> str:
    from tests.website_pages import WEBSITE, parse

    root = parse(WEBSITE / "start.html")
    (el,) = [e for e in root.iter() if e.attrs.get("id") == wanted]
    return " ".join(el.text().replace("’", "'").split())


STEADY = ("Now and then an answer you marked comes back once, to see how steady your marks "
          "are. Mark it as you see it.")


def test_the_mark_step_keeps_two_sentences_and_short_lines_under_it():
    lines = _sections(_readme())["The 5 steps"].splitlines()
    at = next(i for i, x in enumerate(lines) if x.startswith("2. "))
    assert lines[at].startswith("2. **Mark:** a page opens in your browser. Mark answers Pass or "
                                "Fail; the LLM-as-a-judge's grade stays hidden.")
    under = lines[at + 1:at + 4]
    assert [x[:5] for x in under] == ["   - "] * 3
    assert STEADY in under[0] and NO_BROWSER in under[1] and "--labels" in under[2]


def test_the_mark_step_says_a_marked_answer_comes_back():
    """About 1 in 20 answers comes back once, so the person's own steadiness can be seen."""
    assert STEADY in _step(2)
    assert STEADY in _guide("step-mark")


NO_BROWSER = ("No browser here, or a coding agent runs it? `judgekeeper --no-browser` prints the "
              "link to open instead.")


def test_the_readme_says_how_to_get_the_link_and_what_the_result_notes():
    """--no-browser prints the link; marks made through a link printed with no terminal (a
    coding agent read it) get a note on the result, in the words the result uses."""
    from judgekeeper.start_label import link_lines

    assert NO_BROWSER in _step(2)
    install = _flat(_sections(_readme())["Install"])
    (note,) = link_lines({"printed": 2})
    said = ("The result will say your marks came through a link the agent printed. If you "
            "marked them yourself, you can ignore that.")
    assert said in install
    assert "came through a link printed with no terminal" in note
    assert "If you marked them yourself, nothing to do." in note


def test_the_readme_says_kappa_never_decides():
    """The result comes from the TPR and TNR ranges only (targets.level); kappa is under
    More details on the result page and in report.html."""
    import inspect

    from judgekeeper import report_page, targets

    assert "kappa" not in inspect.getsource(targets.level).lower()
    assert '<h2 id="details-h">More details</h2>' in inspect.getsource(report_page)
    kappa = next(x for x in _sections(_readme())["The numbers"].splitlines()
                 if x.startswith("- **Kappa:**"))
    assert ('it is under "More details" on the result page and in report.html, and never '
            "decides the result (TPR and TNR do).") in kappa


def test_the_fix_step_is_a_loop_and_cant_tell_yet_is_normal():
    from judgekeeper import fix

    step = _step(4)
    assert ("It is a loop: change the rule (with promptfoo, usually in "
            "`.judgekeeper/fix/regrade.yaml`; when it can't write one, `fix` says how), grade "
            "again, then run `judgekeeper fix <new results file>`.") in step
    assert ("with promptfoo, usually `.judgekeeper/fix/regrade.yaml`), then run "
            "`judgekeeper check <new results file>`.") in _step(5)
    assert "With few marks, \"can't tell yet\" is a normal answer." in step
    assert "Result: can't tell yet." in fix.RESULT["same"]


def test_each_recheck_step_says_new_marks_count_once_every_answer_is_graded():
    """Grading only the marked answers again compares on them; a mark made later waits until
    every answer is graded, in the words `check` uses (check.WAIT_NEXT): said the same way in
    the README, the guide and eval-tools.md."""
    from judgekeeper import check

    grade_all = check.WAIT_NEXT.split(", then ")[0]  # "grade all your answers with ..."
    said = (f"Grading only your marked answers is enough to compare the two. To count new marks, "
            f"{grade_all}.")
    assert said in _step(5)
    assert said in _guide("step-check")
    assert said in _flat((ROOT / "docs" / "eval-tools.md").read_text(encoding="utf-8"))


def test_the_readme_says_marking_every_answer_leaves_no_range():
    """With every answer of a group marked its share is known (the reference's maths)."""
    numbers = _flat(_sections(_readme())["The numbers"])
    assert ('TPR and TNR each come with a range, such as "about 90% (between 85% and 93%)" '
            "(when you mark every answer, the numbers are exact and have no range).") in numbers
    reference = _flat((ROOT / "docs" / "reference.md").read_text(encoding="utf-8"))
    assert "With every answer of a group marked, its share is known, so it has no range." in reference


def test_the_docs_say_mark_asks_for_a_taken_on_pass_mark_again():
    """After `check --pass-if` takes a pass mark on, `check` and `fix` read with it, while
    `mark` and a plain run ask for it again (the code: front's pass mark question)."""
    reference = _flat((ROOT / "docs" / "reference.md").read_text(encoding="utf-8"))
    changelog = _flat((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    assert ("Once `check` takes it on, later `check` and `fix` runs read your results with it. "
            "`mark` and a plain `judgekeeper` ask for the pass mark again, with that one as the "
            "default;") in reference
    assert ("once taken on, later `check` and `fix` runs read with it, and `mark` and a plain "
            "`judgekeeper` ask for the pass mark again with it as the default.") in changelog
    for text in (reference, changelog):
        assert "`check`, `fix` and `mark` runs read" not in text
    measure = next(x for x in (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
                   if x.startswith("3. **Measure:**"))
    assert ("If your LLM-as-a-judge gives scores, a plain `judgekeeper` asks for the pass mark "
            "again, with the one you gave as the default; with no terminal, it prints the "
            "`--pass-if` to give.") in measure


def test_the_jailbreakbench_screens_are_what_this_version_prints():
    """The two Measure screens in the JailbreakBench report are this version's (made again
    from the committed marks), and the old first run's "good enough to use" at 200 marks is
    named as judgekeeper 1.0.0b2's, not given as today's result."""
    import re

    text = (ROOT / "docs" / "examples" / "jailbreakbench" / "report.md").read_text(encoding="utf-8")
    flat = _flat(text)
    assert not re.search(r"\byour judge\b", text, re.IGNORECASE)
    assert "in the wording of an older version" not in text
    after_200 = flat.split("### After 200 marks", 1)[1].split("###", 1)[0]
    assert "Result: too early to tell. Mark more answers to get a result." in after_200
    assert "Result: your LLM-as-a-judge is good enough to use." not in after_200
    assert ('On the same 200 marks, judgekeeper 1.0.0b2 said "good enough to use"' in after_200)
    draw = flat.split("## One draw on commit `6437d85`", 1)[1].split("## ", 1)[0]
    assert "Result: your LLM-as-a-judge is good enough to use." in draw
    assert ('In 7 of the 20 draws, judgekeeper 1.0.0b2 gave the result "good enough to use".'
            in flat)
