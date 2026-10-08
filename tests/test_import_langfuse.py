"""`judgekeeper import langfuse`: Langfuse's public API in, a report out.

Checked against recorded responses built from Langfuse's published OpenAPI definitions, not a
live server (see tests/fixtures/langfuse/make_responses.py for the commit and the numbers):
6 labeled traces, one run, --pass-if 'score>=0.5' -> TPR 2/3, TNR 2/3, kappa 1/3.
A local stub server (tests/langfuse_stub.py) answers the requests; time is faked, so the rate
limit and the 429 back-off never sleep for real.
"""

import base64
import hashlib
import json

import pytest

from judgekeeper.anchors import canonical_json
from judgekeeper.cli import main
from judgekeeper.readers import langfuse_api
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


def run(stub, monkeypatch, out, *extra, window=("--from", "2026-09-01")):
    monkeypatch.setenv("LANGFUSE_HOST", stub.url)
    return main(["import", "langfuse", "--judge-score", "helpfulness",
                 "--human-score", "helpfulness_human", "--pass-if", "score>=0.5",
                 *window, "--out", str(out), *extra])


def report(out):
    return json.loads((out / "report.json").read_text(encoding="utf-8"))


def test_one_command_turns_the_api_into_a_report(keys, clock, monkeypatch, tmp_path, capsys):
    with LangfuseStub() as stub:
        assert run(stub, monkeypatch, tmp_path / "rep") == 0
    r = report(tmp_path / "rep")
    assert r["n_runs"] == 1
    assert r["anchors"]["n_items"] == 6
    assert r["runs"][0]["tpr"] == pytest.approx(2 / 3)
    assert r["runs"][0]["tnr"] == pytest.approx(2 / 3)
    assert r["runs"][0]["kappa"] == pytest.approx(1 / 3)
    assert r["noise_floor"]["status"].startswith("unknown")
    src = r["source"]
    assert src["kind"] == "langfuse"
    assert src["metric"] == "helpfulness"
    assert src["n_judged_unlabeled"] == 1  # trace-7
    assert src["ids_derived"] is False
    assert any("one run" in n for n in src["notes"])
    fp = r["fingerprint"]
    assert (fp["provider"], fp["model"], fp["rubric_version"]) == ("openai", "gpt-4.1-mini", "3")
    prompt = load("evaluators.json")["data"][1]["prompt"]
    assert fp["prompt_hash"] == hashlib.sha256(canonical_json(prompt).encode()).hexdigest()
    assert fp["temperature"] is None  # Langfuse stores none
    run1 = [json.loads(x) for x in (tmp_path / "rep" / "runs" / "run-01.jsonl").read_text(
        encoding="utf-8")
            .splitlines()]
    t1 = next(x for x in run1 if x.get("id") == "trace-1")
    assert t1["verdict"] == "pass" and t1["raw_score"] == 0.9
    assert t1["rationale"] == "The answer covers most of the question."
    assert "one run" in capsys.readouterr().out


def test_requests_are_read_only_paged_and_authenticated(keys, clock, monkeypatch, tmp_path):
    with LangfuseStub() as stub:
        assert run(stub, monkeypatch, tmp_path / "rep", window=(
            "--from", "2026-09-01", "--to", "2026-10-01T12:00:00Z")) == 0
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


def test_requests_are_spaced_to_the_rate(keys, clock, monkeypatch, tmp_path):
    with LangfuseStub() as stub:
        assert run(stub, monkeypatch, tmp_path / "a") == 0
    assert clock.sleeps == pytest.approx([2.0, 2.0, 2.0])  # 30 a minute: 4 requests
    clock.sleeps.clear()
    with LangfuseStub() as stub:
        assert run(stub, monkeypatch, tmp_path / "b", "--rate", "120") == 0
    assert clock.sleeps == pytest.approx([0.5, 0.5, 0.5])


def test_429_backs_off_for_retry_after_then_succeeds(keys, clock, monkeypatch, tmp_path):
    with LangfuseStub(rate_limited=2, retry_after="7") as stub:
        assert run(stub, monkeypatch, tmp_path / "rep", "--rate", "6000") == 0
    assert len(stub.score_requests()) == 5  # two 429s, then three pages
    assert clock.sleeps.count(7.0) == 2
    assert report(tmp_path / "rep")["runs"][0]["kappa"] == pytest.approx(1 / 3)


def test_429_without_end_gives_up(keys, clock, monkeypatch, tmp_path, capsys):
    with LangfuseStub(rate_limited=100, retry_after="1") as stub:
        assert run(stub, monkeypatch, tmp_path / "rep") == 1
    err = capsys.readouterr().err
    assert "429" in err
    assert len(stub.score_requests()) == langfuse_api.MAX_RETRIES + 1


