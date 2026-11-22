"""The keeper of human judgment for AI: see how often a check agrees with human labels."""

__version__ = "1.4.0"

__all__ = ["record"]


def __getattr__(name: str):
    # Imported on first use, so `import judgekeeper` stays light.
    if name == "record":
        from judgekeeper.recorder import record

        return record
    raise AttributeError(f"module 'judgekeeper' has no attribute {name!r}")
