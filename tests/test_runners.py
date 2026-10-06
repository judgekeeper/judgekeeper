from types import SimpleNamespace

import pytest

from judgekeeper.fingerprint import JudgeFingerprint
from judgekeeper.runners import AnthropicRunner, Judgment, OpenAIRunner, ReplayRunner

from .conftest import FIXTURES

PAIRWISE_PROMPT = """---
rubric_version: test-v1
---
{{input}}
Output A: {{output_a}}
Output B: {{output_b}}
"""

SINGLE_PROMPT = """---
rubric_version: single-v1
---
{{input}}
Output: {{output}}
"""

ITEM = {"id": "i1", "input": "q", "output_a": "GOOD", "output_b": "bad", "human_label": "A"}


def test_replay_runner_returns_recorded_judgments():
    runner = ReplayRunner(FIXTURES / "pairwise" / "runs" / "run-01.jsonl")
    j = runner.judge({"id": "i4"})
    assert isinstance(j, Judgment)
    assert j.verdict == "B"
    assert j.rationale == "run1 i4 AB"
    assert j.swapped is not None and j.swapped.verdict == "B"
    assert isinstance(runner.fingerprint, JudgeFingerprint)
    assert runner.fingerprint.model == "claude-haiku-4-5-20251001"


def test_replay_runner_unknown_item():
    runner = ReplayRunner(FIXTURES / "pairwise" / "runs" / "run-01.jsonl")
    with pytest.raises(KeyError):
        runner.judge({"id": "nope"})


class FakeAnthropic:
    """Prefers whichever slot holds the string GOOD; records every prompt it sees."""

    def __init__(self, first_slot_always=False):
        self.calls = []
        self.first_slot_always = first_slot_always
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        text = kwargs["messages"][0]["content"]
        if self.first_slot_always:
            pick = "A"
        else:
            pick = "A" if "Output A: GOOD" in text else "B"
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=f"reasoning\nVerdict: {pick}")],
            model="claude-haiku-4-5-20251001",
        )


def make_prompt(tmp_path, text=PAIRWISE_PROMPT):
    p = tmp_path / "prompt.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_anthropic_runner_judges_both_orderings(tmp_path):
    client = FakeAnthropic()
    runner = AnthropicRunner(
        model="claude-haiku-4-5", prompt_path=make_prompt(tmp_path), temperature=0.0, client=client
    )
    j = runner.judge(ITEM)
    assert len(client.calls) == 2
    assert "Output A: GOOD" in client.calls[0]["messages"][0]["content"]
    assert "Output A: bad" in client.calls[1]["messages"][0]["content"]
    # anthropic>=1 removed the temperature kwarg from messages.create (TypeError); the API
    # still honours it on Haiku 4.5, so it must travel in the request body.
    assert all("temperature" not in c for c in client.calls)
    assert all(c["extra_body"] == {"temperature": 0.0} for c in client.calls)
    assert all(c["model"] == "claude-haiku-4-5" for c in client.calls)
    # both orderings map back to the original label
    assert j.verdict == "A"
    assert j.swapped.verdict == "A"
    assert j.snapshot == "claude-haiku-4-5-20251001"
    fp = runner.fingerprint
    assert fp.provider == "anthropic"
    assert fp.snapshot == "claude-haiku-4-5-20251001"
    assert fp.rubric_version == "test-v1"
    assert fp.temperature == 0.0


def test_anthropic_runner_maps_swapped_first_slot_pick(tmp_path):
    runner = AnthropicRunner(
        model="m", prompt_path=make_prompt(tmp_path), client=FakeAnthropic(first_slot_always=True)
    )
    j = runner.judge(ITEM)
    assert j.verdict == "A"
    assert j.swapped.verdict == "B"


def test_anthropic_runner_single_output(tmp_path):
    class Client(FakeAnthropic):
        def _create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="ok\nVerdict: pass")], model="snap"
            )

    client = Client()
    runner = AnthropicRunner(
        model="m", prompt_path=make_prompt(tmp_path, SINGLE_PROMPT), client=client
    )
    j = runner.judge({"id": "s", "input": "q", "output": "o", "human_label": "pass"})
    assert len(client.calls) == 1
    assert j.verdict == "pass"
    assert j.swapped is None