def test_evaluator_with_default_model(keys, clock, monkeypatch, tmp_path, capsys):
    with LangfuseStub(evaluators=load("evaluators-default-model.json")) as stub:
        assert run(stub, monkeypatch, tmp_path / "rep") == 0
    r = report(tmp_path / "rep")
    assert r["fingerprint"]["model"] is None and r["fingerprint"]["provider"] is None
    assert "model" in r["fingerprint_unknown"]
    assert r["fingerprint"]["prompt_hash"] is not None  # the prompt is still known
    assert any("modelConfig is null" in n for n in r["source"]["notes"])


def test_no_matching_evaluator(keys, clock, monkeypatch, tmp_path):
    with LangfuseStub(evaluators={"data": [], "meta": {}}) as stub:
        assert run(stub, monkeypatch, tmp_path / "rep") == 0
    r = report(tmp_path / "rep")
    for f in ("model", "prompt_hash", "rubric_version"):
        assert f in r["fingerprint_unknown"]
    assert any("no evaluator named 'helpfulness'" in n for n in r["source"]["notes"])


def test_source_that_disagrees_with_the_mapping_is_noted(keys, clock, monkeypatch, tmp_path):
    pages = score_pages()
    pages[0]["data"][0]["source"] = "ANNOTATION"  # a judge score a person entered
    with LangfuseStub(pages=pages) as stub:
        assert run(stub, monkeypatch, tmp_path / "rep") == 0
    notes = report(tmp_path / "rep")["source"]["notes"]
    assert any("1 'helpfulness' score has source ANNOTATION" in n for n in notes)
    # trace-5's human score came through the API: ambiguous, not a disagreement
    assert not any("'helpfulness_human'" in n and "API" in n for n in notes)


def test_judge_and_human_with_one_name_split_by_source(keys, clock, monkeypatch, tmp_path):
    pages = score_pages()
    for p in pages:
        for s in p["data"]:
            if s["name"] == "helpfulness_human":
                s["name"] = "helpfulness"
                s["source"] = "ANNOTATION"
    with LangfuseStub(pages=pages) as stub:
        monkeypatch.setenv("LANGFUSE_HOST", stub.url)
        assert main(["import", "langfuse", "--judge-score", "helpfulness", "--human-score",
                     "helpfulness", "--pass-if", "score>=0.5", "--max-items", "100",
                     "--out", str(tmp_path / "rep")]) == 0
    r = report(tmp_path / "rep")
    assert r["runs"][0]["kappa"] == pytest.approx(1 / 3)
    assert any("source ANNOTATION" in n for n in r["source"]["notes"])


def test_max_items_stops_paging(keys, clock, monkeypatch, tmp_path):
    with LangfuseStub() as stub:
        assert run(stub, monkeypatch, tmp_path / "rep", window=("--max-items", "7")) == 0
    assert len(stub.score_requests()) == 2
    assert "fromTimestamp" not in stub.score_requests()[0][1]
    r = report(tmp_path / "rep")
    assert any("--max-items 7" in n for n in r["source"]["notes"])


def test_a_window_or_max_items_is_required(keys, clock, monkeypatch, tmp_path, capsys):
    with LangfuseStub() as stub:
        assert run(stub, monkeypatch, tmp_path / "rep", window=()) == 2
    assert not stub.requests
    assert "--max-items" in capsys.readouterr().err


@pytest.mark.parametrize("window", [("--from", "yesterday"), ("--to", "2026-13-01"),
                                    ("--from", "2026-10-02", "--to", "2026-10-01"),
                                    ("--max-items", "0")])
def test_bad_window_is_a_usage_error(keys, clock, monkeypatch, tmp_path, window):
    with LangfuseStub() as stub:
        assert run(stub, monkeypatch, tmp_path / "rep", window=window) == 2
    assert not stub.requests


