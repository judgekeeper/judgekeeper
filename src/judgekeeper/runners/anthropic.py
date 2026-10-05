"""Anthropic Messages API runner.

Reads the key from ANTHROPIC_API_KEY, or the variable named with --api-key-env. A base URL
(--base-url, else ANTHROPIC_BASE_URL) points it at a gateway. Redirects are not followed: the
key goes only to the endpoint named.
"""

from __future__ import annotations

from pathlib import Path

from judgekeeper.runners.base import PromptedRunner


class AnthropicRunner(PromptedRunner):
    provider = "anthropic"
    key_env = "ANTHROPIC_API_KEY"
    base_url_env = "ANTHROPIC_BASE_URL"

    def __init__(
        self,
        model: str,
        prompt_path: str | Path,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        client=None,
        base_url: str | None = None,
        api_key_env: str | None = None,
    ):
        super().__init__(model, prompt_path, temperature, base_url=base_url,
                         api_key_env=api_key_env)
        self.max_tokens = max_tokens
        if client is None:
            kwargs = self._client_kwargs()
            try:
                import anthropic
            except ImportError:
                raise RuntimeError(
                    'the anthropic package is not installed: pip install '
                    '"judgekeeper[anthropic]"'
                ) from None
            client = anthropic.Anthropic(**kwargs, http_client=self._http_client(anthropic))
        self.client = client

    def _complete(self, text: str) -> tuple[str, str | None]:
        response = self._send(
            self.client.messages.create,
            model=self.model,
            max_tokens=self.max_tokens,
            # anthropic>=1 dropped the temperature kwarg; the API still accepts it for models
            # that support sampling, and the fingerprint records it, so send it in the body.
            extra_body={"temperature": self.temperature},
            messages=[{"role": "user", "content": text}],
        )
        out = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        return out, getattr(response, "model", None)
