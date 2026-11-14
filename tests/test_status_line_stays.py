"""A line under the buttons ("Noted...", "Not marked...", "Nothing to undo.") never moves a
button: Pass, Fail, Skip and Undo have the same boxes with and without it. Run in headless
Chrome on the real page, at 1470 and 1280 px wide; skipped where there is no Chrome."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from judgekeeper import mark_page

LINES = {
    "none": "",
    "noted": mark_page.FIRST_COUNTS.format(mark="Fail"),
    "not marked": mark_page.NOT_MARKED.format(shown='"where do I change the backup window..."'),
    "opening": mark_page.OPENING,
    "nothing to undo": "Nothing to undo.",
    "not saved": "Not saved: this answer was changed.",
    "no answer": mark_page.NO_ANSWER,
}

# What the page can show near the buttons besides the card itself: the line under them, the
# state beside the question, the note on a card shown again, the run and the bar's line.
STATES = {
    "marked pass": 'ans-status|<span>Marked </span><span class="said pass">Pass</span>',
    "skipped": "ans-status|Skipped",
    "shown again": "a-again!",
    "run": "a-run!Run 2 of 3: graded differently",
    "bar line": "waiting!Judge grades are not here yet; they are marked once, here.",
}

MEASURE = """
<script nonce="n">
window.addEventListener("load", function () {
  setTimeout(function () {
    var out = {}, status = document.getElementById("status");
    function boxes(name) {
      out[name] = {};
      ["fail", "pass", "skip", "undo"].forEach(function (id) {
        var r = document.getElementById(id).getBoundingClientRect();
        out[name][id] = [r.left, r.top, r.width, r.height].map(Math.round);
      });
      out[name].inner = [innerWidth, innerHeight];
    }
    var lines = %s, states = %s;
    Object.keys(lines).forEach(function (name) {
      status.textContent = lines[name];
      status.classList.toggle("calm", /^(Noted|Your result|Nothing)/.test(lines[name]));
      boxes("line: " + name);
    });
    status.textContent = "";
    Object.keys(states).forEach(function (name) {
      var spec = states[name], hide = spec.indexOf("!") > -1, at = spec.split(/[|!]/);
      var node = document.getElementById(at[0]);
      if (hide) { node.hidden = false; if (at[1]) { node.textContent = at[1]; } }
      else { node.innerHTML = at[1]; }
      boxes("state: " + name);
      if (hide) { node.hidden = true; } else { node.textContent = ""; }
    });
    var pre = document.createElement("pre"); pre.id = "measured";
    pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
  }, 600);
});
</script>
"""


def _chrome() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        if found := shutil.which(name):
            return found
    for path in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ):
        if os.path.exists(path):
            return path
    return None


def _boxes(width: int, height: int, long: bool = False) -> dict:
    chrome = _chrome()
    if chrome is None:
        pytest.skip("needs Chrome to lay the page out")
    question, answer = ("Question?", "Answer.") if not long else (
        "Where do I change the backup window for plan 16? " * 5, "Open Settings, then Backups. " * 120)
    data = {"items": [{"id": f"a{i}", "input": question, "output": answer,
                       "label": None, "skipped": False} for i in range(6)],
            "total": 6, "start": 0, "counts": {"correct": 0, "wrong": 0, "skipped": 0},
            "status": {"text": "Keep going.", "ready": False}}
    page = (mark_page.label_page(None, model="gpt-4.1-mini", tool="promptfoo")
            .replace("__NONCE__", "n").replace("__TOKEN__", "t0k")
            .replace("__DATA__", json.dumps(data).replace("<", "\\u003c")))
    page = page.replace("</body>", MEASURE % (json.dumps(LINES), json.dumps(STATES)) + "</body>")
    with tempfile.TemporaryDirectory() as folder:
        file = Path(folder) / "page.html"
        file.write_text(page, encoding="utf-8")
        out = subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
             f"--user-data-dir={Path(folder) / 'profile'}", f"--window-size={width},{height}",
             "--virtual-time-budget=4000", "--dump-dom", file.as_uri()],
            check=False, capture_output=True, text=True, encoding="utf-8", timeout=120)
    found = re.search(r'<pre id="measured">(.*?)</pre>', out.stdout, re.DOTALL)
    assert found, out.stderr[-500:]
    return json.loads(found[1].replace("&quot;", '"').replace("&amp;", "&"))


@pytest.mark.parametrize("long", [False, True], ids=["short", "long text"])
@pytest.mark.parametrize("width,height", [(1470, 978), (1280, 860)])
def test_nothing_that_shows_moves_a_button(width, height, long):
    boxes = _boxes(width, height, long)
    base = boxes["line: none"]
    moved = {name: {k: v for k, v in got.items() if k != "inner" and v != base[k]}
             for name, got in boxes.items()}
    assert {name: m for name, m in moved.items() if m} == {}


def test_the_line_under_the_buttons_is_out_of_the_layout():
    """It sits over the foot of the answer, so a line showing or going cannot move a button."""
    assert re.search(r"\.status \{ position: absolute;", mark_page.STYLE)
