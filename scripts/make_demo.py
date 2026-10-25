"""Make the README's demo: docs/assets/demo.webp, an animated WebP of about 18 seconds.

    python scripts/make_demo.py                      # writes docs/assets/demo.webp
    python scripts/make_demo.py --chrome PATH        # a Chrome or Chromium to use
    python scripts/make_demo.py --frames DIR         # also save each frame as a PNG in DIR

It builds the website's sample project (scripts/make_site_shots.py: 40 made-up answers the
LLM-as-a-judge decided, saved with judgekeeper.record(), so no judge is called and no API key is
read). Then it runs `judgekeeper` there at a pseudo-terminal, as a person does. The browser it
opens is the script's headless Chrome: a stand-in for webbrowser.open writes down the link and
says it opened, so judgekeeper prints what a person sees. On the marking page Chrome clicks
Pass or Fail on three answers with real mouse events; the other answers are marked through the
page's own HTTP calls (POST /label, with the seconds a person might take, as the page sends
them). Then `judgekeeper` runs again and prints its result.

Every line of terminal text in the demo is what judgekeeper printed; only the colours are
added, and the mouse pointer, which headless Chrome does not draw. The terminal looks like the
website's (website/assets/style.css and its fonts).
Standard library and judgekeeper, plus Pillow (pip install pillow) to write the WebP.
The file must be under 1 MB and last 15 to 20 seconds; the WebP quality goes down until it fits.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import os
import pty
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

# scripts/ is on the path when this file is run: the sample project, Chrome and the page's calls
from make_site_shots import ANSWERS, Chrome, Start, find_chrome, make_project, my_mark

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFile
except ImportError:  # checked in main(), so --help works without it
    Image = None

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "assets" / "demo.webp"
FONTS = ROOT / "website" / "assets" / "fonts"
WIDTH, HEIGHT, BAR = 1000, 720, 44  # the window, and its title bar, in pixels
MAX_BYTES = 1_000_000
SECONDS = (15.0, 20.0)  # how long the demo may last
QUALITIES = (90, 85, 80, 75, 70, 65, 60)
CLICKED = 3  # answers marked with the mouse on camera
MARK_SECONDS = (6, 4, 9, 5, 7, 3, 8)  # the seconds sent with each mark made over HTTP
TYPE_STEP = 3  # characters typed per frame
TYPE_MS = 90  # how long each typed frame shows
ROWS = 29  # the terminal's lines: it scrolls, as a terminal does
TRIES = 20  # sample projects made until the first answers to click hold a Pass and a Fail

# `python -c` with this runs judgekeeper's own main, with one change: the browser it opens is
# the demo's Chrome. The link goes to the file JK_DEMO_OPENED, and the open counts as done.
OPENER = """
import os, sys, webbrowser

class Demo(webbrowser.BaseBrowser):
    def open(self, url, new=0, autoraise=True):
        with open(os.environ["JK_DEMO_OPENED"], "a", encoding="utf-8") as f:
            f.write(url + "\\n")
        return True

