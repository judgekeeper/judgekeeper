"""Render a docs/*.md page to website/*.html (every page in PAGES, or one: give the source
and the target). Standard library only. It handles only the Markdown these pages use:
headings, paragraphs, fenced code, tables, lists, `code`, **bold**, *italics* and links. A
test renders each page again and compares, so the committed pages cannot fall behind."""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from share_preview import head  # the title, the description and the share-preview tags

ROOT = Path(__file__).resolve().parent.parent
DOCS_URL = "https://github.com/judgekeeper/judgekeeper/blob/main/docs/"
PAGES = {  # source stem: (target page, title, description)
    "reference": ("reference.html", "Reference: every command and flag",
                  "Every judgekeeper command, file format, flag, exit code and config key."),
    "own-metric": ("own-metric.html", "Your own metric", ("Write your own rule, label real "
                   "outputs, run any judge, and read how often it agrees with your labels.")),
    "assistant": ("assistant.html", "With a coding assistant",
                  "Hand the whole job to a coding assistant: install the skill or paste one prompt."),
}
NAV = [("index.html", "Home"),
       ("own-metric.html", "Your own metric"), ("start.html", "Use it on your app"),
       ("assistant.html", "With a coding assistant"), ("reference.html", "Reference"),
       ("https://github.com/judgekeeper/judgekeeper", "GitHub")]

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{head}
<link rel="icon" href="assets/logo.svg" type="image/svg+xml">
<link rel="stylesheet" href="assets/style.css">
<script src="assets/site.js" defer></script>
</head>
<body>
<a class="skip" href="#main">Skip to the content</a>
<header class="site-header"><div class="wrap">
<a class="brand" href="index.html"><img src="assets/logo.svg" alt="" width="28" height="32"> judgekeeper</a>
<nav class="site-nav" aria-label="Site"><ul>
{nav}</ul></nav>
</div></header>
<main id="main" class="wrap narrow doc">
{body}
<p class="note">This page is generated from <a href="{source_url}">docs/{source}</a> by <code>scripts/{script}</code>.</p>
</main>
<footer class="site-footer"><div class="wrap">judgekeeper is free and open source (MIT).
<a href="https://github.com/judgekeeper/judgekeeper">Source on GitHub</a>.</div></footer>
</body>
</html>
"""


def slug(text: str) -> str:
    """GitHub's heading anchor: lowercase, punctuation dropped, spaces become hyphens."""
    text = re.sub(r"[^\w\- ]", "", text.lower())
    return text.replace(" ", "-")


def link(url: str) -> str:
    if url.startswith(("#", "http://", "https://", "examples/")):
        return url  # examples/ is served next to the page (website/examples -> docs/examples)
    return DOCS_URL + url  # another file in docs/: link to it on GitHub


def inline(text: str) -> str:
    """Escape, then format everything outside `code` spans."""
    out = []
    for i, part in enumerate(re.split(r"(`[^`]*`)", text)):
        if i % 2:
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
            continue
        part = html.escape(part, quote=False)
        part = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", part)
        part = re.sub(r"(?<![\w*])\*(?!\s)([^*]+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", part)
        part = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                      lambda m: f'<a href="{html.escape(link(m[2]))}">{m[1]}</a>', part)
        out.append(part)
    return "".join(out)


def render(markdown: str) -> str:
    lines, out, i = markdown.splitlines(), [], 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            end = lines.index("```", i + 1) if "```" in lines[i + 1:] else len(lines)
            code = "\n".join(lines[i + 1:end])
            out.append(f"<pre><code>{html.escape(code, quote=False)}</code></pre>")
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


def nav(target: str) -> str:
    """The navigation bar every page carries, with `target` marked as the current page."""
    current = ' aria-current="page"'
    return "".join(f'<li><a href="{href}"{current if href == target else ""}>{label}</a></li>\n'
                   for href, label in NAV)


def build(source: Path, out: Path) -> None:
    target, title, description = PAGES[source.stem]
    body = render(source.read_text(encoding="utf-8"))
    if target == "assistant.html":  # commands and the prompt get a copy button (assets/site.js)
        body = body.replace("<pre>", '<div class="code"><pre>').replace("</pre>", "</pre></div>")
    out.write_text(PAGE.format(head=head(target, title, description), nav=nav(target), body=body,
                               source=source.name, source_url=DOCS_URL + source.name,
                               script="render_reference.py"), encoding="utf-8")


if __name__ == "__main__":
    for source, out in [sys.argv[1:3]] if len(sys.argv) == 3 else [
            (ROOT / "docs" / f"{stem}.md", ROOT / "website" / p[0]) for stem, p in PAGES.items()]:
        build(Path(source), Path(out))
