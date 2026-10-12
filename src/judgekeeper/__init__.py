"""Check your LLM-as-a-judge: see how often it agrees with human labels."""

__version__ = "1.0.0b1"

__all__ = ["record"]


def __getattr__(name: str):
    # Imported on first use, so `import judgekeeper` stays light.
    if name == "record":
        from judgekeeper.recorder import record

        return record
    raise AttributeError(f"module 'judgekeeper' has no attribute {name!r}")
