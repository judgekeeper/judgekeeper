"""A small, dated table of judge model prices, for the cost line before asking a judge again.

USD per million tokens, input and output, standard tier, read on PRICES_READ from the
providers' price pages and LiteLLM's price file. judgekeeper never fetches prices: a model
that is not here gets "cost unknown". Update the table at each release.

An estimate is shown as a range, from half to 2.5 times the token count's cost: token counts
are guesses unless the results file saved the judge's real ones, and reasoning models bill
hidden output tokens.
"""

from __future__ import annotations

import re

PRICES_READ = "2026-10-05"
PRICES = {
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-2024-05-13": (5.00, 15.00),  # the first gpt-4o snapshot costs more
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.6-sol": (4.00, 20.00),
    "gpt-6-sol": (2.00, 10.00),
    "gpt-6-luna": (0.10, 0.50),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-5-5": (4.00, 20.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),  # up to 200,000 input tokens
    "gemini-3.1-pro-preview": (2.00, 12.00),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.6-flash": (0.75, 3.75),  # Google's page: 1.50 / 7.50 from 2027-01-01
    "gemini-3.7-flash": (0.75, 3.75),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "mistral-small-latest": (0.15, 0.60),
    "mistral-small-2603": (0.15, 0.60),
    "mistral-large-latest": (0.50, 1.50),
    "grok-4.3": (1.25, 2.50),
    "openai/gpt-oss-20b": (0.075, 0.30),  # on Groq
}
LOW, HIGH = 0.5, 2.5
OUTPUT_TOKENS = 200  # a verdict and a short reason, when the file has no real count
_SUFFIX = re.compile(r"\s*\([^()]*\)\s*\Z")  # DeepEval's " (Anthropic)"
_SNAPSHOT = re.compile(r"-(20\d{6}|\d{4}-\d{2}-\d{2})\Z")


def _candidates(model: str) -> list[str]:
    name = _SUFFIX.sub("", model.strip()).lower()
    out = [name]
    if ":/" in name:
        out.append(name.split(":/", 1)[1])
    if ":" in name:
        out.append(name.rsplit(":", 1)[1])
        out.append(name.split(":", 1)[1])
    if "/" in name:
        out.append(name.split("/", 1)[1])
    return out + [_SNAPSHOT.sub("", c) for c in out]


def price(model: str | None) -> tuple[float, float] | None:
    """(input, output) USD per million tokens, or None for a model not in the table."""
    if not model:
        return None
    return next((PRICES[c] for c in _candidates(str(model)) if c in PRICES), None)


def tokens_from_text(text: str) -> tuple[int, int]:
    """A call's tokens from what the judge reads: characters / 4, plus a short reply."""
    return len(text) // 4, OUTPUT_TOKENS


def estimate(model: str | None, tokens: list[tuple[int, int]]) -> tuple[float, float] | None:
    """(low, high) USD for calls of (input, output) tokens, or None when the price is
    unknown."""
    p = price(model)
    if p is None:
        return None
    cost = sum(i * p[0] + o * p[1] for i, o in tokens) / 1_000_000
    return cost * LOW, cost * HIGH


def money(x: float) -> str:
    return "less than $0.01" if x < 0.01 else f"${x:,.2f}"


def amount(low: float, high: float) -> str:
    """A cost range in words: "less than $0.01", "up to $0.02" or "about $0.50 to $2.50"."""
    if high < 0.01:
        return "less than $0.01"
    if low < 0.01:
        return f"up to {money(high)}"
    return f"about {money(low)} to {money(high)}"


def cost_line(model: str | None, provider: str | None,
              tokens: list[tuple[int, int]]) -> str:
    from judgekeeper.keys import PROVIDERS

    est = estimate(model, tokens)
    if est is None:
        return f"Cost unknown for this model ({model})."
    low, high = est
    who = f"{PROVIDERS[provider].label}'s" if provider in PROVIDERS else "list"
    words = amount(low, high)
    return f"{words[0].upper()}{words[1:]} at {who} prices from {PRICES_READ}; check your provider."
