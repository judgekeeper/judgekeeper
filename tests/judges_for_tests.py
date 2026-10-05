"""Judge functions for the --callable tests. No network."""


def keyword_judge(item: dict) -> bool:
    return "good" in item["output"]


def pick_good(item: dict) -> str:
    """Pairwise: prefers whichever output says good."""
    return "A" if "good" in item["output_a"] else "B"


def always_raises(item: dict) -> bool:
    raise RuntimeError("the judge service is down\n(try again later)")


def raises_with_a_key(item: dict) -> bool:
    raise RuntimeError("401 for key sk-ant-api03-abcdefghijklmnop")
