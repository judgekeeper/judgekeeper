"""Install judgekeeper fresh into a new project and walk the whole path a person takes.

    python scripts/install_check.py --tool promptfoo --source build --work /tmp/jk-check
    python scripts/install_check.py --tool table --source pypi:0.2.0 --work /tmp/jk-check
    python scripts/install_check.py --tool promptfoo --via uvx --work /tmp/jk-check

What a stranger does, with nobody at the keyboard and no API key:

1. A project folder with a space in its path, under --work, with its own virtual environment;
   with `--via uvx`, no virtual environment.
2. judgekeeper installed into it: `build` builds the wheel from this checkout and installs that
   (never an editable install); `pypi:VERSION` installs that release from PyPI, trying again
   for up to 10 minutes while a new release spreads. With `--via uvx` nothing is installed in
   the project: every step runs `uvx --from <the wheel or judgekeeper==VERSION> judgekeeper`.
   `judgekeeper --version` must say the version.
3. The eval tool installed into the project, and real results made with it. Every judge talks
   to a fake judge this script serves on 127.0.0.1: an OpenAI-compatible API and Ollama's own,
   which pass questions 1 to 28 and fail 29 to 50, so the numbers are known.
4. The way a person goes: `judgekeeper` (the first look and the page in the background; with
   `--no-browser` its link is printed), every answer marked on the page (25 Pass, 25 Fail),
   `judgekeeper` again for the result, `judgekeeper --stop`; then `judgekeeper start`: the
   review, Fix your judge (the coding-agent prompt, then a new rule saved with --rule-file),
   the new rule put in the tool's own file and the tool run again, Try your new judge, and Ask
   your judge again; then, with the new rule in the results, `check --yes` (the re-check on
   the marks; --yes answers its question about judge calls, as there is no terminal) and the
   report's History. judgekeeper's input is a closed pipe; the pages are used through their
   own HTTP calls, with a stand-in person whose marks are fixed.
5. Every command's output, then "N of N steps OK". Exit 1 on any failed step or "Traceback".

Tools: table, promptfoo, deepeval, inspect, mlflow, record (your own judge code with
judgekeeper.record()), own-format (your own results file, mapped by `judgekeeper`),
promptfoo-ollama and inspect-ollama (an open-source judge on Ollama; no model is downloaded).
`--via uvx` takes only the tools that need no Python package in the project (UVX_TOOLS).

Standard library only. Pages get ports from a free-port search, never judgekeeper's default.
Only the project folder this script made is removed (unless --keep).
"""

from __future__ import annotations

import argparse
import http.server
import importlib.util
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import venv
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS = ("table", "promptfoo", "deepeval", "inspect", "mlflow", "record", "own-format",
         "promptfoo-ollama", "inspect-ollama")
UVX_TOOLS = ("table", "promptfoo", "own-format", "promptfoo-ollama")  # nothing to pip install
WIN = os.name == "nt"
MARKER = ".made-by-install-check"  # only a folder holding this file is ever removed

N = 50
JUDGE_PASSES = frozenset(range(1, 29))  # the fake judge passes 1-28 and fails 29-50
PERSON_PASSES = frozenset(range(1, 23)) | {31, 32, 33}  # the stand-in: 25 Pass, 25 Fail
RULE_OLD = "Pass only if the answer gives the right sum."
RULE_NEW = "Pass only if the answer gives the right sum, written as a number."
WHY = {"pass": "The sum is right.", "fail": "The sum in the answer is wrong."}
OLLAMA_MODEL = "llama3.2:3b"
PLACEHOLDER_KEY = "placeholder-not-a-real-key"
AVOID_PORTS = frozenset({8765, *range(8801, 8811)})
PYPI_WAIT = 600  # seconds to keep trying a new release on PyPI

# What each tool's judge is called, and the reply the fake judge gives it.
MODELS = {"promptfoo": "pf-grader", "deepeval": "gpt-4.1", "inspect": "grader-1",
          "mlflow": "gpt-4.1-mini", "own": "my-judge-1"}
DIALECT = {MODELS["promptfoo"]: "promptfoo", MODELS["deepeval"]: "deepeval",
           MODELS["inspect"]: "inspect", MODELS["mlflow"]: "mlflow"}

# The judge's model, as the "Judge:" line of `judgekeeper` says it, per tool.
JUDGE_NAME = {"table": "my-judge-1", "promptfoo": MODELS["promptfoo"],
              "deepeval": MODELS["deepeval"], "inspect": MODELS["inspect"],
              "mlflow": MODELS["mlflow"], "record": MODELS["own"], "own-format": MODELS["own"],
              "promptfoo-ollama": OLLAMA_MODEL, "inspect-ollama": OLLAMA_MODEL}
# The file the hand-over says the rule is in. A table and a file in your own format hold no
# rule: there a new judge is a new model name in the results.
RULE_FILE = {"promptfoo": "promptfooconfig.yaml", "deepeval": "test_quiz.py",
             "inspect": "quiz.py", "mlflow": "quiz_eval.py", "record": "quiz_judge.py",
             "promptfoo-ollama": "promptfooconfig.yaml", "inspect-ollama": "quiz.py"}
