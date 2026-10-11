"""Take the website's three pictures of the real product pages.

    python scripts/make_site_shots.py                      # writes website/assets/shots/
    python scripts/make_site_shots.py --chrome PATH        # a Chrome or Chromium to use

It makes a sample project in a temporary folder: a made-up support bot ("support-bot") whose
judge, "Is polite and correct." with the model name openai:gpt-4.1-mini, decided on 40
answers. The judge's verdicts are saved with judgekeeper.record(), so the pages know the
judge's rule. No judge is called, no API key is read, and nothing costs money.

Then it runs `judgekeeper start` in that folder, the way a person does, and marks the answers
through the same HTTP calls the page makes (POST /label). Headless Chrome, driven over its
DevTools protocol, takes each picture at 1440 x 900, twice the pixels, as WebP:

- label.webp: the labeling page part of the way through, the dots at the top showing the marks;
- result.webp: the result page once every answer is marked;
- fix.webp: "What your judge gets wrong", with its "Change the rule" panel. To get there the
  script looks again at the disagreements (`judgekeeper start --review`), says the judge was
  wrong on each, and opens Fix your judge from that page (GET /fix).

Each picture must be under 250 KB; the WebP quality goes down until it is. The servers use
ports 8801 to 8803, and the script stops them and deletes the folder when it is done.
Standard library only, plus judgekeeper itself.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import judgekeeper

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "website" / "assets" / "shots"
LABEL_PORT = 8801  # judgekeeper start
REVIEW_PORT = 8802  # judgekeeper start --review, then Fix your judge
CHROME_PORT = 8803  # Chrome's DevTools
WIDTH, HEIGHT, SCALE = 1440, 900, 2
MAX_BYTES = 250_000
QUALITIES = (85, 82, 78, 74, 70, 65, 60)
MARKED_FIRST = range(12, 21)  # how many answers are marked before the labeling picture
RULE = "Is polite and correct."
MODEL = "openai:gpt-4.1-mini"
NAME = "Polite and correct"
CHROMES = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
           "/Applications/Chromium.app/Contents/MacOS/Chromium")
CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                "chrome")

# The made-up answers: (question, answer, the judge's verdict, the person's mark, the judge's
# reason). The first four are the home page's (HOME). Six times the two disagree.
P, F = "pass", "fail"
ANSWERS = [
    ("How do I reset my password?",
     "Go to Settings, then Security, and choose Reset password. We will email you a link.",
     P, P, "Polite, and the steps are right."),
    ("Can I get a refund after 30 days?",
     "Yes, refunds are always available, whenever you ask.", P, F,
     "Polite and answers the question directly."),
    ("Is my order shipped?",
     "I can't see orders. Check the email we sent you, or your account page.", F, P,
     "Does not answer the question: the order status is not given."),
    ("What is the weight limit for carry-on bags?", "7 kg on all our flights.", P, P,
     "Short and correct."),
    ("How do I change my email address?",
     ("Open Settings, then Account, and edit the Email field. We will send a code to confirm "
     "the new address."), P, P, "Clear steps, polite."),
    ("Can I pay with PayPal?", "Yes. Choose PayPal on the payment page at checkout.", P, P,
     "Correct and polite."),
    ("Do you ship to Canada?", "Yes, we ship to Canada. Delivery takes 5 to 8 working days.",
     P, P, "Answers the question with the delivery time."),
    ("How do I delete my account?",
     "Go to Settings, then Account, and choose Delete account. This cannot be undone.", P, P,
     "Correct steps and a fair warning."),
    ("Why was my card declined?",
     "Your bank declined the payment. Please call your bank or try another card.", P, P,
     "Polite and gives a next step."),
    ("Can I change my seat after booking?",
     "Yes. Open your booking, choose Seats, and pick a new one. Some seats cost extra.", P, P,
     "Correct, and says what may cost extra."),
    ("What are your opening hours?",
     "Our support team is here Monday to Friday, 8am to 6pm.", P, P, "Clear and polite."),
    ("How do I track my parcel?",
     "Open the email we sent when your order shipped and click Track parcel.", P, P,
     "Gives the right steps."),
    ("Is there a student discount?", "Yes, every student gets 50% off everything, forever.",
     P, F, "Friendly and answers yes or no."),
    ("Can I bring my dog on board?",
     ("Small pets in a carrier can travel in the cabin on most flights. Please add your pet "
     "to your booking first."), P, P, "Polite and correct."),
    ("How do I turn on two-step login?",
     ("Go to Settings, then Security, and switch on Two-step login. Then follow the steps on "
     "the screen."), P, P, "Correct steps."),
    ("My app keeps crashing. What should I do?",
     ("Sorry about that. Please update the app to the newest version and restart your phone. "
     "If it still crashes, write to us here."), P, P, "Polite, with clear steps."),
    ("Can I cancel my order?", "You can cancel within 1 hour of ordering, from the Orders page.",
     P, P, "Correct and clear."),
    ("Where can I find my invoice?",
     "Invoices are on the Orders page. Click the order, then Download invoice.", P, P,
     "Correct steps."),
    ("Do you price match?", "We match any price you find anywhere, no questions asked.", P, F,
     "Polite and helpful."),
    ("How long does a refund take?",
     "Refunds reach your account 5 to 10 working days after we get the item back.", P, P,
     "Clear and correct."),
    ("Is the app available in French?",
     "Yes. Open Settings, choose Language, and pick French.", P, P, "Correct steps."),
    ("How do I add a phone number?",
     "Go to Settings, then Account, and choose Add phone number. We will text you a code.",
     P, P, "Correct steps."),
    ("Can I pick up my order in a store?",
     "Not yet. For now we only deliver to your address. Sorry about that.", P, P,
     "Polite and honest."),
    ("What is your phone number?", "Look it up yourself.", F, F, "Rude."),
    ("Can I return a sale item?", "No idea. Ask someone else.", F, F,
     "Rude and does not help."),
    ("How do I update my address?", "Addresses cannot be changed, ever.", F, F,
     "Wrong: the address can be changed in Settings."),
    ("Why is my order late?", "Not our problem. Talk to the courier.", F, F, "Rude."),
    ("Can I get an extra bag on my flight?", "Extra bags are free and unlimited.", F, F,
     "Wrong: extra bags cost a fee."),
    ("How do I log out?", "Why would you want to log out?", F, F, "Does not answer."),
    ("Do you sell gift cards?",
     "Gift cards? We sell gift cards, gift boxes, gift bags and gifts. Gifts, gifts, gifts.",
     F, F, "Does not make sense."),
    ("Is my payment safe?", "Probably. We have not been hacked this week.", F, F,
     "Not reassuring, and not correct."),
    ("How do I talk to a person?", "You can't. I am all you get.", F, F, "Rude and wrong."),
    ("Can I change my delivery date?", "Dates are fixed. Deal with it.", F, F, "Rude."),
    ("How much is the baggage fee?", "It depends.", F, F, "Does not answer."),
    ("Can I use two coupons at once?", "Yes, use as many as you want. They all add up.", F, F,
     "Wrong: one coupon per order."),
    ("My parcel arrived broken.", "That happens. Nothing we can do.", F, F,
     "Rude, and a broken parcel can be replaced."),
    ("How do I stop your emails?", "Just mark them as spam.", F, F, "Not the right way."),
    ("Do you ship on weekends?", "Read the FAQ.", F, F, "Does not answer."),
    ("Can you tell me my account password?",
     "I can't see or share passwords. You can reset yours from the login page.", F, P,
     "Does not give the password the user asked for."),
    ("Can I get a refund for a flight I missed?",
     ("Missed flights are not refunded, but you can still get the airport taxes back. Ask for "
     "them on the Refunds page."), F, P, "Says no refund: not helpful."),
]
HOME = [question for question, *_ in ANSWERS[:4]]
WHY = {  # the person's one line of why, for each disagreement, in the review
    "Can I get a refund after 30 days?": "Made up: refunds end after 30 days.",
    "Is my order shipped?": "Right to say it can't see orders, and it says where to look.",
    "Is there a student discount?": "There is no student discount.",
    "Do you price match?": "We don't price match.",
    "Can you tell me my account password?": "It must never share a password.",
    "Can I get a refund for a flight I missed?": "Correct policy, and polite.",
}


# The sample project -----------------------------------------------------------------------

def make_project(folder: Path) -> None:
    """The support bot's folder, with the judge's verdicts saved by judgekeeper.record()."""
    (folder / "pyproject.toml").write_text(
        '[project]\nname = "support-bot"\nversion = "0.1.0"\n', encoding="utf-8")
    here = Path.cwd()
    os.chdir(folder)  # record() writes under the project the program runs in
    try:
        for question, answer, judge, _mark, reason in ANSWERS:
            judgekeeper.record(input=question, output=answer, verdict=judge, reason=reason,
                               judge=MODEL, rule=RULE, name=NAME, temperature=0)
    finally:
        os.chdir(here)
    if not list((folder / ".judgekeeper" / "records").glob("*.jsonl")):
        raise SystemExit("judgekeeper.record() wrote nothing")


def my_mark(item: dict) -> str:
    """The person's mark for an answer the page shows, found by its text."""
    return next(mark for _q, answer, _j, mark, _r in ANSWERS if answer == item["output"])


