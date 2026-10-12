"""The Langfuse reader: Langfuse's public API in, ScoreRecords out.

Checked against recorded responses built from Langfuse's published OpenAPI definitions, not a
live server (see tests/fixtures/langfuse/make_responses.py for the commit and the numbers):
7 judge scores (trace-1 to trace-7) and 6 human scores (trace-1 to trace-6), one run.
A local stub server (tests/langfuse_stub.py) answers the requests; time is faked, so the rate
limit and the 429 back-off never sleep for real.
"""

import base64
import hashlib

import pytest

from judgekeeper.anchors import canonical_json
from judgekeeper.readers import langfuse_api
from judgekeeper.records import RecordsError, fingerprint_known
from judgekeeper.table import make_fingerprint
from tests.langfuse_stub import LangfuseStub, load, score_pages

PUBLIC, SECRET = "pk-lf-fixture-public-0001", "sk-lf-fixture-secret-0002"
BASIC = base64.b64encode(f"{PUBLIC}:{SECRET}".encode()).decode()


class FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    t = FakeTime()
    monkeypatch.setattr(langfuse_api, "_clock", t.clock)
    monkeypatch.setattr(langfuse_api, "_sleep", t.sleep)
    return t


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", PUBLIC)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", SECRET)
    for name in ("LANGFUSE_BASE_URL", "LANGFUSE_HOST"):
        monkeypatch.delenv(name, raising=False)


def read(stub, monkeypatch, judge="helpfulness", human="helpfulness_human", **options):
    monkeypatch.setenv("LANGFUSE_HOST", stub.url)
    if not {"from_", "to", "max_items"} & set(options):
        options["from_"] = "2026-09-01"
    return langfuse_api.read_langfuse(judge, human, **options)


def judge_fingerprint(records):
    rec = next(r for r in records if r.annotator_kind == "LLM")
    return make_fingerprint(fingerprint_known(rec.evaluator))


def test_reads_the_judge_and_human_scores(keys, clock, monkeypatch):
    with LangfuseStub() as stub:
        label, records = read(stub, monkeypatch)
    assert label == "langfuse 127.0.0.1"
    assert records.ids_derived is False
    judge = {r.target_id: r for r in records if r.annotator_kind == "LLM"}
    human = {r.target_id: r.label for r in records if r.annotator_kind == "HUMAN"}
    assert sorted(judge) == [f"trace-{n}" for n in range(1, 8)]
    assert human == {f"trace-{n}": "pass" if n <= 3 else "fail" for n in range(1, 7)}
    assert judge["trace-1"].score == 0.9 and judge["trace-1"].label is None
    assert judge["trace-1"].explanation == "The answer covers most of the question."
    assert all(r.run is None for r in records)  # one run
    assert any("one run" in n for n in records.notes)
    fp = judge_fingerprint(records)
    assert (fp.provider, fp.model, fp.rubric_version) == ("openai", "gpt-4.1-mini", "3")
    prompt = load("evaluators.json")["data"][1]["prompt"]
    assert fp.prompt_hash == hashlib.sha256(canonical_json(prompt).encode()).hexdigest()
    assert fp.temperature is None  # Langfuse stores none


def test_requests_are_read_only_paged_and_authenticated(keys, clock, monkeypatch):
    with LangfuseStub() as stub:
        read(stub, monkeypatch, from_="2026-09-01", to="2026-10-01T12:00:00Z")
    scores = stub.score_requests()
    assert len(scores) == 3
    assert [q.get("cursor") for _, q, _ in scores] == [None, "eyJwYWdlIjoyfQ",
                                                       "eyJwYWdlIjozfQ"]
    q = scores[0][1]
    assert q["limit"] == "100"
    assert q["fields"] == "details,subject,annotation"
    assert q["name"] == "helpfulness,helpfulness_human"
    assert q["fromTimestamp"] == "2026-09-01T00:00:00Z"
    assert q["toTimestamp"] == "2026-10-01T12:00:00Z"
    evaluators = [r for r in stub.requests if r[0] == "/api/public/v2/evaluators"]
    assert len(evaluators) == 1  # one call
    assert len(stub.requests) == 4
    for _, _, headers in stub.requests:
        assert headers["Authorization"] == f"Basic {BASIC}"


def test_requests_are_spaced_to_the_rate(keys, clock, monkeypatch):
    with LangfuseStub() as stub:
        read(stub, monkeypatch)
    assert clock.sleeps == pytest.approx([2.0, 2.0, 2.0])  # 30 a minute: 4 requests
    clock.sleeps.clear()
    with LangfuseStub() as stub:
        read(stub, monkeypatch, rate=120)
    assert clock.sleeps == pytest.approx([0.5, 0.5, 0.5])


def test_429_backs_off_for_retry_after_then_succeeds(keys, clock, monkeypatch):
    with LangfuseStub(rate_limited=2, retry_after="7") as stub:
        _, records = read(stub, monkeypatch, rate=6000)
    assert len(stub.score_requests()) == 5  # two 429s, then three pages
    assert clock.sleeps.count(7.0) == 2
    assert len(records) == 13


def test_429_without_end_gives_up(keys, clock, monkeypatch):
    with (LangfuseStub(rate_limited=100, retry_after="1") as stub,
          pytest.raises(langfuse_api.LangfuseError, match="429")):
        read(stub, monkeypatch)
    assert len(stub.score_requests()) == langfuse_api.MAX_RETRIES + 1


def test_evaluator_with_default_model(keys, clock, monkeypatch):
    with LangfuseStub(evaluators=load("evaluators-default-model.json")) as stub:
        _, records = read(stub, monkeypatch)
    fp = judge_fingerprint(records)
    assert fp.model is None and fp.provider is None
    assert fp.prompt_hash is not None  # the prompt is still known
    assert any("modelConfig is null" in n for n in records.notes)