def test_anthropic_runner_requires_key_without_client(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicRunner(model="m", prompt_path=make_prompt(tmp_path))


def test_openai_runner_judges_both_orderings(tmp_path):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        text = kwargs["messages"][0]["content"]
        pick = "A" if "Output A: GOOD" in text else "B"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=f"Verdict: {pick}"))],
            model="gpt-x-2026-01-01",
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    runner = OpenAIRunner(model="gpt-x", prompt_path=make_prompt(tmp_path), client=client)
    j = runner.judge(ITEM)
    assert len(calls) == 2
    assert j.verdict == "A" and j.swapped.verdict == "A"
    assert runner.fingerprint.provider == "openai"
    assert runner.fingerprint.snapshot == "gpt-x-2026-01-01"


def test_openai_runner_requires_key_without_client(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIRunner(model="m", prompt_path=make_prompt(tmp_path))


# --- redirects (security review, finding 4) -----------------------------------------------------

REDIRECT_KEY = "sentinel-redirect-key-51ab"
SINGLE_ITEM = {"id": "s", "input": "q", "output": "o", "human_label": "pass"}


@pytest.fixture
def gateway_pair():
    """Two local servers: `gateway` answers every POST with a 307 to `other`, which records
    what it receives and answers like the Messages API."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    received = []

    class Quiet(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def _body(self):
            return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    class Other(Quiet):
        def do_POST(self):
            self._body()
            received.append({k.lower(): v for k, v in self.headers.items()})
            body = json.dumps({
                "id": "msg_1", "type": "message", "role": "assistant", "model": "served",
                "content": [{"type": "text", "text": "Verdict: pass"}],
                "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    other = ThreadingHTTPServer(("127.0.0.1", 0), Other)

    class Gateway(Quiet):
        def do_POST(self):
            self._body()
            self.send_response(307)
            # "localhost", not 127.0.0.1: another origin, as a hostile gateway would name.
            self.send_header("Location", f"http://localhost:{other.server_address[1]}{self.path}")
            self.send_header("Content-Length", "0")
            self.end_headers()

    gateway = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    for server in (other, gateway):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    yield SimpleNamespace(url=f"http://127.0.0.1:{gateway.server_address[1]}", received=received)
    for server in (other, gateway):
        server.shutdown()
        server.server_close()


def test_anthropic_runner_does_not_follow_a_redirect_with_the_key(tmp_path, monkeypatch,
                                                                  gateway_pair):
    """The real SDK against a gateway that redirects to another origin: the key stays put."""
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", REDIRECT_KEY)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    runner = AnthropicRunner(model="m", prompt_path=make_prompt(tmp_path, SINGLE_PROMPT),
                             base_url=gateway_pair.url)
    with pytest.raises(RuntimeError, match="redirect") as e:
        runner.judge(SINGLE_ITEM)
    assert gateway_pair.received == []  # nothing, so no x-api-key, reached the other host
    assert "307" in str(e.value) and "127.0.0.1" in str(e.value)
    assert REDIRECT_KEY not in str(e.value)


class _Redirected(Exception):
    """What both SDKs raise for a 3xx they did not follow: an error with the status code."""

    status_code = 307


@pytest.mark.parametrize("make", ["anthropic", "openai"])
def test_runner_reports_a_redirect_as_a_clear_error(tmp_path, make):
    def create(**kwargs):
        raise _Redirected(f"Error code: 307 (sent x-api-key {REDIRECT_KEY})")

    prompt = make_prompt(tmp_path, SINGLE_PROMPT)
    if make == "anthropic":
        runner = AnthropicRunner(model="m", prompt_path=prompt,
                                 client=SimpleNamespace(messages=SimpleNamespace(create=create)))
    else:
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        runner = OpenAIRunner(model="m", prompt_path=prompt, client=client)
    with pytest.raises(RuntimeError, match="does not follow redirects") as e:
        runner.judge(SINGLE_ITEM)
    assert "307" in str(e.value)
    assert REDIRECT_KEY not in str(e.value)
    assert e.value.__cause__ is None  # the SDK's own text is not carried into the message


def test_other_errors_pass_through_unchanged(tmp_path):
    class Denied(Exception):
        status_code = 401

    def create(**kwargs):
        raise Denied("no")

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    runner = OpenAIRunner(model="m", prompt_path=make_prompt(tmp_path, SINGLE_PROMPT),
                          client=client)
    with pytest.raises(Denied):
        runner.judge(SINGLE_ITEM)