webbrowser.register("demo", None, Demo("demo"), preferred=True)
sys.argv[0] = "judgekeeper"
from judgekeeper.__main__ import main
sys.exit(main())
"""

TERMINAL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>
@font-face {{ font-family: "JetBrains Mono"; font-weight: 400;
  src: url("{fonts}/jetbrains-mono-latin-400-normal.woff2") format("woff2"); }}
@font-face {{ font-family: "JetBrains Mono"; font-weight: 500;
  src: url("{fonts}/jetbrains-mono-latin-500-normal.woff2") format("woff2"); }}
html, body {{ margin: 0; width: {width}px; height: {height}px; overflow: hidden; }}
body {{ background: #07080a; color: #e6e8eb; font-family: "JetBrains Mono", Menlo, monospace;
  font-variant-ligatures: none; -webkit-font-smoothing: antialiased; box-sizing: border-box;
  border: 1px solid #262a30; display: flex; flex-direction: column; }}
.bar {{ flex: none; display: flex; align-items: center; height: {bar}px; padding: 0 20px;
  border-bottom: 1px solid #262a30; background: #101215; font-size: 13px; color: #8b919a;
  box-sizing: border-box; }}
.bar::before {{ content: ""; flex: none; width: 11px; height: 11px; border-radius: 50%;
  background: #33373e; box-shadow: 18px 0 0 #33373e, 36px 0 0 #33373e; margin-right: 36px; }}
.title {{ flex: 1; text-align: center; margin-right: 72px; }}
.url {{ flex: 1; margin: 0 24px 0 16px; height: 28px; line-height: 28px; border-radius: 7px;
  background: #07080a; border: 1px solid #262a30; padding: 0 14px; }}
.url b {{ color: #e6e8eb; font-weight: 400; }}
.screen {{ flex: 1; min-height: 0; overflow: hidden; display: flex; flex-direction: column;
  padding: 14px 26px; }}
pre {{ margin: 0; font: inherit; font-size: 14.5px; line-height: 1.5; white-space: pre; }}
.p, .next {{ color: #10B981; }}
.c, .step {{ color: #e6e8eb; font-weight: 500; }}
.dim {{ color: #8b919a; }}
.warn {{ color: #e0a43a; font-weight: 500; }}
.good {{ color: #10B981; font-weight: 500; }}
.cur {{ display: inline-block; width: .6em; height: 1.2em; vertical-align: -.22em;
  background: #e6e8eb; }}
</style></head><body><div class="bar" id="bar"></div>
<div class="screen"><pre id="out"></pre></div></body></html>
"""


# judgekeeper at a terminal ---------------------------------------------------------------

