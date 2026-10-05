"""The shipped price table: dated, never fetched."""

from __future__ import annotations

import pytest

from judgekeeper import prices


def test_the_table_is_dated():
    assert prices.PRICES_READ == "2026-10-05"


@pytest.mark.parametrize("model, expected", [
    ("gpt-4.1-mini", (0.40, 1.60)),
    ("openai:gpt-4.1-mini", (0.40, 1.60)),
    ("openai:chat:gpt-4.1-mini", (0.40, 1.60)),
    ("openai:/gpt-4.1-mini", (0.40, 1.60)),
    ("openai/gpt-4.1-mini", (0.40, 1.60)),
    ("gpt-5.6-sol", (4.00, 20.00)),
    ("claude-sonnet-4-6 (Anthropic)", (3.00, 15.00)),
    ("anthropic:messages:claude-haiku-4-5-20251001", (1.00, 5.00)),
    ("gemini-3.8-flash", (0.75, 3.75)),
    ("mistral-large-latest", (0.50, 1.50)),
    ("grok-4.3", (1.25, 2.50)),
    ("groq:openai/gpt-oss-20b", (0.075, 0.30)),
    ("my-own-model", None),
    (None, None),
])
def test_prices_per_million_tokens(model, expected):
    assert prices.price(model) == expected


def test_an_estimate_is_a_range_from_half_to_two_and_a_half_times():
    # 100 calls of 1,500 input and 200 output tokens at gpt-5.6-sol's $4 / $20:
    # 100 x (1500 x 4 + 200 x 20) / 1e6 = $1.00, so $0.50 to $2.50.
    low, high = prices.estimate("gpt-5.6-sol", [(1500, 200)] * 100)
    assert (low, high) == pytest.approx((0.50, 2.50))


def test_the_cost_line():
    line = prices.cost_line("openai:gpt-5.6-sol", "openai", [(1500, 200)] * 100)
    assert line == "About $0.50 to $2.50 at OpenAI's prices from 2026-10-05; check your provider."


def test_a_tiny_cost():
    line = prices.cost_line("gpt-4.1-mini", "openai", [(100, 10)])
    assert line.startswith("Less than $0.01")


def test_an_unknown_model_has_no_cost():
    assert prices.estimate("my-own-model", [(1500, 200)]) is None
    assert prices.cost_line("my-own-model", None, [(1500, 200)]) == (
        "Cost unknown for this model (my-own-model).")


def test_no_network_is_used(monkeypatch):
    import socket

    def refuse(*a, **k):
        raise AssertionError("no network")

    monkeypatch.setattr(socket, "create_connection", refuse)
    assert prices.price("gpt-4.1-mini") == (0.40, 1.60)


def test_tokens_from_text():
    # characters / 4 of what the judge reads, plus 200 output tokens
    assert prices.tokens_from_text("x" * 4000) == (1000, 200)
