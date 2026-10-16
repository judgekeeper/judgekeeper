"""The shipped price table: dated, never fetched."""

from __future__ import annotations

import pytest

from judgekeeper import prices


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
    ("gpt-4.1", (2.00, 8.00)),
    ("gpt-4o-2024-08-06", (2.50, 10.00)),
    ("gpt-4o-2024-05-13", (5.00, 15.00)),
    ("claude-opus-5 (Anthropic)", (5.00, 25.00)),
    ("gemini/gemini-2.5-pro", (1.25, 10.00)),
    ("gemini-3.8-pro", None),  # not in LiteLLM's price file on the date read
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


def test_no_network_is_used(monkeypatch):
    import socket

    def refuse(*a, **k):
        raise AssertionError("no network")

    monkeypatch.setattr(socket, "create_connection", refuse)
    assert prices.price("gpt-4.1-mini") == (0.40, 1.60)


def test_tokens_from_text():
    # characters / 4 of what the judge reads, plus 200 output tokens
    assert prices.tokens_from_text("x" * 4000) == (1000, 200)