def say(folder: Path, opened: Path, *flags: str) -> str:
    """Run `judgekeeper` in the project at a pseudo-terminal until it stops: what it printed,
    as plain text (only the escape codes and carriage returns taken out)."""
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "COLUMNS": "80", "JK_DEMO_OPENED": str(opened),
           "JUDGEKEEPER_NO_LINKS": "1"}  # no terminal links: the text stays plain
    env.pop("BROWSER", None)  # the browser is the demo's Chrome
    main, side = pty.openpty()
    try:
        process = subprocess.Popen([sys.executable, "-c", OPENER, *flags], cwd=folder, env=env,
                                   stdin=side, stdout=side, stderr=side)
    finally:
        os.close(side)
    out = b""
    deadline = time.monotonic() + 120
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([main], [], [], 0.5)
            if ready:
                try:
                    chunk = os.read(main, 65536)
                except OSError:  # the terminal closes when judgekeeper stops (EIO on Linux)
                    break
                if not chunk:
                    break
                out += chunk
            elif process.poll() is not None:
                break
        else:
            process.kill()
            raise SystemExit("judgekeeper did not stop:\n" + out.decode("utf-8", "replace"))
        process.wait(timeout=10)
    finally:
        os.close(main)
    text = out.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\x1b\[[0-9;?]*[A-Za-z]", "", text)
    return text.rstrip("\n")


def last_link(opened: Path) -> str:
    links = opened.read_text(encoding="utf-8").split() if opened.is_file() else []
    if not links:
        raise SystemExit("judgekeeper opened no page")
    return links[-1]


# The frames -------------------------------------------------------------------------------

def coloured(lines: list[str]) -> str:
    """The terminal's lines as HTML: the text as printed, with the website's colours."""
    out = []
    for line in lines:
        text = html.escape(line)
        if line.startswith("$ "):
            text = f'<span class="p">$</span> <span class="c">{text[2:]}</span>'
        elif re.match(r"Step \d of \d: ", line) or re.match(r"judgekeeper \d", line):
            text = f'<span class="step">{text}</span>'
        elif line.startswith("Result: "):
            kind = "warn" if "needs work" in line else "good"
            text = f'Result: <span class="{kind}">{text[8:]}</span>'
        elif line.startswith("Next:"):
            text = f'<span class="next">Next:</span>{text[5:]}'
        out.append(text)
    return "\n".join(out)


class Frames:
    """The demo's frames, each an image and how long it shows (in milliseconds)."""

    def __init__(self, chrome: Chrome, work: Path):
        self.chrome = chrome
        self.items: list[tuple[Image.Image, int]] = []
        page = work / "terminal.html"
        page.write_text(TERMINAL.format(fonts=FONTS.as_uri(), width=WIDTH, height=HEIGHT,
                                        bar=BAR), encoding="utf-8")
        self.terminal_page = page.as_uri()

    def _viewport(self, height: int) -> None:
        self.chrome.call("Emulation.setDeviceMetricsOverride", width=WIDTH, height=height,
                         deviceScaleFactor=1, mobile=False)

    def _grab(self, height: int) -> Image.Image:
        clip = {"x": 0, "y": 0, "width": WIDTH, "height": height, "scale": 1}
        data = self.chrome.call("Page.captureScreenshot", format="png", clip=clip)["data"]
        parser = ImageFile.Parser()  # the PNG from bytes
        parser.feed(base64.b64decode(data))
        return parser.close().convert("RGB")

    def add(self, image: Image.Image, ms: int) -> None:
        if self.items and not ImageChops.difference(self.items[-1][0], image).getbbox():
            self.items[-1] = (self.items[-1][0], self.items[-1][1] + ms)  # the same picture
        else:
            self.items.append((image, ms))

    def open_terminal(self, title: str) -> None:
        self._viewport(HEIGHT)
        self.chrome.visit(self.terminal_page, settle=0.2)
        self.chrome.run(f"document.getElementById('bar').innerHTML = "
                        f"{json.dumps('<span class=title>' + html.escape(title) + '</span>')}")

    def terminal(self, lines: list[str], ms: int, cursor: bool = False) -> None:
        body = coloured(lines[-ROWS:]) + ('<span class="cur"></span>' if cursor else "")
        self.chrome.run(f"document.getElementById('out').innerHTML = {json.dumps(body)}")
        self.add(self._grab(HEIGHT), ms)

    def typed(self, before: list[str], command: str, hold: int) -> None:
        """The prompt, then `command` typed a few characters at a time, then a short wait."""
        for n in range(0, len(command) + 1, TYPE_STEP):
            self.terminal([*before, "$ " + command[:n]], TYPE_MS if n else 500, cursor=True)
        self.terminal([*before, "$ " + command], hold, cursor=True)

    def browser_bar(self, link: str) -> Image.Image:
        """The browser's title bar with the page's address, drawn in the terminal page."""
        parts = urlsplit(link)
        self.open_terminal("")
        self.chrome.run("document.getElementById('bar').innerHTML = "
                        + json.dumps(f'<span class="url"><b>{parts.hostname}</b>:{parts.port}'
                                     f'{parts.path}</span>'))
        return self._grab(BAR)

    def browser(self, bar: Image.Image, ms: int, pointer: tuple[float, float] | None = None,
                pressed: bool = False) -> None:
        page = self._grab(HEIGHT - BAR)
        frame = Image.new("RGB", (WIDTH, HEIGHT), "#07080a")
        frame.paste(bar, (0, 0))
        frame.paste(page, (0, BAR))
        draw = ImageDraw.Draw(frame)
        draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline="#262a30")
        if pointer is not None:
            arrow(draw, pointer[0], pointer[1] + BAR, pressed)
        self.add(frame, ms)

    def seconds(self) -> float:
        return sum(ms for _, ms in self.items) / 1000


def arrow(draw: ImageDraw.ImageDraw, x: float, y: float, pressed: bool) -> None:
    """A mouse pointer with its tip at (x, y); smaller while the button is held down."""
    k = 0.85 if pressed else 1.0
    shape = [(0, 0), (0, 20), (5, 15), (9, 24), (12.5, 22.5), (8.5, 14), (15, 14)]
    draw.polygon([(x + k * px, y + k * py) for px, py in shape], fill="#ffffff",
                 outline="#07080a", width=2)


