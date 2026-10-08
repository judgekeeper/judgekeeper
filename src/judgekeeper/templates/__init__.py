"""The starter rule files that `judgekeeper init` writes.

`single.md` and `pairwise.md` ship inside the wheel. Each loads with `load_prompt` as it is
(frontmatter `rubric_version: my-metric-v1`, the usual placeholders, the usual `Verdict:`
line); the parts the user writes are marked `[FILL IN: ...]`, and `judge --prompt` refuses a
file that still has one. Standard library only.
"""

from __future__ import annotations

from pathlib import Path

from judgekeeper.textio import quote_arg

TEMPLATES = Path(__file__).resolve().parent
DEFAULT_OUT = "prompts/judge.md"


def template_path(pairwise: bool = False) -> Path:
    return TEMPLATES / ("pairwise.md" if pairwise else "single.md")


def template_text(pairwise: bool = False) -> str:
    return template_path(pairwise).read_bytes().decode("utf-8").replace("\r\n", "\n")


class ExistsError(Exception):
    """The target file exists and --force was not given."""


def write_starter(out: str | Path, pairwise: bool = False, force: bool = False) -> Path:
    """Write the template to `out`, creating parent folders; refuse to overwrite without force."""
    out = Path(out)
    if out.exists() and not force:
        raise ExistsError(f"{out} exists; pass --force to overwrite it")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(template_text(pairwise), encoding="utf-8")
    return out


def next_steps(out: str | Path) -> str:
    """The steps that follow `init`, with the rule file filled in."""
    return "\n".join([
        f"wrote {out}: fill in every [FILL IN: ...] marker, then",
        ("  1. label real items (30 to 60 for a first look, about 100 for a firmer result) "
         "in anchors.jsonl,"),
        ("     one JSON line each: id, input, output and human_label (pass or fail; with "
         "--pairwise,"),
        "     output_a, output_b and A or B). judge seals the file the first time it reads it.",
        "  2. run any judge with the rule, 3 times:",
        ("       judgekeeper judge anchors.jsonl --runner anthropic --model "
         f"claude-haiku-4-5-20251001 --prompt {quote_arg(out)} --runs 3 --out "
         "runs/my-metric/"),
        "  3. read the report:",
        "       judgekeeper validate anchors.jsonl runs/my-metric/ --out reports/my-metric/",
    ])
