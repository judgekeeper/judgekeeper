"""The API key names of the LLM providers judgekeeper knows: names only, never a value.

judgekeeper never needs, holds, prints, stores, logs or passes on a key. These names tell
`redact` which variables hold a key, so a value that turns up in a results file or an error is
scrubbed before it is shown or written.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    label: str  # "OpenAI", as in "your OpenAI key"
    keys: tuple[tuple[str, ...], ...] = ()  # alternatives; each a set of names all needed
    settings: tuple[str, ...] = ()


PROVIDERS = {
    "openai": Provider("OpenAI", (("OPENAI_API_KEY",),), (
        "OPENAI_TEMPERATURE", "OPENAI_MAX_TOKENS", "OPENAI_MAX_COMPLETION_TOKENS",
        "OPENAI_TOP_P", "OPENAI_BASE_URL", "OPENAI_API_HOST", "OPENAI_API_BASE_URL",
        "OPENAI_API_BASE")),
    "anthropic": Provider("Anthropic", (("ANTHROPIC_API_KEY",),), (
        "ANTHROPIC_TEMPERATURE", "ANTHROPIC_MAX_TOKENS", "ANTHROPIC_BASE_URL")),
    "azure": Provider("Azure OpenAI", (
        ("AZURE_OPENAI_API_KEY",), ("AZURE_API_KEY",),
        ("AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID")), (
        "AZURE_OPENAI_API_HOST", "AZURE_OPENAI_BASE_URL")),
    "google": Provider("Google AI Studio", (
        ("GOOGLE_API_KEY",), ("GEMINI_API_KEY",), ("PALM_API_KEY",))),
    "vertex": Provider("Google Vertex", (("VERTEX_API_KEY",), ("GOOGLE_API_KEY",)), (
        "VERTEX_PROJECT_ID", "GOOGLE_CLOUD_PROJECT", "VERTEX_REGION", "GOOGLE_CLOUD_LOCATION")),
    "bedrock": Provider("AWS Bedrock", (
        ("AWS_BEARER_TOKEN_BEDROCK",), ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")), (
        "AWS_BEDROCK_REGION", "AWS_BEDROCK_TEMPERATURE", "AWS_BEDROCK_MAX_TOKENS",
        "AWS_BEDROCK_TOP_P")),
    "mistral": Provider("Mistral", (("MISTRAL_API_KEY",),), (
        "MISTRAL_TEMPERATURE", "MISTRAL_MAX_TOKENS", "MISTRAL_API_HOST",
        "MISTRAL_API_BASE_URL")),
    "groq": Provider("Groq", (("GROQ_API_KEY",),)),
    "openrouter": Provider("OpenRouter", (("OPENROUTER_API_KEY",),)),
    "ollama": Provider("Ollama", (), ("OLLAMA_BASE_URL",)),
    "xai": Provider("xAI", (("XAI_API_KEY",), ("GROK_API_KEY",))),
    "codex": Provider("Codex", (("CODEX_API_KEY",),)),
}
# Settings a tool reads for every provider.
TOOL_SETTINGS = {"deepeval": ("TEMPERATURE", "DEEPEVAL_MODEL_THINKING")}


def all_names() -> set[str]:
    """Every variable name this module looks at."""
    names = {n for p in PROVIDERS.values() for alt in p.keys for n in alt}
    names |= {n for p in PROVIDERS.values() for n in p.settings}
    names |= {n for s in TOOL_SETTINGS.values() for n in s}
    names |= {"AZURE_DEPLOYMENT_NAME", "AZURE_OPENAI_DEPLOYMENT_NAME",
              "GOOGLE_APPLICATION_CREDENTIALS", "AWS_PROFILE", "CODEX_HOME"}
    return names


def key_names() -> set[str]:
    """The API key names of the providers judgekeeper knows."""
    return {n for p in PROVIDERS.values() for alt in p.keys for n in alt}
