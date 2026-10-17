"""The pages, the saved files and the words.

- The wording sweep: no "for free", no "your app" on its own, in the package and the docs.
- The marking page at phone width scrolls as one, and a "Not saved" line is always on
  screen; each entry in its list of answers is one line, cut with "…".
- More key shapes are hidden; joined emoji and scripts keep their zero-width joiners.
- A long answer cut in the report ends with "…", at a word.
- Every file judgekeeper writes in `.judgekeeper/` is its owner's only (0600, folders 0700).
- The pages are dark only: no theme switch, no light colours.
No test calls an AI API.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from judgekeeper import fix, label, look, mark_page, redact, report_page, start_label
from judgekeeper.start_label import Workspace
from tests.start_projects import split, table_project
from tests.test_flow_fixes import _mark
from tests.test_front import run
from tests.test_product_pages import CHECK, NOT_GATE_TNR, _result

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "judgekeeper"


@pytest.fixture
def here(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# 36. The wording sweep ----------------------------------------------------------------------

OLD_WORDS = [  # (where, the old text)
    ("src", r"Re-checked for free"),
    ("README.md", r"checks its grades for free"),
    ("README.md", r"never runs your app(?! or agent)"),
    ("src", r"Your app is not run\."),
    ("src", r"the trace of your app's run"),
    ("src", r"hold your app's answers"),
    ("docs/reference.md", r"What the free check found"),
    ("SECURITY.md", r"The free check on the website"),
    ("README.md", r"a question, your app's answer"),
    ("src", r"\(free: it runs no test\)"),
    ("docs/reference.md", r"with the saved scores: free, no AI call"),
    ("docs/reference.md", r"Free first: answers you marked"),
]


def test_the_old_words_are_gone():
    src = "\n".join(p.read_text(encoding="utf-8") for p in PACKAGE.rglob("*.py"))
    for where, old in OLD_WORDS:
        text = src if where == "src" else (ROOT / where).read_text(encoding="utf-8")
        assert not re.search(old, text), (where, old)


def test_the_new_words():
    from judgekeeper import check, start
    from judgekeeper.again import deepeval, inspect, mlflow, promptfoo

    assert "Re-checked with no AI call, from your new results." in Path(check.__file__).read_text(
        encoding="utf-8")
    for module in (deepeval, inspect, mlflow, promptfoo):
        assert "Your app or agent is not run." in Path(module.__file__).read_text(
            encoding="utf-8"), module.__name__
    assert "the trace of your app or agent's run" in Path(promptfoo.__file__).read_text(
        encoding="utf-8")
    assert start_label.GITIGNORE.startswith("# judgekeeper's files hold your answers. ")
    assert Path(start.__file__).read_text(encoding="utf-8").count("(it runs no test)") >= 2
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "checks its grades with no AI call" in readme
    assert "judgekeeper never runs your app or agent" in readme
    assert 'alt="The marking page: a question, the answer' in readme
    ref = (ROOT / "docs" / "reference.md").read_text(encoding="utf-8")
    assert "What the first check found" in ref
    assert "with the saved scores, with no AI call" in ref
    assert "First, with no AI call: answers you marked" in ref
    assert "The browser check on the website (`check.html`)" in (
        ROOT / "SECURITY.md").read_text(encoding="utf-8")


# 37. The marking page at phone width --------------------------------------------------------

def _phone_rules() -> str:
    return mark_page.STYLE[mark_page.STYLE.index("@media (max-width: 760px)"):]


def test_at_phone_width_the_page_scrolls_as_one():
    phone = _phone_rules()
    assert "html, body { height: auto; }" in phone
    assert "#app, .wrap { flex: none; min-height: 0; }" in phone
    assert ".main, .list { overflow: visible; }" in phone


def test_a_not_saved_line_is_brought_into_view():
    from tests.test_mark_page_script import _run

    got = _run("""
      fetch = function () { return Promise.reject(new Error("gone")); };
      document.getElementById("status").scrollIntoView = function (o) { shown.push(o); };
      key("ArrowRight"); await settle(); await settle();
      console.log(JSON.stringify({status: ids["status"].textContent, shown: shown}));""",
               before="var shown = [];\n")
    assert got["status"].startswith("Not saved: this page lost its link to judgekeeper.")
    assert got["shown"] == [{"block": "nearest"}]


def _chrome() -> str | None:
    for name in (os.environ.get("JUDGEKEEPER_CHROME"), "google-chrome", "chromium",
                 "chromium-browser", "chrome"):
        if name and shutil.which(name):
            return shutil.which(name)
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return mac if os.path.exists(mac) else None


# The marking page in a 390px frame (headless Chrome is at least 500px wide): open the longest
# answer, scroll its Pass button to the middle, press it with judgekeeper gone, then look.
PHONE_CHECK = """
var f = document.getElementById("f");
f.addEventListener("load", function () {
  var w = f.contentWindow, d = f.contentDocument, out = {width: w.innerWidth};
  d.getElementById("intro-ok").click();
  d.querySelector('[data-k="0"]').click();
  setTimeout(function () {
    var p = d.getElementById("pass"), boxes = [];
    for (var e = p.parentElement; e && e !== d.body; e = e.parentElement) {
      var s = w.getComputedStyle(e);
      if ((s.overflowY === "auto" || s.overflowY === "scroll") &&
          e.scrollHeight > e.clientHeight + 2) { boxes.push(e.className || e.tagName); }
    }
    out.boxes = boxes;
    var r = p.getBoundingClientRect();
    w.scrollTo(0, r.top + w.scrollY - w.innerHeight / 2);
    r = p.getBoundingClientRect();
    var hit = d.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    out.pass = hit === p || p.contains(hit);
    p.click();
    setTimeout(function () {
      var s = d.getElementById("status"), q = s.getBoundingClientRect();
      out.status = s.textContent.slice(0, 9);
      out.seen = q.height > 0 && q.top >= 0 && q.bottom <= w.innerHeight;
      document.getElementById("out").textContent = JSON.stringify(out);
    }, 500);
  }, 300);
});
"""


def test_at_390px_the_pass_button_and_the_status_line_can_be_reached(tmp_path):
    chrome = _chrome()
    if chrome is None:
        pytest.skip("needs Chrome")
    items = [{"id": f"a{i}", "input": f"Question {i}?", "output": f"Answer {i}.",
              "label": None, "skipped": False} for i in range(8)]
    items[0]["input"] = "Long word: " + "A" * 3000
    data = {"items": items, "total": 8, "start": 1,
            "counts": {"correct": 0, "wrong": 0, "skipped": 0},
            "status": {"text": "Keep going.", "ready": False}}
    page = (mark_page.label_page(None, "judgekeeper mark").replace("__NONCE__", "n")
            .replace("__TOKEN__", "t").replace("__DATA__", label._json_for_html(data)))
    srcdoc = page.replace("&", "&amp;").replace('"', "&quot;")
    (tmp_path / "phone.html").write_text(
        '<!doctype html><html><body style="margin:0"><p id="out"></p>'
        f'<iframe id="f" style="width:390px;height:844px;border:0" srcdoc="{srcdoc}"></iframe>'
        f"<script>{PHONE_CHECK}</script></body></html>", encoding="utf-8")
    try:
        done = subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--no-sandbox",
             f"--user-data-dir={tmp_path / 'profile'}", "--window-size=800,900",
             "--virtual-time-budget=5000", "--dump-dom", (tmp_path / "phone.html").as_uri()],
            check=False, capture_output=True, text=True, encoding="utf-8", timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("Chrome did not start")
    found = re.search(r'<p id="out">(\{.*?\})</p>', done.stdout)
    if not found:
        pytest.skip("Chrome did not run the page")
    got = json.loads(found[1].replace("&quot;", '"'))
    assert got == {"width": 390, "boxes": [], "pass": True, "status": "Not saved", "seen": True}


# 38. More key shapes hidden -----------------------------------------------------------------

# Not real keys: each is in two parts, so no secret scanner takes it for one
KEYS = {
    "AWS access key": "AKIA" + "IOSFODNN7EXAMPLE",
    "AWS session key": "ASIA" + "JEXAMPLEXEG2JICE",
    "GitHub ghp_": "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789",
    "GitHub gho_": "gho_" + "bcdefghijklmnopqrstuvwxyz01234567890",
    "GitHub ghs_": "ghs_" + "cdefghijklmnopqrstuvwxyz012345678901",
    "GitHub ghu_": "ghu_" + "defghijklmnopqrstuvwxyz0123456789012",
    "GitHub github_pat_": "github_pat_" + ("11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz"
                                           "0123456789ABCDEFGHIJKLMNOPQRSTU"),
    "Google API key": "AIza" + "SyA1EXAMPLEexampleEXAMPLEexample12",
    "Slack xoxb-": "xoxb-" + "123456789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx",
    "Slack xoxp-": "xoxp-" + ("123456789012-1234567890123-1234567890123-"
                              "0123456789abcdef0123456789abcdef"),
}
AWS_SECRET = "wJalrXUtnFEMI" + "/K7MDENG/bPxRfiCYEXAMPLEKEY"


@pytest.mark.parametrize("name", sorted(KEYS))
def test_a_key_shape_is_hidden(name):
    assert redact.scrub(f"use {KEYS[name]} here.") == "use [REDACTED] here."


def test_an_aws_secret_after_its_name_is_hidden():
    for text in (f"aws_secret_access_key = {AWS_SECRET}", f"AWS_SECRET_ACCESS_KEY={AWS_SECRET}",
                 f'"aws_secret_access_key": "{AWS_SECRET}"'):
        assert AWS_SECRET not in redact.scrub(text), text
        assert "[REDACTED]" in redact.scrub(text), text


def test_a_bearer_token_is_hidden():
    token = "abcdefghijklmnopqrstuvwxyz" + "ABCDEF0123456789"
    assert redact.scrub(f"Authorization: Bearer {token}") == \
        "Authorization: Bearer [REDACTED]"


def test_ordinary_text_is_kept():
    for text in ("AKIA is a prefix.", "The ghp_ tokens are GitHub's.", "Ask Bearer of the news.",
                 "AIza", "xoxb-", "an aws_secret_access_key is 40 characters"):
        assert redact.scrub(text) == text


def test_keys_in_answers_are_not_saved_or_shown(here, capsys):
    table_project(here, split(20, 16))
    rows = (here / "results.csv").read_text(encoding="utf-8").splitlines()
    rows[1] = rows[1].replace("Answer", f"Use {KEYS['AWS access key']} and "
                                        f"aws_secret_access_key={AWS_SECRET}. Answer")
    rows[2] = rows[2].replace("Answer", f"Token {KEYS['GitHub ghp_']}. Answer")
    (here / "results.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    assert run(capsys)[0] == 0
    saved = "".join(p.read_text(encoding="utf-8", errors="replace")
                    for p in (here / ".judgekeeper").rglob("*") if p.is_file())
    assert (here / ".judgekeeper" / "report.html").is_file()
    for key in (KEYS["AWS access key"], AWS_SECRET, KEYS["GitHub ghp_"]):
        assert key not in saved


def test_the_reference_lists_the_key_shapes():
    ref = (ROOT / "docs" / "reference.md").read_text(encoding="utf-8")
    line = next(x for x in ref.splitlines() if "anything shaped like" in x)
    for shape in ("`sk-ant-…`", "`AKIA…`", "`ASIA…`", "`aws_secret_access_key`", "`ghp_…`",
                  "`gho_…`", "`ghs_…`", "`ghu_…`", "`github_pat_…`", "`AIza…`", "`xoxb-…`",
                  "`xoxp-…`", "`Bearer …`"):
        assert shape in line, shape


# 39. Joined emoji and scripts ---------------------------------------------------------------

def test_a_page_keeps_the_zero_width_joiners():
    family = "\U0001F468\u200d\U0001F469\u200d\U0001F467"
    assert redact.visible(f"Emoji {family} test") == f"Emoji {family} test"
    assert redact.visible("می\u200cخواهم") == "می\u200cخواهم"  # Persian needs ZWNJ


def test_a_page_still_drops_the_other_hidden_characters():
    for hidden in ("\u200b", "\u200e", "\u200f", "\u202e", "\u2066", "\ufeff", "\x1b"):
        assert redact.visible(f"pa{hidden}ss") == "pass", repr(hidden)


def test_the_terminal_still_drops_every_zero_width_character():
    assert redact.printable("a\u200db\u200cc") == "abc"


# 40. The answer list ------------------------------------------------------------------------

def test_each_answer_in_the_list_is_one_line_cut_with_an_ellipsis():
    style = mark_page.STYLE
    assert "grid-template-columns: 36px minmax(0, 1fr) 16px;" in style
    assert (".item .q { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }"
            in style)
    assert "overflow-wrap: anywhere" not in style.split(".item .q")[1].split("}")[0]


# 41. The report's cut -----------------------------------------------------------------------

LOREM = ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor "
         "incididunt ut labore et dolore magna aliqua ")


def test_a_long_text_is_cut_at_a_word_and_ends_with_an_ellipsis():
    long = ("Start " + LOREM * 200)[:20000]
    cut = fix.cut_words(long, 1500)
    assert cut.endswith("…") and len(cut) <= 1500
    body = cut[:-1]
    assert long.startswith(body) and long[len(body)] == " "
    assert fix.cut_words("short text", 1500) == "short text"
    word = "A" * 3000  # one word: cut where it must
    assert fix.cut_words(word, 1500) == "A" * 1499 + "…"


def test_the_report_cuts_a_long_answer_with_an_ellipsis(here, capsys):
    table_project(here, split(20, 16))
    long = ("Start " + LOREM * 200)[:20000]
    rows = (here / "results.csv").read_text(encoding="utf-8").splitlines()
    rows[1] = rows[1].replace("Answer 0.", long)  # the judge passed it
    (here / "results.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert run(capsys)[0] == 0
    ws = Workspace(here)
    _mark(ws, person={0: "fail"})
    section = fix.report_section(ws)
    answer = next(m["answer"] for m in section["mistakes"] if m["answer"].startswith("Start"))
    assert answer.endswith("…") and long.startswith(answer[:-1])
    assert long[len(answer) - 1] == " "


# 42. File permissions -----------------------------------------------------------------------

private = pytest.mark.skipif(os.name == "nt", reason="Windows has no 0600")


@private
def test_the_shared_helpers_make_private_files_and_folders(tmp_path):
    from judgekeeper import marks, textio

    folder = tmp_path / ".judgekeeper" / "fix" / "runs"
    textio.make_private(folder)
    for f in (tmp_path / ".judgekeeper", folder.parent, folder):
        assert os.stat(f).st_mode & 0o777 == 0o700, f
    marks.append(tmp_path / ".judgekeeper" / "history.jsonl", {"kind": "check"})
    with textio.open_private(tmp_path / ".judgekeeper" / "page.log", "ab") as log:
        log.write(b"x")
    for f in ("history.jsonl", "page.log"):
        assert os.stat(tmp_path / ".judgekeeper" / f).st_mode & 0o777 == 0o600, f


@private
@pytest.mark.real_page
def test_the_page_log_is_private(tmp_path, monkeypatch):
    from judgekeeper import background

    def no_page(*args, **kwargs):
        raise OSError("not started")

    monkeypatch.setattr(background.subprocess, "Popen", no_page)
    assert background.start(tmp_path, {"port": 0}, "t", timeout=0.1) is None
    assert os.stat(tmp_path / background.LOG).st_mode & 0o777 == 0o600


@private
def test_every_file_and_folder_judgekeeper_writes_is_private(here, capsys, monkeypatch):
    table_project(here, split(20, 16))
    assert run(capsys)[0] == 0
    _mark(Workspace(here))
    assert run(capsys)[0] == 0
    run(capsys, "fix")
    table_project(here, split(16, 20))  # the newest grades changed: check re-reads them
    run(capsys, "check")
    from judgekeeper import recorder

    monkeypatch.setattr(recorder, "_paths", {})  # the file's path, kept for this test only
    recorder.record(input="q", output="a", verdict="pass", judge="gpt-4.1")
    assert any((here / ".judgekeeper" / "records").iterdir())
    bad = []
    for top, dirs, files in os.walk(here / ".judgekeeper"):
        for name in [top, *(os.path.join(top, f) for f in files)]:
            want = 0o700 if os.path.isdir(name) else 0o600
            if os.stat(name).st_mode & 0o777 != want:
                bad.append(f"{os.path.relpath(name, here)} {oct(os.stat(name).st_mode & 0o777)}")
    assert (here / ".judgekeeper" / "history.jsonl").is_file()
    assert (here / ".judgekeeper" / "fix").is_dir()
    assert not bad
    assert os.stat(here / "results.csv").st_mode & 0o077  # the project's own files: as they were


# 45. Dark only ------------------------------------------------------------------------------

def _pages() -> dict[str, str]:
    return {"marking": mark_page.label_page("support bot", "judgekeeper mark",
                                            model="openai:gpt-4.1-mini", tool="promptfoo"),
            "result": start_label.result_html(_result(*CHECK), back="/?token=t"),
            "report.html": start_label.result_html(_result(*NOT_GATE_TNR)),
            "old link": mark_page.old_link_page()}


def test_every_page_is_dark_with_no_theme_switch():
    for name, page in _pages().items():
        assert 'id="theme"' not in page and 'class="theme"' not in page, name
        assert "jk-theme" not in page and "localStorage.getItem(\"jk" not in page, name
        assert "data-theme" not in page, name
        assert re.search(r":root \{ color-scheme: dark;", page), name
        assert not re.search(r"color-scheme:\s*(light|dark\s+light|light\s+dark)", page), name
        assert "#ffffff; --text: #111317" not in page, name  # the light colours


def test_look_has_no_theme_scripts():
    for gone in ("THEME_FIRST", "THEME_SWITCH", "SWITCH"):
        assert not hasattr(look, gone), gone
    assert "dark only" in look.__doc__ and "jk-theme" not in look.__doc__


def test_the_result_page_runs_only_its_one_script():
    page = start_label.result_html(_result(*NOT_GATE_TNR))
    scripts = re.findall(r"<script>(.*?)</script>", page, re.DOTALL)
    assert scripts == [report_page.SCRIPT]
    assert report_page.CSP.count("'sha256-") == 1


def test_the_old_link_page_runs_no_script():
    assert "<script" not in mark_page.old_link_page()
    assert "script-src" not in mark_page.OLD_LINK_CSP

