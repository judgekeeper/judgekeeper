"""judgekeeper: validate, monitor and migrate your LLM-as-judge."""

__version__ = "0.1.4"

__all__ = ["check_judge", "check_table", "import_results"]


def __getattr__(name: str):
    # Imported on first use, so `import judgekeeper` stays light.
    if name == "check_table":
        from judgekeeper.table import check_table

        return check_table
    if name == "check_judge":
        from judgekeeper.custom import check_judge

        return check_judge
    if name == "import_results":
        from judgekeeper.readers import import_results

        return import_results
    raise AttributeError(f"module 'judgekeeper' has no attribute {name!r}")
