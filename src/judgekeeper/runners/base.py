"""Runner interface: `judge(item) -> Judgment`."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from judgekeeper.anchors import LABELS, PAIRWISE, item_kind
from judgekeeper.fingerprint import JudgeFingerprint, endpoint_host, utc_now
from judgekeeper.prompts import load_prompt, parse_verdict


@dataclass
class Judgment:
    """One judge decision on one item.

    For pairwise items `verdict` comes from the AB ordering (output_a shown first) and
    `swapped` holds the BA ordering. Both verdicts are expressed in the item's original
    labels, so `swapped.verdict == "A"` means the judge preferred output_a even when it was
    shown second. `snapshot` is the model id the provider reported serving for this call.
    A custom judge that raised or returned nothing usable has verdict "error" and `error` set.
    """

    verdict: str | None
    raw_score: float | None
    rationale: str
    swapped: Judgment | None = None
    snapshot: str | None = None
    error: str | None = None


class Runner(Protocol):
    @property
    def fingerprint(self) -> JudgeFingerprint: ...

    def judge(self, item: dict) -> Judgment: ...


_SWAP = {"A": "B", "B": "A"}

# Sent when --base-url is given and the key variable is empty: local servers (Ollama,
# vLLM) need no key, but the SDKs refuse to build a client without one.
PLACEHOLDER_KEY = "judgekeeper-no-key"


class RedirectError(RuntimeError):
    """The endpoint answered with a redirect, which judgekeeper does not follow."""


class PromptedRunner:
    """Shared logic for API runners: prompt rendering, AB/BA ordering, verdict parsing, and
    where the key and base URL come from.

    Subclasses set `key_env` and `base_url_env` (the SDK's own variables) and implement
    `_complete(prompt_text) -> (response_text, served_model_id)`. They build the SDK client
    with `_http_client` and call it through `_send`, so a redirect is an error, not followed.
    """

    provider = ""
    key_env = ""
    base_url_env = ""

    def __init__(self, model: str, prompt_path: str | Path, temperature: float = 0.0,
                 base_url: str | None = None, api_key_env: str | None = None):
        self.model = model
        self.temperature = temperature
        self.prompt = load_prompt(prompt_path)
        self._created_at = utc_now()
        self._snapshot: str | None = None
        # The flag wins over the SDK's environment variable; both name the endpoint.
        self.base_url = base_url or os.environ.get(self.base_url_env) or None
        self.endpoint = endpoint_host(self.base_url)
        self.api_key_env = api_key_env or self.key_env
        self._base_url_flag = bool(base_url)
        self.used_placeholder_key = False

    def _api_key(self) -> str:
        """The key from the configured variable. Never logged, never written."""
        key = os.environ.get(self.api_key_env)
        if key:
            return key
        if self._base_url_flag:
            self.used_placeholder_key = True
            return PLACEHOLDER_KEY
        raise RuntimeError(f"{self.api_key_env} is not set")

    def _client_kwargs(self) -> dict:
        kwargs = {"api_key": self._api_key(), "max_retries": 5}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return kwargs

    def _http_client(self, sdk):
        """The SDK's own HTTP client, set not to follow redirects.

        A redirect would re-send the request, and with it the API key header, to whatever
        address the endpoint names. The key goes only to the endpoint the user chose.
        """
        factory = getattr(sdk, "DefaultHttpxClient", None)
        if factory is None:
            raise RuntimeError(
                f"this version of the {self.provider} package cannot turn redirects off, so "
                f"judgekeeper will not send a key with it: pip install -U {self.provider}")
        return factory(follow_redirects=False)

    def _send(self, create, **request):
        """Call the SDK; a redirect it did not follow becomes a RedirectError.

        The message is written here and names only the endpoint host and the status code:
        nothing from the response, and nothing from the SDK's own error text.
        """
        try:
            return create(**request)
        except Exception as e:
            status = getattr(e, "status_code", None)
            if not isinstance(status, int) or not 300 <= status < 400:
                raise
        raise RedirectError(
            f"{self.endpoint or 'the ' + self.provider + ' API'} answered with a redirect "
            f"(HTTP {status}). judgekeeper does not follow redirects, so the API key is sent "
            "only to the endpoint you chose; point --base-url at the final address.")

    @property
    def fingerprint(self) -> JudgeFingerprint:
        return JudgeFingerprint(
            provider=self.provider,
            model=self.model,
            snapshot=self._snapshot,
            prompt_hash=self.prompt.prompt_hash,
            rubric_version=self.prompt.rubric_version,
            temperature=self.temperature,
            created_at=self._created_at,
            endpoint=self.endpoint,
        )

    def _complete(self, text: str) -> tuple[str, str | None]:
        raise NotImplementedError

    def _ask(self, allowed: tuple[str, ...], **values: str) -> Judgment:
        text, served = self._complete(self.prompt.render(**values))
        if served:
            self._snapshot = served
        return Judgment(
            verdict=parse_verdict(text, allowed), raw_score=None, rationale=text, snapshot=served
        )

    def judge(self, item: dict) -> Judgment:
        kind = item_kind(item)
        allowed = LABELS[kind]
        if kind != PAIRWISE:
            return self._ask(allowed, input=item["input"], output=item["output"])
        ab = self._ask(allowed, input=item["input"], output_a=item["output_a"],
                       output_b=item["output_b"])
        ba = self._ask(allowed, input=item["input"], output_a=item["output_b"],
                       output_b=item["output_a"])
        ba.verdict = _SWAP.get(ba.verdict) if ba.verdict else None
        ab.swapped = ba
        return ab