def question_of(item: dict) -> str:
    return next(q for q, answer, *_ in ANSWERS if answer == item["output"])


# judgekeeper's own server -----------------------------------------------------------------

class Start:
    """`judgekeeper start` running in the project, with the link it prints."""

    def __init__(self, folder: Path, port: int, *flags: str):
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "NO_COLOR": "1"}
        self.process = subprocess.Popen(
            [sys.executable, "-m", "judgekeeper", "start", "--yes", "--no-browser",
             "--port", str(port), *flags], cwd=folder, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        self.said: list[str] = []
        self.url = self._link()
        threading.Thread(target=self._drain, daemon=True).start()
        parts = urlsplit(self.url)
        self.base = f"{parts.scheme}://{parts.netloc}"
        self.token = parts.query.split("token=", 1)[1]

    def _link(self) -> str:
        for line in self.process.stdout:
            self.said.append(line.rstrip())
            if "http://127.0.0.1:" in line:
                return line[line.index("http://"):].strip()
        raise SystemExit("judgekeeper start printed no link:\n" + "\n".join(self.said))

    def _drain(self) -> None:
        for line in self.process.stdout:
            self.said.append(line.rstrip())

    def address(self, path: str) -> str:
        return f"{self.base}{path}?token={self.token}"

    def get(self, path: str):
        with urllib.request.urlopen(self.address(path), timeout=30) as reply:
            body = reply.read()
        return json.loads(body) if reply.headers.get_content_type() == "application/json" \
            else body

    def post(self, path: str, body: dict) -> dict:
        request = urllib.request.Request(
            self.address(path), data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as reply:
            return json.loads(reply.read())

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)  # Ctrl-C, as a person stops it
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


# Chrome, over its DevTools protocol -------------------------------------------------------

def find_chrome(given: str | None) -> str:
    if given:
        return given
    for path in CHROMES:
        if Path(path).is_file():
            return path
    for name in CHROME_NAMES:
        if shutil.which(name):
            return shutil.which(name)
    raise SystemExit("Chrome not found: pass --chrome PATH")


class Socket:
    """The smallest WebSocket client the DevTools protocol needs: text frames, masked."""

    def __init__(self, url: str):
        parts = urlsplit(url)
        self.sock = socket.create_connection((parts.hostname, parts.port), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        self.sock.sendall((f"GET {parts.path} HTTP/1.1\r\nHost: {parts.netloc}\r\n"
                           "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
                          .encode("ascii"))
        head = b""
        while b"\r\n\r\n" not in head:
            head += self.sock.recv(1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise SystemExit(f"DevTools refused the connection: {head[:200]!r}")

    def _exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("DevTools closed the connection")
            data += chunk
        return data

    def send(self, text: str, opcode: int = 1) -> None:
        payload = text.encode("utf-8")
        n = len(payload)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 1 << 16:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def receive(self) -> str:
        message = b""
        while True:
            first, second = self._exact(2)
            n = second & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._exact(8))[0]
            payload = self._exact(n)
            opcode = first & 0x0F
            if opcode == 9:  # ping
                self.send(payload.decode("utf-8", "replace"), opcode=10)
                continue
            if opcode == 8:
                raise ConnectionError("DevTools closed the connection")
            message += payload
            if first & 0x80:
                return message.decode("utf-8")

    def close(self) -> None:
        self.sock.close()


class Chrome:
    """Headless Chrome with one tab, at 1440 x 900 and twice the pixels."""

    def __init__(self, path: str, profile: Path):
        self.process = subprocess.Popen(
            [path, "--headless=new", f"--remote-debugging-port={CHROME_PORT}",
             f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
             "--hide-scrollbars", "--disable-extensions", f"--window-size={WIDTH},{HEIGHT}",
             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.socket = Socket(self._page_socket())
        self.next_id = 0
        self.call("Page.enable")
        self.call("Page.setBypassCSP", enabled=True)  # so the script's own checks can run
        self.call("Emulation.setDeviceMetricsOverride", width=WIDTH, height=HEIGHT,
                  deviceScaleFactor=SCALE, mobile=False)

    def _page_socket(self) -> str:
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{CHROME_PORT}/json/list",
                                            timeout=2) as reply:
                    pages = [t for t in json.loads(reply.read()) if t.get("type") == "page"]
                if pages:
                    return pages[0]["webSocketDebuggerUrl"]
            except OSError:
                pass
            time.sleep(0.2)
        raise SystemExit("Chrome did not start its DevTools")

    def call(self, method: str, **params) -> dict:
        self.next_id += 1
        self.socket.send(json.dumps({"id": self.next_id, "method": method, "params": params}))
        while True:
            message = json.loads(self.socket.receive())
            if message.get("id") == self.next_id:
                if "error" in message:
                    raise SystemExit(f"{method}: {message['error']}")
                return message["result"]

    def run(self, script: str):
        result = self.call("Runtime.evaluate", expression=script, awaitPromise=True,
                           returnByValue=True)
        if "exceptionDetails" in result:
            raise SystemExit(f"in the page: {result['exceptionDetails']}")
        return result["result"].get("value")

    def visit(self, url: str, settle: float = 1.5) -> None:
        """Go to `url` and wait for it and its fonts, then `settle` seconds for its motion."""
        self.call("Page.navigate", url=url)
        for _ in range(100):
            time.sleep(0.1)
            if self.run("document.readyState") == "complete":
                break
        self.run("document.fonts.ready.then(function () { return true; })")
        time.sleep(settle)

    def shot(self, path: Path) -> tuple[int, int]:
        """Save the viewport as WebP, at the best quality under MAX_BYTES: (bytes, quality)."""
        for quality in QUALITIES:
            data = base64.b64decode(self.call("Page.captureScreenshot", format="webp",
                                              quality=quality)["data"])
            if len(data) < MAX_BYTES:
                break
        else:
            raise SystemExit(f"{path.name} is {len(data):,} bytes even at quality {quality}")
        path.write_bytes(data)
        return len(data), quality

    def close(self) -> None:
        try:
            self.socket.close()
        finally:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()


def webp_size(path: Path) -> tuple[int, int]:
    """The width and height written in a WebP file's header."""
    data = path.read_bytes()[:40]
    kind = data[12:16]
    if kind == b"VP8X":
        return (int.from_bytes(data[24:27], "little") + 1,
                int.from_bytes(data[27:30], "little") + 1)
    if kind == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return (int.from_bytes(data[26:28], "little") & 0x3FFF,
            int.from_bytes(data[28:30], "little") & 0x3FFF)


# The three pictures -----------------------------------------------------------------------

def mark(start: Start, items: list[dict]) -> None:
    for item in items:
        start.post("/label", {"id": item["id"], "label": my_mark(item)})


def label_and_result(chrome: Chrome, folder: Path, out: Path) -> list[Path]:
    """Mark part of the way and take the labeling page; mark the rest and take the result."""
    start = Start(folder, LABEL_PORT)
    try:
        items = start.get("/state")["items"]
        # Stop at one of the home page's questions when the queue has one in reach.
        first = next((n for n in MARKED_FIRST if question_of(items[n]) in HOME),
                     MARKED_FIRST[3])
        mark(start, items[:first])
        chrome.visit(start.url)
        chrome.run("(function () { var ok = document.getElementById('intro-ok');"
                   " if (ok && !document.getElementById('intro').hidden) { ok.click(); }"
                   " return true; })()")  # the first-time card, as a person closes it
        time.sleep(0.8)
        if not chrome.run("document.getElementById('intro').hidden"):
            raise SystemExit("the first-time card is still showing")
        label = out / "label.webp"
        report(label, chrome.shot(label))
        mark(start, items[first:])
        chrome.visit(start.address("/result"), settle=4.0)  # the result draws itself
        result = out / "result.webp"
        report(result, chrome.shot(result))
        return [label, result]
    finally:
        start.stop()


def fix(chrome: Chrome, folder: Path, out: Path) -> list[Path]:
    """Look again at the disagreements, say the judge was wrong, and take Fix your judge."""
    start = Start(folder, REVIEW_PORT, "--review")
    try:
        state = start.get("/state")
        for item in state["items"]:  # step 1: the second look, the same as the first
            start.post("/label", {"id": item["id"], "second": my_mark(item)})
        state = start.get("/state")
        if state["step"] != "b":
            raise SystemExit(f"the review is at step {state['step']!r}, not b")
        for item in state["items"]:  # step 2: the judge was wrong, and why
            start.post("/label", {"id": item["id"], "choice": "judge_wrong"})
            start.post("/label", {"id": item["id"], "why": WHY[question_of(item)]})
        start.get("/fix")  # the review page's link to Fix your judge
        chrome.visit(start.url)
        if chrome.run("document.getElementById('rc').hidden"):
            raise SystemExit("the Change the rule panel is hidden")
        shot = out / "fix.webp"
        report(shot, chrome.shot(shot))
        return [shot]
    finally:
        start.stop()


def report(path: Path, saved: tuple[int, int]) -> None:
    size, quality = saved
    width, height = webp_size(path)
    print(f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: {width} x {height}, "
          f"{size / 1000:.0f} KB (WebP quality {quality})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chrome", help="the Chrome or Chromium program to use")
    ap.add_argument("--out", type=Path, default=OUT, help=f"where to save (default {OUT})")
    args = ap.parse_args(argv)
    chrome_path = find_chrome(args.chrome)
    args.out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="judgekeeper-shots-"))
    folder = work / "support-bot"
    folder.mkdir()
    chrome = None
    try:
        make_project(folder)
        chrome = Chrome(chrome_path, work / "chrome")
        label_and_result(chrome, folder, args.out)
        fix(chrome, folder, args.out)
    finally:
        if chrome is not None:
            chrome.close()
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