NEW_MODEL = "my-judge-2"
NO_RULE_SAID = "Your results do not say your judge's rule, so judgekeeper can't write a prompt"
OWN_JUDGE = ("table", "record", "own-format")  # asked again through --judge-command
PIP = {"deepeval": ["deepeval"], "inspect": ["inspect-ai", "openai"], "mlflow": ["mlflow"],
       "inspect-ollama": ["inspect-ai", "openai"]}


# The pure parts -------------------------------------------------------------------------------

def question_number(value) -> int:
    """The quiz question an answer, a request or a page item is about (0 when none)."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    m = re.search(r"Question (\d+):", text)
    return int(m.group(1)) if m else 0


def quiz(i: int) -> tuple[str, str]:
    """Question i and the app's answer to it."""
    return f"Question {i}: what is {i} + {i}?", f"The answer is {2 * i}."


def person_mark(item) -> str:
    """The stand-in person's mark for a page item: Pass or Fail by a fixed pattern."""
    return "pass" if question_number(item) in PERSON_PASSES else "fail"


def page_link(text: str) -> tuple[str, str] | None:
    """The page's address and token from judgekeeper's output."""
    m = re.search(r"(http://127\.0\.0\.1:\d+)/\?token=([\w-]+)", text)
    return (m.group(1), m.group(2)) if m else None


def planned_calls(text: str) -> int | None:
    """N from a plan: the `--allow-calls N` it says to add, else its "= N judge calls" line."""
    m = re.search(r"--allow-calls\s+([\d,]+)", text) or re.search(r"=\s*([\d,]+) judge calls",
                                                                  text)
    return int(m.group(1).replace(",", "")) if m else None


def source_version(source: str) -> str:
    """The version `--source` must install: this checkout's for build, else the one named."""
    if source == "build":
        m = re.search(r'(?m)^version\s*=\s*"([^"]+)"',
                      (REPO / "pyproject.toml").read_text(encoding="utf-8"))
        if not m:
            raise SystemExit("no version in pyproject.toml")
        return m.group(1)
    m = re.fullmatch(r"pypi:([0-9][0-9A-Za-z.+!-]*)", source)
    if not m:
        raise SystemExit(f"--source must be build or pypi:VERSION, not {source!r}")
    return m.group(1)


def uvx_command(uvx: str, source: str, wheel: Path | None) -> list[str]:
    """`judgekeeper` run by uvx: from the built wheel, or from the release on PyPI."""
    spec = str(wheel) if source == "build" else f"judgekeeper=={source_version(source)}"
    return [uvx, "--from", spec, "judgekeeper"]


def rule_for(tool: str, rule: str) -> str:
    """The judge's rule as the tool holds it, with the parts the tool needs kept."""
    if tool.startswith("inspect"):
        return rule + " End with GRADE: C or GRADE: I."
    if tool == "mlflow":
        return rule + " Question: {{ inputs }} Answer: {{ outputs }}"
    return rule


def judge_text(dialect: str, ok: bool) -> str:
    """What the fake judge says, in the shape the tool reads."""
    reason = "Checked the sum." if ok else "The sum is not right."
    if dialect == "promptfoo":  # llm-rubric
        return json.dumps({"reason": reason, "pass": ok, "score": 1 if ok else 0})
    if dialect == "inspect":  # model_graded_qa
        return f"{reason}\nGRADE: {'C' if ok else 'I'}"
    if dialect == "deepeval":  # GEval: a 0-10 score
        return json.dumps({"reason": reason, "score": 9 if ok else 1})
    if dialect == "mlflow":  # make_judge
        return json.dumps({"result": "pass" if ok else "fail", "rationale": reason})
    return json.dumps({"verdict": "pass" if ok else "fail", "reason": reason})


def _logprobs(text: str) -> dict:
    tokens = re.findall(r"\d+|\w+|\s+|[^\w\s]", text)
    return {"content": [{"token": t, "logprob": 0.0, "bytes": None,
                         "top_logprobs": [{"token": t, "logprob": 0.0, "bytes": None}]}
                        for t in tokens]}


