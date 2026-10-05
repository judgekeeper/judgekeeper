"""OpenAI Chat Completions runner.

Reads the key from OPENAI_API_KEY, or the variable named with --api-key-env. A base URL
(--base-url, else OPENAI_BASE_URL) points it at any OpenAI-compatible endpoint: Azure OpenAI's
v1 endpoint, OpenRouter, Together, a LiteLLM proxy, Ollama, vLLM. Redirects are not followed:
the key goes only to the endpoint named.
"""

from __future__ import annotations

from pathlib import Path

from judgekeeper.runners.base import PromptedRunner


class OpenAIRunner(PromptedRunner):
    provider = "openai"
    key_env = "OPENAI_API_KEY"
    base_url_env = "OPENAI_BASE_URL"

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
                import openai
            except ImportError:
                raise RuntimeError(
                    'the openai package is not installed: pip install "judgekeeper[openai]"'
                ) from None
            client = openai.OpenAI(**kwargs, http_client=self._http_client(openai))
        self.client = client

    def _complete(self, text: str) -> tuple[str, str | None]:
        response = self._send(
            self.client.chat.completions.create,
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "user", "content": text}],
        )
        return response.choices[0].message.content or "", getattr(response, "model", None)