# The marking page -------------------------------------------------------------------------

def centre(chrome: Chrome, element: str) -> tuple[float, float]:
    box = chrome.run(f"(function () {{ var r = document.getElementById({json.dumps(element)})"
                     ".getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2];"
                     " })()")
    return box[0], box[1]


def mouse(chrome: Chrome, kind: str, x: float, y: float) -> None:
    extra = {"button": "left", "clickCount": 1} if kind != "mouseMoved" else {}
    chrome.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, **extra)


def click(chrome: Chrome, frames: Frames, bar: Image.Image, element: str, hover: int) -> None:
    """Point at `element`, press and let go, as a person clicks it: a frame for each."""
    x, y = centre(chrome, element)
    tip = (x + 6, y + 4)
    mouse(chrome, "mouseMoved", x, y)
    time.sleep(0.3)
    frames.browser(bar, hover, tip)
    mouse(chrome, "mousePressed", x, y)
    time.sleep(0.15)
    frames.browser(bar, 200, tip, pressed=True)
    mouse(chrome, "mouseReleased", x, y)


def marking(chrome: Chrome, frames: Frames, start: Start, link: str) -> None:
    """The marking page as judgekeeper opened it: close the first-time card, then mark three
    answers the way the person would, with the mouse."""
    frames._viewport(HEIGHT - BAR)
    bar = frames.browser_bar(link)
    frames._viewport(HEIGHT - BAR)
    chrome.visit(link)
    if chrome.run("document.getElementById('intro').hidden"):
        raise SystemExit("the marking page showed no first-time card")
    frames.browser(bar, 1000)
    click(chrome, frames, bar, "intro-ok", 500)
    time.sleep(0.8)
    if not chrome.run("document.getElementById('intro').hidden"):
        raise SystemExit("the first-time card is still showing")
    for n in range(CLICKED):
        frames.browser(bar, 1100 if n == 0 else 800)
        shown = chrome.run("document.getElementById('a-text').textContent")
        choice = my_mark({"output": shown})
        click(chrome, frames, bar, choice, 450)
        time.sleep(0.9)  # saved, and the next answer is on screen
    marked = start.get("/state")["counts"]
    if marked["correct"] + marked["wrong"] != CLICKED:
        raise SystemExit(f"the clicks marked {marked}, not {CLICKED} answers")
    frames.browser(bar, 1100)


def first_run(folder: Path, opened: Path) -> tuple[list[str], str]:
    """Make the sample project and run `judgekeeper` in it: what it printed and the link it
    opened. judgekeeper puts the answers in a new random order each time; the project is made
    again until the answers clicked on camera are both kinds, a Pass and a Fail."""
    for _ in range(TRIES):
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir()
        opened.unlink(missing_ok=True)
        make_project(folder)
        first = say(folder, opened).splitlines()
        link = last_link(opened)
        marks = {my_mark(item) for item in Page(link).get("/state")["items"][:CLICKED]}
        if len(marks) == 2:
            return first, link
        say(folder, opened, "--stop")
    raise SystemExit(f"the first {CLICKED} answers were all one kind {TRIES} times")


def mark_the_rest(start: Start) -> None:
    for n, item in enumerate(start.get("/state")["items"]):
        if item["label"] is None:
            start.post("/label", {"id": item["id"], "label": my_mark(item),
                                  "seconds": MARK_SECONDS[n % len(MARK_SECONDS)]})


class Page(Start):
    """The page `judgekeeper` left open in the background, reached by the link it opened."""

    def __init__(self, link: str):  # Start's calls, without starting judgekeeper
        parts = urlsplit(link)
        self.base = f"{parts.scheme}://{parts.netloc}"
        self.token = parts.query.split("token=", 1)[1]


# The WebP ---------------------------------------------------------------------------------