def test_no_matching_evaluator(keys, clock, monkeypatch):
    with LangfuseStub(evaluators={"data": [], "meta": {}}) as stub:
        _, records = read(stub, monkeypatch)
    fp = judge_fingerprint(records)
    assert fp.model is None and fp.prompt_hash is None and fp.rubric_version is None
    assert any("no evaluator named 'helpfulness'" in n for n in records.notes)


def test_source_that_disagrees_with_the_mapping_is_noted(keys, clock, monkeypatch):
    pages = score_pages()
    pages[0]["data"][0]["source"] = "ANNOTATION"  # a judge score a person entered
    with LangfuseStub(pages=pages) as stub:
        _, records = read(stub, monkeypatch)
    assert any("1 'helpfulness' score has source ANNOTATION" in n for n in records.notes)
    # trace-5's human score came through the API: ambiguous, not a disagreement
    assert not any("'helpfulness_human'" in n and "API" in n for n in records.notes)


def test_judge_and_human_with_one_name_split_by_source(keys, clock, monkeypatch):
    pages = score_pages()
    for p in pages:
        for s in p["data"]:
            if s["name"] == "helpfulness_human":
                s["name"] = "helpfulness"
                s["source"] = "ANNOTATION"
    with LangfuseStub(pages=pages) as stub:
        _, records = read(stub, monkeypatch, human="helpfulness", max_items=100)
    assert sum(r.annotator_kind == "LLM" for r in records) == 7
    assert sum(r.annotator_kind == "HUMAN" for r in records) == 6
    assert any("source ANNOTATION" in n for n in records.notes)


def test_max_items_stops_paging(keys, clock, monkeypatch):
    with LangfuseStub() as stub:
        _, records = read(stub, monkeypatch, max_items=7)
    assert len(stub.score_requests()) == 2
    assert "fromTimestamp" not in stub.score_requests()[0][1]
    assert any("--max-items 7" in n for n in records.notes)


def test_a_window_or_max_items_is_required(keys, clock, monkeypatch):
    with LangfuseStub() as stub:
        monkeypatch.setenv("LANGFUSE_HOST", stub.url)
        with pytest.raises(RecordsError, match="--max-items"):
            langfuse_api.read_langfuse("helpfulness", "helpfulness_human")
    assert not stub.requests


@pytest.mark.parametrize("window", [{"from_": "yesterday"}, {"to": "2026-13-01"},
                                    {"from_": "2026-10-02", "to": "2026-10-01"},
                                    {"max_items": 0}])
def test_bad_window_is_an_error(keys, clock, monkeypatch, window):
    with LangfuseStub() as stub, pytest.raises(RecordsError):
        read(stub, monkeypatch, **window)
    assert not stub.requests


def test_missing_keys_are_an_error(clock, monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", SECRET)
    with (LangfuseStub() as stub,
          pytest.raises(RecordsError, match="LANGFUSE_PUBLIC_KEY") as e):
        read(stub, monkeypatch)
    assert not stub.requests
    assert SECRET not in str(e.value)


def test_default_host_is_the_eu_cloud(keys):
    assert langfuse_api.host_from_env() == "https://cloud.langfuse.com"


def test_base_url_wins_over_host(keys, monkeypatch):
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com")
    monkeypatch.setenv("LANGFUSE_HOST", "https://other.example.com")
    assert langfuse_api.host_from_env() == "https://us.cloud.langfuse.com"


@pytest.mark.parametrize("host", ["ftp://langfuse.example.com",
                                  "https://user:pw@langfuse.example.com"])
def test_bad_host_is_an_error(keys, monkeypatch, host):
    monkeypatch.setenv("LANGFUSE_HOST", host)
    with pytest.raises(RecordsError) as e:
        langfuse_api.read_langfuse("a", "b", max_items=5)
    assert "pw" not in str(e.value)


def test_cross_host_redirect_is_refused(keys, clock, monkeypatch):
    with LangfuseStub() as other:
        # 127.0.0.1 and localhost are different hosts: the credentials must not follow
        target = other.url.replace("127.0.0.1", "localhost")
        with (LangfuseStub(redirect_to=target) as stub,
              pytest.raises(langfuse_api.LangfuseError, match="redirect") as e):
            read(stub, monkeypatch)
    assert len(stub.requests) == 1
    assert not other.requests
    assert SECRET not in str(e.value) and BASIC not in str(e.value)


def test_http_error_never_echoes_credentials(keys, clock, monkeypatch):
    with LangfuseStub(status=401) as stub, pytest.raises(langfuse_api.LangfuseError) as e:
        read(stub, monkeypatch)
    message = str(e.value)
    assert "401" in message and "LANGFUSE_SECRET_KEY" in message
    for value in (PUBLIC, SECRET, BASIC):
        assert value not in message
    assert len(stub.requests) == 1


# --- plain http:// to a remote host ------------------------------------------------------------


def test_plain_http_remote_host_is_warned_about(keys, clock, monkeypatch):
    with LangfuseStub() as stub:
        # Requests still go to the local stub; only the warning about the host is under test.
        real = langfuse_api.LangfuseClient
        monkeypatch.setattr(langfuse_api, "LangfuseClient",
                            lambda host, *a, **kw: real(stub.url, *a, **kw))
        monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse.example.com")
        _, records = langfuse_api.read_langfuse("helpfulness", "helpfulness_human",
                                                from_="2026-09-01")
    assert any("langfuse.example.com" in w and "unencrypted" in w for w in records.warnings)


def test_local_http_host_is_not_warned_about(keys, clock, monkeypatch):
    with LangfuseStub() as stub:
        _, records = read(stub, monkeypatch)
    assert not any("unencrypted" in w for w in records.warnings)