def fake_reply(path: str, body: dict) -> tuple[int, dict]:
    """The fake judge's HTTP status and JSON reply to one request.

    OpenAI-compatible `/v1/chat/completions` and Ollama's own `/api/chat`, `/api/generate`,
    `/api/tags` and `/api/version`. A chat request about question i passes when i is in
    JUDGE_PASSES. On Ollama's own API the reply is promptfoo's; on the OpenAI API with the
    Ollama model it is Inspect AI's."""
    path = path.split("?", 1)[0].rstrip("/")
    model = str(body.get("model") or "")
    if path.endswith("/api/tags"):
        return 200, {"models": [{"name": OLLAMA_MODEL, "model": OLLAMA_MODEL}]}
    if path.endswith("/api/version"):
        return 200, {"version": "0.0.0"}
    if path.endswith("/models"):
        names = [*MODELS.values(), OLLAMA_MODEL]
        return 200, {"object": "list", "data": [{"id": m, "object": "model"} for m in names]}
    ok = question_number(body) in JUDGE_PASSES
    if path.endswith(("/api/chat", "/api/generate")):
        text = judge_text("promptfoo", ok)
        reply = {"model": model, "created_at": "2026-01-01T00:00:00Z", "done": True,
                 "done_reason": "stop", "total_duration": 1, "prompt_eval_count": 1,
                 "eval_count": 1}
        if path.endswith("/api/chat"):
            reply["message"] = {"role": "assistant", "content": text}
        else:
            reply["response"] = text
        return 200, reply
    if path.endswith("/chat/completions"):
        dialect = "inspect" if model == OLLAMA_MODEL else DIALECT.get(model, "own")
        text = judge_text(dialect, ok)
        choice = {"index": 0, "finish_reason": "stop",
                  "message": {"role": "assistant", "content": text}}
        if body.get("logprobs"):
            choice["logprobs"] = _logprobs(text)
        return 200, {"id": "fake-judge", "object": "chat.completion", "created": 0,
                     "model": model or "fake", "choices": [choice],
                     "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
    return 404, {"error": {"message": f"the fake judge does not serve {path}"}}


def free_port() -> int:
    """A port on 127.0.0.1 that nothing listens on, never judgekeeper's default."""
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port not in AVOID_PORTS:
            return port


# The fake judge's server -----------------------------------------------------------------------

class FakeJudge:
    """Serves fake_reply on 127.0.0.1 in a thread and counts the judge calls."""

    def __init__(self):
        self.calls: list[tuple[str, int]] = []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _reply(self, body: dict):
                status, reply = fake_reply(self.path, body)
                if self.path.split("?")[0].endswith(("/completions", "/api/chat",
                                                     "/api/generate")):
                    owner.calls.append((str(body.get("model")), question_number(body)))
                data = (json.dumps(reply) + "\n").encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    body = {}
                self._reply(body if isinstance(body, dict) else {})

            def do_GET(self):
                self._reply({})

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


# The check ------------------------------------------------------------------------------------

class Check:
    def __init__(self, tool: str, source: str, work: Path, via: str = "venv"):
        self.tool, self.source, self.via = tool, source, via
        self.version = source_version(source)
        self.work = work
        self.project = work / f"{tool} project"
        self.dist = work / f"{tool} wheel"
        self.bin = self.project / ".venv" / ("Scripts" if WIN else "bin")
        if via == "uvx":  # no environment in the project: Python as installed, judgekeeper by uvx
            self.py = Path(sys.executable)
            self.jk = uvx_command(shutil.which("uvx") or "uvx", source, None)
        else:
            self.py = self.bin / ("python.exe" if WIN else "python")
            self.jk = [str(self.bin / ("judgekeeper.exe" if WIN else "judgekeeper"))]
        self.steps: list[tuple[str, bool, str]] = []
        self.judge = FakeJudge()
        self.env = dict(os.environ)
        for name in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH", "CONDA_PREFIX"):
            self.env.pop(name, None)
        url = self.judge.url
        self.env.update({
            "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "OPENAI_BASE_URL": f"{url}/v1", "OPENAI_API_KEY": PLACEHOLDER_KEY,
            "FAKEAI_BASE_URL": f"{url}/v1", "FAKEAI_API_KEY": PLACEHOLDER_KEY,
            # promptfoo reads Ollama's own API at the bare address; Inspect AI its OpenAI one.
            "OLLAMA_BASE_URL": f"{url}/v1" if tool == "inspect-ollama" else url,
            "OLLAMA_HOST": url,
            "DEEPEVAL_TELEMETRY_OPT_OUT": "YES", "DEEPEVAL_GRPC_LOGGING": "NO",
            "PROMPTFOO_DISABLE_TELEMETRY": "1", "PROMPTFOO_DISABLE_UPDATE": "1",
            "PROMPTFOO_DISABLE_SHARING": "1", "PROMPTFOO_REQUEST_BACKOFF_MS": "10",
            "MLFLOW_DISABLE_AGENT_HINT": "1", "MLFLOW_GENAI_EVAL_MAX_WORKERS": "4",
            "INSPECT_DISPLAY": "none", "INSPECT_LOG_LEVEL": "warning",
            "UV_PYTHON": sys.executable, "UV_NO_PROGRESS": "1",
        })
        self.port = free_port()

    # Running things

    def step(self, name: str, ok: bool, detail: str = "") -> bool:
        self.steps.append((name, ok, detail))
        print(f"\n=== {'OK  ' if ok else 'FAIL'} {name} {detail}".rstrip(), flush=True)
        return ok

    def which(self, name: str) -> str:
        return shutil.which(name, path=self.env.get("PATH")) or name

    def run(self, name: str, args, ok_codes=(0,), expect=(), timeout=900, record=True,
            env=None):
        """Run a command in the project with a closed input; check its exit code, that the
        output holds every pattern in `expect`, and that nothing printed a traceback."""
        args = [str(a) for a in args]
        print(f"\n--- {name}: {' '.join(args)}", flush=True)
        try:
            p = subprocess.run(args, check=False, cwd=self.project, input="",
                               capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=timeout, env=env or self.env)
        except subprocess.TimeoutExpired as e:
            out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) \
                else e.stdout or ""
            print(out)
            if record:
                self.step(name, False, f"(still running after {timeout} s)")
            return None
        except OSError as e:
            if record:
                self.step(name, False, f"({type(e).__name__}: {e})")
            return None
        print(p.stdout)
        if p.stderr.strip():
            print("[stderr]\n" + p.stderr[-8000:])
        if record:
            missing = [e for e in expect if not re.search(e, p.stdout)]
            bad = "Traceback" in p.stdout + p.stderr
            detail = f"(exit {p.returncode}"
            detail += "".join(f"; missing: {m}" for m in missing)
            detail += "; traceback)" if bad else ")"
            self.step(name, p.returncode in ok_codes and not missing and not bad, detail)
        return p

    def serve(self, name: str, args, act, expect=(), wait=300) -> bool:
        """Run a command that serves a page, read its link, let `act(base, token)` use the
        page, then wait for the command to end (it stops itself after the last click). Its
        output must hold every pattern in `expect`."""
        args = [str(a) for a in args]
        print(f"\n--- {name}: {' '.join(args)}", flush=True)
        proc = subprocess.Popen(args, cwd=self.project, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", env=self.env)
        proc.stdin.close()
        lines: list[str] = []
        found: list[tuple[str, str]] = []

        def read():
            for line in proc.stdout:
                print(line, end="", flush=True)
                lines.append(line)
                if not found and page_link(line):
                    found.append(page_link(line))

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        deadline = time.monotonic() + wait
        while not found and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.2)
        ok, detail = False, "(no page link)"
        if found:
            try:
                ok, detail = act(*found[0])
            except Exception as e:  # noqa: BLE001 - any failure is this step's failure
                ok, detail = False, f"({type(e).__name__}: {e})"
        try:
            code = proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()  # the page this script started; nothing else is stopped
            proc.wait(timeout=30)
            code, ok, detail = "killed", False, detail + " (still serving after 60 s)"
        reader.join(10)
        out = "".join(lines)
        missing = [e for e in expect if not re.search(e, out)]
        if missing:
            ok, detail = False, detail + "".join(f" (missing: {m})" for m in missing)
        if "Traceback" in out:
            ok, detail = False, detail + " (traceback)"
        self.step(name, ok and code == 0, f"{detail} (exit {code})")
        return ok and code == 0

    def start(self, *flags) -> list[str]:
        return [*self.jk, "start", *flags, "--port", self.port]

    def front(self, *flags, browser: bool = False) -> list[str]:
        """`judgekeeper` with no command; the page's link printed, never a browser (with
        `browser`, the fake one fake_browser makes)."""
        return [*self.jk, *flags, *([] if browser else ["--no-browser"]), "--port", self.port]

    # The page's own HTTP calls

    def call(self, base: str, token: str, path: str, body=None):
        req = urllib.request.Request(f"{base}{path}?token={token}",
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Origin": base})  # as the page sends it
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read().decode("utf-8")
                return json.loads(raw) if r.headers.get_content_type() == "application/json" \
                    else raw
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{path}: HTTP {e.code} {e.read().decode('utf-8', 'replace')}")

    def post_marks(self, base: str, token: str):
        """The stand-in person marks every answer on the page `judgekeeper mark` opened, a few
        seconds each."""
        state = self.call(base, token, "/state")
        for item in state["items"]:
            self.call(base, token, "/label", {"id": item["id"], "label": person_mark(item),
                                              "seconds": 4})
        return True, f"({len(state['items'])} marked)"

    def review(self, base: str, token: str):
        """Step 1: a second look at each answer, the judge hidden. Step 2: on each
        disagreement, "Your judge was wrong", with a why."""
        state = self.call(base, token, "/state")
        for item in state["items"]:
            self.call(base, token, "/label", {"id": item["id"], "second": person_mark(item)})
        state = self.call(base, token, "/state")
        shown = len(state["items"])
        for item in state["items"]:
            self.call(base, token, "/label", {"id": item["id"], "choice": "judge_wrong"})
            self.call(base, token, "/label", {"id": item["id"], "why": WHY[person_mark(item)]})
        after = self.call(base, token, "/state")
        self.call(base, token, "/result")
        return after.get("step") == "done", f"({shown} disagreements; step {after.get('step')})"

    # Installing

    def make_project(self):
        for folder in (self.project, self.dist):
            remove_own(folder)
            folder.mkdir(parents=True)
            (folder / MARKER).write_text("", encoding="utf-8")
        if self.via == "uvx":
            self.step("project with no virtual environment (uvx)",
                      not (self.project / ".venv").exists())
            return
        venv.create(self.project / ".venv", with_pip=True)
        self.env["VIRTUAL_ENV"] = str(self.project / ".venv")
        self.env["PATH"] = str(self.bin) + os.pathsep + self.env.get("PATH", "")
        self.step("project with its own virtual environment", self.py.is_file(),
                  f"({self.project})")

    def wait_for_pypi(self, name: str, cmd: list) -> bool:
        """Run cmd until it works: a new release takes a few minutes to reach every mirror."""
        deadline = time.monotonic() + PYPI_WAIT
        while True:
            p = self.run(name, cmd, timeout=600, record=False)
            if p and p.returncode == 0:
                return self.step(name, True)
            if time.monotonic() > deadline:
                return self.step(name, False, f"(not installable after {PYPI_WAIT} s)")
            print("Not on PyPI yet; trying again in 30 s.", flush=True)
            time.sleep(30)

    def install(self) -> bool:
        if self.source == "build":
            if importlib.util.find_spec("build"):
                cmd = [sys.executable, "-m", "build", "--wheel", "--outdir", self.dist, REPO]
            elif shutil.which("uv"):
                cmd = [shutil.which("uv"), "build", "--wheel", "--out-dir", self.dist, REPO]
            else:
                return self.step("build the wheel", False,
                                 "(needs `pip install build`, or uv on the PATH)")
            if not self.run("build the wheel from this checkout", cmd, timeout=600):
                return False
            wheels = sorted(self.dist.glob("judgekeeper-*.whl"))
            if not self.step("one wheel built", len(wheels) == 1,
                             f"({[w.name for w in wheels]})"):
                return False
            if self.via == "uvx":
                self.jk = uvx_command(self.jk[0], self.source, wheels[0])
            else:
                p = self.run("install the wheel", [self.py, "-m", "pip", "install", wheels[0]],
                             timeout=600)
                if not p or p.returncode:
                    return False
        elif self.via == "uvx":
            if not self.wait_for_pypi(f"uvx judgekeeper=={self.version} from PyPI",
                                      [self.jk[0], "--refresh", *self.jk[1:], "--version"]):
                return False
        elif not self.wait_for_pypi(f"install judgekeeper=={self.version} from PyPI",
                                    [self.py, "-m", "pip", "install", "--no-cache-dir",
                                     f"judgekeeper=={self.version}"]):
            return False
        p = self.run("judgekeeper --version", [*self.jk, "--version"],
                     expect=[rf"^judgekeeper {re.escape(self.version)}\s*$"])
        if not p or p.returncode:
            return False
        if self.tool in PIP:
            p = self.run(f"install {', '.join(PIP[self.tool])}",
                         [self.py, "-m", "pip", "install", *PIP[self.tool]], timeout=1200)
            if not p or p.returncode:
                return False
        if self.tool.startswith("promptfoo"):
            p = self.run("install promptfoo with npm, into the project",
                         [self.which("npm"), "install", "--no-audit", "--no-fund",
                          "promptfoo"], timeout=900)
            if not p or p.returncode:
                return False
            self.run("npx promptfoo --version", [self.which("npx"), "promptfoo", "--version"])
        if self.tool in PIP:
            names = [n.replace("-", "_") for n in PIP[self.tool]]
            code = f"import importlib.metadata as m; print(*[(n, m.version(n)) for n in {names}])"
            self.run("the tool's version", [self.py, "-c", code], record=False)
        return True

    # The tools: make results with the judge's rule

    def write(self, name: str, text: str):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def make_results(self, rule: str, label: str):
        before = len(self.judge.calls)
        make = {"table": self.make_table, "promptfoo": self.make_promptfoo,
                "deepeval": self.make_deepeval, "inspect": self.make_inspect,
                "mlflow": self.make_mlflow, "record": self.make_record,
                "own-format": self.make_own_format, "promptfoo-ollama": self.make_promptfoo,
                "inspect-ollama": self.make_inspect}
        if self.tool == "table":
            self.write_own_judge(rule)  # the judge that made the table, for --judge-command
        make[self.tool](rule_for(self.tool, rule), label)
        if self.tool != "table":
            made = len(self.judge.calls) - before
            self.step(f"the judge was called ({label})", made > 0, f"({made} calls)")
        time.sleep(1.5)  # the next results get a later time

    def make_table(self, rule: str, label: str):
        model = MODELS["own"] if rule == RULE_OLD else NEW_MODEL
        lines = ["input,output,verdict,judge_model"]
        for i in range(1, N + 1):
            q, a = quiz(i)
            lines.append(f'"{q}","{a}",{"pass" if i in JUDGE_PASSES else "fail"},{model}')
        self.write("results.csv", "\n".join(lines) + "\n")
        self.step(f"results.csv written ({label})", True)

    def make_promptfoo(self, rule: str, label: str):
        grader = (f"ollama:chat:{OLLAMA_MODEL}" if self.tool == "promptfoo-ollama"
                  else f"openai:chat:{MODELS['promptfoo']}")
        tests = "\n".join(f"  - vars:\n      question: {json.dumps(quiz(i)[0])}\n"
                          f"      answer: {json.dumps(quiz(i)[1])}" for i in range(1, N + 1))
        self.write("promptfooconfig.yaml",
                   "description: quiz bot\nprompts:\n  - \"{{question}} {{answer}}\"\n"
                   "providers:\n  - echo\ndefaultTest:\n  assert:\n    - type: llm-rubric\n"
                   f"      value: {json.dumps(rule)}\n      provider: {grader}\n"
                   f"tests:\n{tests}\n")
        self.run(f"npx promptfoo eval ({label})",
                 [self.which("npx"), "promptfoo", "eval", "-c", "promptfooconfig.yaml", "-o",
                  "results.json", "--no-cache", "--no-share"], ok_codes=(0, 100))

    def make_deepeval(self, rule: str, label: str):
        self.write("test_quiz.py", f'''import pytest
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase

try:
    from deepeval.test_case import SingleTurnParams as Params
except ImportError:  # DeepEval before 4
    from deepeval.test_case import LLMTestCaseParams as Params

correctness = GEval(name="Correctness", evaluation_steps=[{rule!r}],
                    evaluation_params=[Params.INPUT, Params.ACTUAL_OUTPUT],
                    model={MODELS["deepeval"]!r}, threshold=0.5)


@pytest.mark.parametrize("i", range(1, {N} + 1))
def test_quiz(i):
    case = LLMTestCase(input=f"Question {{i}}: what is {{i}} + {{i}}?",
                       actual_output=f"The answer is {{2 * i}}.")
    assert_test(case, [correctness])
''')
        self.env["DEEPEVAL_RESULTS_FOLDER"] = "results"
        try:
            self.run(f"deepeval test run ({label})",
                     [self.bin / ("deepeval.exe" if WIN else "deepeval"), "test", "run",
                      "test_quiz.py"], ok_codes=(0, 1))
        finally:
            self.env.pop("DEEPEVAL_RESULTS_FOLDER")

    def make_inspect(self, rule: str, label: str):
        grader = (f"ollama/{OLLAMA_MODEL}" if self.tool == "inspect-ollama"
                  else f"openai-api/fakeai/{MODELS['inspect']}")
        self.write("quiz.py", f'''from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import model_graded_qa
from inspect_ai.solver import generate

task = Task(
    dataset=[Sample(id=i, input=f"Question {{i}}: what is {{i}} + {{i}}?", target=str(2 * i))
             for i in range(1, {N} + 1)],
    solver=generate(),
    scorer=model_graded_qa(instructions={rule!r}),
)
app = get_model("mockllm/model", custom_outputs=[
    ModelOutput.from_content("mockllm/model", f"The answer is {{2 * i}}.")
    for i in range(1, {N} + 1)])

if __name__ == "__main__":
    eval(task, model=app, model_roles={{"grader": {grader!r}}}, max_samples=1,
         log_dir="logs", display="none")
''')
        self.run(f"inspect eval ({label})", [self.py, "quiz.py"])

    def make_mlflow(self, rule: str, label: str):
        self.write("quiz_eval.py", f'''import mlflow
from mlflow.genai.judges import make_judge

mlflow.set_tracking_uri("sqlite:///mlflow.db")
mlflow.set_experiment("quiz bot")

correctness = make_judge(
    name="sum_check",
    instructions={rule!r},
    model="openai:/{MODELS["mlflow"]}",
)
data = [{{"inputs": {{"question": f"Question {{i}}: what is {{i}} + {{i}}?"}},
          "outputs": f"The answer is {{2 * i}}."}} for i in range(1, {N} + 1)]

if __name__ == "__main__":
    mlflow.genai.evaluate(data=data, scorers=[correctness])
''')
        self.run(f"mlflow.genai.evaluate ({label})", [self.py, "quiz_eval.py"])

    def write_own_judge(self, rule: str):
        """The judge in your own code: `quiz_judge.py` asks the fake judge with the rule.
        Your app and your judge command both import it, as they would in a real project."""
        self.write("quiz_judge.py", f'''import json
import urllib.request

RULE = {rule!r}
JUDGE = {self.judge.url + "/v1/chat/completions"!r}


def judge(question, answer):
    body = json.dumps({{"model": {MODELS["own"]!r}, "messages": [
        {{"role": "system", "content": RULE}},
        {{"role": "user", "content": f"{{question}}\\n{{answer}}"}}]}}).encode()
    request = urllib.request.Request(JUDGE, data=body,
                                     headers={{"Content-Type": "application/json"}})
    with urllib.request.urlopen(request, timeout=60) as reply:
        said = json.loads(json.loads(reply.read())["choices"][0]["message"]["content"])
    return said["verdict"], said["reason"]
''')
        # The --exec contract: one answer as JSON on stdin, the verdict as JSON on stdout.
        self.write("judge_command.py", '''import json
import sys

from quiz_judge import judge

answer = json.load(sys.stdin)
verdict, reason = judge(answer["input"], answer["output"])
print(json.dumps({"verdict": verdict, "reason": reason}))
''')

    def make_record(self, rule: str, label: str):
        self.write_own_judge(rule)
        self.write("quiz_app.py", f'''import judgekeeper

from quiz_judge import RULE, judge

for i in range(1, {N} + 1):
    question, answer = f"Question {{i}}: what is {{i}} + {{i}}?", f"The answer is {{2 * i}}."
    verdict, reason = judge(question, answer)
    judgekeeper.record(input=question, output=answer, verdict=verdict, reason=reason,
                       judge={MODELS["own"]!r}, rule=RULE, name="Correctness")
''')
        self.run(f"the quiz app with judgekeeper.record() ({label})", [self.py, "quiz_app.py"])
        files = list((self.project / ".judgekeeper" / "records").glob("*.jsonl"))
        self.step(f"record() saved the decisions ({label})", bool(files),
                  f"({len(files)} files)")

    def make_own_format(self, rule: str, label: str):
        self.write_own_judge(rule)
        model = MODELS["own"] if rule == RULE_OLD else NEW_MODEL
        self.write("quiz_app.py", f'''import json
import time

from quiz_judge import judge

cases = []
for i in range(1, {N} + 1):
    question, answer = f"Question {{i}}: what is {{i}} + {{i}}?", f"The answer is {{2 * i}}."
    verdict, reason = judge(question, answer)
    cases.append({{"case": f"q{{i}}", "prompt": {{"user_question": question}},
                   "reply": {{"bot_answer": answer}},
                   "grading": {{"verdict": verdict, "explanation": reason}}}})
results = {{"finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "judge": {{"model": {model!r}}}, "cases": cases}}
with open("evals/quiz-results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=1)
''')
        (self.project / "evals").mkdir(exist_ok=True)
        self.run(f"the quiz app saves its own results file ({label})",
                 [self.py, "quiz_app.py"])

    # The user's path

    def mark_path(self):
        """`judgekeeper` finds the judge, checks it and opens the page in the background (its
        link printed: no browser, no terminal); the stand-in person marks on it; `judgekeeper`
        then prints the result; `--stop` closes the page. For a file in your own format the
        first run maps it (answers given by --yes) and goes on: it is the first look."""
        decisions = (rf"Your judge's grades: {len(JUDGE_PASSES)} Pass, "
                     rf"{N - len(JUDGE_PASSES)} Fail\.")
        # Started by uvx, every Next: line names `uvx judgekeeper@<version>` (it may wrap).
        uvx = [r"Next: [^`]*`uvx judgekeeper@"] if self.via == "uvx" else []
        expect = [r"Step 1 of 5: Find", rf"Judge: .*{re.escape(JUDGE_NAME[self.tool])}",
                  decisions, r"Step 2 of 5: Mark",
                  r"Open this link in your browser to mark answers:\s+http://127\.0\.0\.1:",
                  *uvx]
        if self.tool == "own-format":
            p = self.mark_step("1. judgekeeper maps the file (answers given by --yes, no "
                               "terminal): the first look, and the page in the background",
                               self.front("--yes"), [r"Saved judgekeeper\.toml", *expect])
            self.step("judgekeeper.toml saved", (self.project / "judgekeeper.toml").is_file())
        else:
            p = self.mark_step("1. judgekeeper: the first look, and the page in the background",
                               self.front(), expect)
        link = page_link(p.stdout) if p else None
        if not self.step("2. the page's link is printed", link is not None):
            return
        try:
            ok, detail = self.post_marks(*link)
        except Exception as e:  # noqa: BLE001 - any failure is this step's failure
            ok, detail = False, f"({type(e).__name__}: {e})"
        self.step("2. the stand-in person marks every answer on the page", ok, detail)
        self.mark_step("2. judgekeeper prints the result", self.front(),
                       [r"Your marks: 50 \(25 Pass, 25 Fail\), made on the page",
                        r"Of the answers you passed, your judge passed",
                        r"Of the answers you failed, your judge failed",
                        r"Step 3 of 5: Measure", *uvx])
        self.mark_step("2. judgekeeper --stop closes the page", [*self.jk, "--stop"],
                       [r"Closed the marking page"])

    def recheck(self):
        """The new rule is in the results: `check --yes` re-tests it on the marks, and the
        report holds the check."""
        self.run("7. check re-tests the new judge on the marks", [*self.jk, "check", "--yes"],
                 expect=[r"Re-checked on (your 50|\d+ of your 50) marks",
                         r"Answers you passed:", r"Answers you failed:"])
        report = self.project / ".judgekeeper" / "report.html"
        try:
            html = report.read_text(encoding="utf-8")
        except OSError:
            html = ""
        self.step("7. report.html has the check in its History", "<h3>History</h3>" in html)

    def mark_step(self, name: str, args, expect, env=None):
        """A step that opens or closes the page; when it fails, what the page's own process
        wrote to .judgekeeper/page.log, and whether its lock is still there."""
        p = self.run(name, args, expect=expect, env=env)
        if self.steps and not self.steps[-1][1]:
            folder = self.project / ".judgekeeper"
            try:
                log = (folder / "page.log").read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                log = f"(not readable: {type(e).__name__})"
            print(f"\n--- .judgekeeper/page.log\n{log[-8000:] or '(empty)'}", flush=True)
            print(f"--- .judgekeeper/server.json is there: {(folder / 'server.json').exists()}",
                  flush=True)
        return p

    def plan_then_go(self, name: str, flags: list[str]) -> bool:
        """Run a step that asks before spending: once for its plan (it stops, exit 8), then
        with --allow-calls N, N read from the plan."""
        # MLflow's own judge is a make_judge, never one of MLflow's built-in judges.
        expect = [r"judge calls", *([r"make_judge"] if self.tool == "mlflow" else [])]
        plan = self.run(f"{name}: the plan", self.start(*flags, "--no-browser"),
                        ok_codes=(8,), expect=expect)
        n = planned_calls(plan.stdout) if plan else None
        if not self.step(f"{name}: N read from the plan", n is not None, f"(N = {n})"):
            return False
        if self.tool.endswith("ollama"):
            for line in ("Your judge runs on Ollama; it needs no key.",
                         "Free: it runs on your computer."):
                self.step(f"{name}: the plan says {line!r}", line in plan.stdout)
        before = len(self.judge.calls)
        p = self.run(f"{name}: --allow-calls {n}",
                     self.start(*flags, "--allow-calls", n, "--no-browser"))
        made = len(self.judge.calls) - before
        self.step(f"{name}: the judge was called", made > 0, f"({made} calls)")
        return bool(p and p.returncode == 0)

    def walk(self):
        self.make_results(RULE_OLD, "old rule")
        self.mark_path()
        self.run("2. start: the last result and what next", self.start("--no-browser"),
                 ok_codes=(0, 8), expect=[r"Your last result", r"--review"])
        self.serve("3. review the disagreements (start --review --yes)",
                   self.start("--review", "--no-browser", "--yes"), self.review)

        if self.tool not in RULE_FILE:  # no rule in the results: nothing to write a prompt for
            self.run("4. Fix your judge in the terminal (start --fix --no-browser)",
                     self.start("--fix", "--no-browser"),
                     expect=[r"Passed, but you said Fail", NO_RULE_SAID])
            print("These results hold no rule, so there is no agent prompt and no rule to save.")
        else:
            self.fix_rule()

        # What a coding agent does with the hand-over: the new rule in the tool's own file.
        self.make_results(RULE_NEW, "new rule")
        extra = (["--judge-command", "python judge_command.py"] if self.tool in OWN_JUDGE
                 else ["--fields", "input,actual_output"] if self.tool == "deepeval" else [])
        self.plan_then_go("5. try your new judge", ["--try-new-judge", *extra])
        self.plan_then_go("6. ask your judge again", ["--ask-again", "--times", "1", *extra])
        self.recheck()

    def fix_rule(self):
        """Fix your judge as a coding agent does: the terminal's prompt, then a new rule
        saved with --rule-file, and the hand-over that says where it goes."""
        fix = self.run("4. Fix your judge in the terminal (start --fix --no-browser)",
                       self.start("--fix", "--no-browser"),
                       expect=[r"paste this:", r"--rule-file"])
        agent_text = fix.stdout.split("paste this:")[-1] if fix else ""
        self.step("4. the agent prompt holds no answer text",
                  bool(fix) and "The answer is" not in agent_text
                  and (self.project / ".judgekeeper" / "fix" / "prompt.txt").is_file())
        rule_file = self.project / ".judgekeeper" / "fix" / "agent-rule.txt"
        rule_file.parent.mkdir(parents=True, exist_ok=True)
        rule_file.write_text(rule_for(self.tool, RULE_NEW) + "\n", encoding="utf-8")
        self.run("4. save a hand-written rule (start --fix --rule-file)",
                 self.start("--fix", "--rule-file", rule_file.relative_to(self.project)),
                 expect=[r"Saved"])
        try:
            meta = json.loads((self.project / ".judgekeeper" / "fix" / "rule.json")
                              .read_text(encoding="utf-8"))
            where = json.dumps(meta.get("hand_over"))
        except (OSError, ValueError) as e:
            where = f"{type(e).__name__}: {e}"
        self.step(f"4. the hand-over says the rule is in {RULE_FILE[self.tool]}",
                  RULE_FILE[self.tool] in where, f"({where[:300]})")

    def summary(self) -> int:
        print("\n\n==================== SUMMARY ====================")
        print(f"{self.tool} via {self.via} on {sys.platform}, Python {sys.version.split()[0]}, "
              f"judgekeeper {self.version} ({self.source}); fake judge calls: "
              f"{len(self.judge.calls)}")
        for name, ok, detail in self.steps:
            print(f"{'OK  ' if ok else 'FAIL'}  {name} {detail}".rstrip())
        failed = [s for s in self.steps if not s[1]]
        print(f"{len(self.steps) - len(failed)} of {len(self.steps)} steps OK")
        return 1 if failed else 0


def remove_own(folder: Path):
    """Remove a folder this script made (it holds MARKER); refuse any other."""
    if not folder.exists():
        return
    if not (folder / MARKER).is_file():
        raise SystemExit(f"{folder} exists and was not made by this script; "
                         "choose another --work folder.")

    def writable(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)

    if sys.version_info >= (3, 12):
        shutil.rmtree(folder, onexc=writable)
    else:
        shutil.rmtree(folder, onerror=writable)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tool", required=True, choices=TOOLS)
    parser.add_argument("--source", default="build", help="build, or pypi:VERSION")
    parser.add_argument("--work", required=True, type=Path,
                        help="the folder the project is made in")
    parser.add_argument("--via", choices=("venv", "uvx"), default="venv",
                        help="venv: install into the project's environment; uvx: run by uvx")
    parser.add_argument("--keep", action="store_true", help="keep the project folder")
    args = parser.parse_args(argv)
    if args.via == "uvx" and args.tool not in UVX_TOOLS:
        parser.error(f"--via uvx needs a tool with nothing to install in the project: "
                     f"{', '.join(UVX_TOOLS)}")
    # This script's own printing; judgekeeper's output is its own process's.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    check = Check(args.tool, args.source, args.work.resolve(), args.via)
    print(f"{args.tool} via {args.via} on {sys.platform}; project: {check.project}; "
          f"fake judge at {check.judge.url}; pages on port {check.port}", flush=True)
    try:
        check.make_project()
        if check.install():
            check.walk()
    finally:
        check.judge.stop()
    code = check.summary()
    if not args.keep:
        for folder in (check.project, check.dist):
            if folder is None:
                continue
            try:
                remove_own(folder)
            except OSError as e:
                print(f"Could not remove {folder}: {e}")
    return code


if __name__ == "__main__":
    sys.exit(main())
