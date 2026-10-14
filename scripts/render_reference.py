"""Render a docs/*.md page to website/*.html (every page in PAGES, or one: give the source
and the target). Standard library only. It handles only the Markdown these pages use:
headings, paragraphs, fenced code (a ```text fence is printed output, shown without a copy
button), tables, lists, `code`, **bold**, *italics* and links. A test renders each page again
and compares, so the committed pages cannot fall behind."""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from share_preview import head  # the title, the description and the share-preview tags
from site_frame import footer, head_links, header  # the frame every page shares

ROOT = Path(__file__).resolve().parent.parent
DOCS_URL = "https://github.com/judgekeeper/judgekeeper/blob/main/docs/"
PAGES = {  # source stem: (target page, title, description, who the page is for)
    "reference": ("reference.html", "Reference: every command and flag",
                  "Every judgekeeper command, file format, flag, exit code and config key.", ""),
}
NEW_HERE = ('<p class="newhere">New here? Start with the <a href="start.html">Guide</a>. '
            "This page is for {who}.</p>\n")

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{head}
{links}
<script src="assets/site.js" defer></script>
</head>
<body>
{header}
<main id="main" class="wrap narrow doc">
{new_here}{body}
<p class="note">This page is generated from <a href="{source_url}">docs/{source}</a> by <code>scripts/{script}</code>.</p>
</main>
{footer}
</body>
</html>
"""


def slug(text: str) -> str:
    """GitHub's heading anchor: lowercase, punctuation dropped, spaces become hyphens."""
    text = re.sub(r"[^\w\- ]", "", text.lower())
    return text.replace(" ", "-")


def link(url: str) -> str:
    if url.startswith("examples/") and url.endswith(("/", ".md")):  # GitHub shows these best
        return DOCS_URL.replace("/blob/", "/tree/" if url.endswith("/") else "/blob/") + url
    if url.startswith(("#", "http://", "https://", "examples/")):
        return url  # examples/ is served next to the page (website/examples -> docs/examples)
    stem, _, anchor = url.partition("#")
    if stem.removesuffix(".md") in PAGES:  # a page that is on the site: stay on the site
        return PAGES[stem.removesuffix(".md")][0] + (f"#{anchor}" if anchor else "")
    return DOCS_URL + url  # another file in docs/: link to it on GitHub


def inline(text: str) -> str:
    """Escape and format the text. `code` spans are set aside first, so bold text and links
    may hold code, and nothing inside code is formatted."""
    codes: list[str] = []

    def keep(m: re.Match) -> str:
        codes.append(m[1])
        return f"\0{len(codes) - 1}\0"

    text = html.escape(re.sub(r"`([^`]*)`", keep, text), quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)([^*]+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: f'<a href="{html.escape(link(m[2]))}">{m[1]}</a>', text)
    return re.sub(r"\0(\d+)\0", lambda m: f"<code>{html.escape(codes[int(m[1])])}</code>", text)


def render(markdown: str) -> str:
    lines, out, i = markdown.splitlines(), [], 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            end = lines.index("```", i + 1) if "```" in lines[i + 1:] else len(lines)
            code = "\n".join(lines[i + 1:end])
            pre = '<pre class="output">' if line == "```text" else "<pre>"
            out.append(f"{pre}<code>{html.escape(code, quote=False)}</code></pre>")
            i = end + 1
        elif m := re.match(r"(#{1,4}) (.+)", line):
            level, title = len(m[1]), m[2].strip()
            out.append(f'<h{level} id="{slug(title)}">{inline(title)}</h{level}>')
            i += 1
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body = rows[0], [r for r in rows[1:] if not set("".join(r)) <= set("-: ")]
            th = "".join(f"<th>{inline(c)}</th>" for c in head)
            trs = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>\n"
                          for r in body)
            out.append(f"<table>\n<thead><tr>{th}</tr></thead>\n<tbody>\n{trs}</tbody>\n</table>")
        elif re.match(r"(- |\d+\. )", line):
            tag = "ul" if line.startswith("- ") else "ol"
            items = []
            while i < len(lines) and re.match(r"(- |\d+\. )", lines[i]):
                text = re.sub(r"^(- |\d+\. )", "", lines[i])
                items.append(f"<li>{inline(text)}</li>")
                i += 1
            out.append(f"<{tag}>\n" + "\n".join(items) + f"\n</{tag}>")
        elif line.strip():
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(
                    r"(```|#{1,4} |\||- |\d+\. )", lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{inline(' '.join(para))}</p>")
        else:
            i += 1
    return "\n".join(out)


def build(source: Path, out: Path) -> None:
    target, title, description, who = PAGES[source.stem]
    body = render(source.read_text(encoding="utf-8"))
    out.write_text(PAGE.format(
        head=head(target, title, description), links=head_links(), header=header(target),
        footer=footer(), new_here=NEW_HERE.format(who=who) if who else "", body=body,
        source=source.name, source_url=DOCS_URL + source.name, script="render_reference.py"),
        encoding="utf-8", newline="\n")


if __name__ == "__main__":
    for source, out in [sys.argv[1:3]] if len(sys.argv) == 3 else [
            (ROOT / "docs" / f"{stem}.md", ROOT / "website" / p[0]) for stem, p in PAGES.items()]:
        build(Path(source), Path(out))