def test_missing_keys_are_a_usage_error(clock, monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", SECRET)
    with LangfuseStub() as stub:
        assert run(stub, monkeypatch, tmp_path / "rep") == 2
    assert not stub.requests
    assert "LANGFUSE_PUBLIC_KEY" in capsys.readouterr().err


def test_default_host_is_the_eu_cloud(keys):
    assert langfuse_api.host_from_env() == "https://cloud.langfuse.com"


def test_base_url_wins_over_host(keys, monkeypatch):
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com")
    monkeypatch.setenv("LANGFUSE_HOST", "https://other.example.com")
    assert langfuse_api.host_from_env() == "https://us.cloud.langfuse.com"


@pytest.mark.parametrize("host", ["ftp://langfuse.example.com",
                                  "https://user:pw@langfuse.example.com"])
def test_bad_host_is_a_usage_error(keys, monkeypatch, tmp_path, capsys, host):
    monkeypatch.setenv("LANGFUSE_HOST", host)
    assert main(["import", "langfuse", "--judge-score", "a", "--human-score", "b",
                 "--max-items", "5", "--out", str(tmp_path)]) == 2
    assert "pw" not in capsys.readouterr().err


def test_cross_host_redirect_is_refused(keys, clock, monkeypatch, tmp_path, capsys):
    with LangfuseStub() as other:
        # 127.0.0.1 and localhost are different hosts: the credentials must not follow
        target = other.url.replace("127.0.0.1", "localhost")
        with LangfuseStub(redirect_to=target) as stub:
            assert run(stub, monkeypatch, tmp_path / "rep") == 1
    assert len(stub.requests) == 1
    assert not other.requests
    err = capsys.readouterr().err
    assert "redirect" in err and SECRET not in err and BASIC not in err


def test_http_error_never_echoes_credentials(keys, clock, monkeypatch, tmp_path, capsys):
    with LangfuseStub(status=401) as stub:
        assert run(stub, monkeypatch, tmp_path / "rep") == 1
    err = capsys.readouterr().err
    assert "401" in err and "LANGFUSE_SECRET_KEY" in err
    for value in (PUBLIC, SECRET, BASIC):
        assert value not in err
    assert len(stub.requests) == 1


def test_no_credentials_in_any_output_or_file(keys, clock, monkeypatch, tmp_path, capsys):
    pages = score_pages()
    for s in pages[0]["data"]:  # a judge comment echoing the keys and the header
        s["comment"] = f"debug {PUBLIC} {SECRET} Authorization: Basic {BASIC}"
    out = tmp_path / "rep"
    with LangfuseStub(pages=pages) as stub:
        assert run(stub, monkeypatch, out, "--anchors-out", str(tmp_path / "a.jsonl")) == 0
        assert main(["--debug", "import", "langfuse", "--judge-score", PUBLIC,
                     "--human-score", "x", "--max-items", "1", "--out",
                     str(tmp_path / "bad")]) in (1, 2)
    printed = capsys.readouterr()
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert files
    for text in [printed.out, printed.err, *(p.read_text(encoding="utf-8") for p in files)]:
        for value in (PUBLIC, SECRET, BASIC):
            assert value not in text
    assert "[REDACTED]" in (out / "runs" / "run-01.jsonl").read_text(encoding="utf-8")


def test_anchors_out_hands_off_to_judge(keys, clock, monkeypatch, tmp_path):
    anchors = tmp_path / "anchors.jsonl"
    with LangfuseStub() as stub:
        assert run(stub, monkeypatch, tmp_path / "rep", "--anchors-out", str(anchors)) == 0
    items = [json.loads(x) for x in anchors.read_text(encoding="utf-8").splitlines()]
    assert [i["id"] for i in items] == [f"trace-{n}" for n in range(1, 7)]
    assert [i["human_label"] for i in items] == ["pass"] * 3 + ["fail"] * 3
    # the v3 scores endpoint returns no trace text: input and output stay empty
    assert all(i["input"] == "" and i["output"] == "" for i in items)
    assert "reviewed in queue" not in anchors.read_text(encoding="utf-8")
    assert "user-ann-1" not in anchors.read_text(encoding="utf-8")
    # --anchors-out sealed it: judge reads it as it is
    assert main(["judge", str(anchors), "--runner", "replay", "--fixture",
                 str(tmp_path / "rep" / "runs" / "run-01.jsonl"), "--runs", "3",
                 "--out", str(tmp_path / "rejudged")]) == 0
    assert main(["validate", str(anchors), str(tmp_path / "rejudged"),
                 "--out", str(tmp_path / "rep2")]) == 0
    r = report(tmp_path / "rep2")
    assert r["n_runs"] == 3
    assert r["headline"]["kappa_mean"] == pytest.approx(1 / 3)


def test_langfuse_options_need_langfuse(tmp_path, capsys):
    assert main(["import", "mlflow", "--experiment", "e", "--judge-score", "x",
                 "--out", str(tmp_path)]) == 2
    assert "--judge-score" in capsys.readouterr().err


def test_judge_and_human_score_are_required(keys, tmp_path, capsys):
    assert main(["import", "langfuse", "--max-items", "5", "--out", str(tmp_path)]) == 2
    assert "--judge-score" in capsys.readouterr().err


# --- plain http:// to a remote host (security audit item 6) ------------------------------------


def test_plain_http_remote_host_is_warned_about(keys, clock, monkeypatch, tmp_path, capsys):
    with LangfuseStub() as stub:
        # Requests still go to the local stub; only the warning about the host is under test.
        real = langfuse_api.LangfuseClient
        monkeypatch.setattr(langfuse_api, "LangfuseClient",
                            lambda host, *a, **kw: real(stub.url, *a, **kw))
        monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse.example.com")
        assert main(["import", "langfuse", "--judge-score", "helpfulness",
                     "--human-score", "helpfulness_human", "--pass-if", "score>=0.5",
                     "--from", "2026-09-01", "--out", str(tmp_path / "rep")]) == 0
    err = capsys.readouterr().err
    assert "langfuse.example.com" in err and "unencrypted" in err


def test_local_http_host_is_not_warned_about(keys, clock, monkeypatch, tmp_path, capsys):
    with LangfuseStub() as stub:
        assert run(stub, monkeypatch, tmp_path / "rep") == 0
    assert "unencrypted" not in capsys.readouterr().err