def save(frames: Frames, out: Path) -> tuple[int, int]:
    """Write the animated WebP at the best quality under MAX_BYTES: (bytes, quality)."""
    images = [image for image, _ in frames.items]
    durations = [ms for _, ms in frames.items]
    for quality in QUALITIES:
        buffer = io.BytesIO()
        images[0].save(buffer, format="WEBP", save_all=True, append_images=images[1:],
                       duration=durations, loop=0, quality=quality, method=6,
                       allow_mixed=True, minimize_size=True, background=(7, 8, 10, 255))
        if buffer.tell() < MAX_BYTES:
            break
    else:
        raise SystemExit(f"the demo is {buffer.tell():,} bytes even at quality {quality}")
    out.write_bytes(buffer.getvalue())
    return buffer.tell(), quality


def check(out: Path) -> tuple[int, float]:
    """Read the WebP back: its frame count and seconds, from its ANMF chunks."""
    data = out.read_bytes()
    count, total, at = 0, 0, 12
    while at + 8 <= len(data):
        kind, size = data[at:at + 4], int.from_bytes(data[at + 4:at + 8], "little")
        if kind == b"ANMF":
            count += 1
            total += int.from_bytes(data[at + 20:at + 23], "little")
        at += 8 + size + (size & 1)
    return count, total / 1000


def make(chrome: Chrome, work: Path, folder: Path, out: Path, keep: Path | None) -> None:
    opened = work / "opened.txt"
    frames = Frames(chrome, work)
    first, link = first_run(folder, opened)
    prompt = ["$ judgekeeper"]
    try:
        frames.open_terminal(folder.name)
        frames.typed([], "judgekeeper", 350)
        split = next(n for n, line in enumerate(first) if line.startswith("Step 2 of"))
        frames.terminal(prompt + first[:split], 1100)
        frames.terminal(prompt + first, 2700)
        start = Page(link)
        marking(chrome, frames, start, link)
        mark_the_rest(start)
        again = say(folder, opened).splitlines()
        if not any(line.startswith("Result: ") for line in again):
            raise SystemExit("the second run printed no result:\n" + "\n".join(again))
        if any("program" in line for line in again):
            raise SystemExit("judgekeeper took the marks for a program's:\n" + "\n".join(again))
        frames.open_terminal(folder.name)
        before = [*prompt, *first, ""]
        frames.typed(before, "judgekeeper", 300)
        frames.terminal([*before, *prompt, *again, ""], 400)
        frames.terminal([*before, *prompt, *again, "", "$ "], 4500, cursor=True)
    finally:
        say(folder, opened, "--stop")  # close the page left open in the background
    if keep is not None:
        keep.mkdir(parents=True, exist_ok=True)
        for n, (image, ms) in enumerate(frames.items):
            image.save(keep / f"frame-{n:02d}-{ms}ms.png")
    total = frames.seconds()
    if not SECONDS[0] <= total <= SECONDS[1]:
        raise SystemExit(f"the demo lasts {total:.1f} seconds, not {SECONDS[0]:.0f} to "
                         f"{SECONDS[1]:.0f}")
    size, quality = save(frames, out)
    count, seconds = check(out)
    print(f"{out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}: {WIDTH} x {HEIGHT}, "
          f"{count} frames, {seconds:.1f} s, {size / 1000:.0f} KB (WebP quality {quality})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chrome", help="the Chrome or Chromium program to use")
    ap.add_argument("--out", type=Path, default=OUT, help=f"where to save (default {OUT})")
    ap.add_argument("--frames", type=Path, help="a folder to save each frame in, as PNG")
    args = ap.parse_args(argv)
    if Image is None:
        raise SystemExit("make_demo.py needs Pillow to write the WebP: pip install pillow")
    if len(ANSWERS) != 40:
        raise SystemExit("the sample project should have 40 answers")
    chrome_path = find_chrome(args.chrome)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="judgekeeper-demo-"))
    folder = work / "support-bot"
    chrome = None
    try:
        chrome = Chrome(chrome_path, work / "chrome")
        make(chrome, work, folder, args.out, args.frames)
    finally:
        if chrome is not None:
            chrome.close()
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
