"""The top of every page's <head>: its title, its description and its share-preview tags.

The share-preview tags (Open Graph, and the ones X reads) are what WhatsApp, LinkedIn, Slack
and X use to show a picture, a title and one line when someone pastes a link to the site.

The address of the picture and its alt text are written here, once. The generated pages get
this block from scripts/render_reference.py. The hand-written
pages carry the same block, typed in; tests/test_website.py compares every page with head().
The addresses are absolute and on the site's own domain, because the apps that read them fetch
the picture themselves. No page loads it. Standard library only.
"""

from __future__ import annotations

import html

SITE = "https://www.judgekeeper.com/"
IMAGE = SITE + "assets/social-preview.png"  # website/assets/social-preview.png
IMAGE_SIZE = (1280, 640)
IMAGE_ALT = ("judgekeeper: Check your LLM-as-a-judge. See how often it agrees with human labels, "
             "in one command.")


def url(target: str) -> str:
    """The public address of a page; the home page is the site root, as in sitemap.xml."""
    return SITE + ("" if target == "index.html" else target)


def _attr(value: object) -> str:
    return html.escape(str(value), quote=False).replace('"', "&quot;")


def tags(target: str, title: str, description: str) -> str:
    """The share-preview tags of the page `target`, one per line."""
    width, height = IMAGE_SIZE
    og = [("type", "website"), ("site_name", "judgekeeper"), ("title", title),
          ("description", description), ("url", url(target)), ("image", IMAGE),
          ("image:width", width), ("image:height", height), ("image:alt", IMAGE_ALT)]
    x = [("card", "summary_large_image"), ("title", title), ("description", description),
         ("image", IMAGE)]
    return "\n".join(
        [f'<meta property="og:{key}" content="{_attr(value)}">' for key, value in og]
        + [f'<meta name="twitter:{key}" content="{_attr(value)}">' for key, value in x])


def head(target: str, title: str, description: str) -> str:
    """The <title>, the description and the share-preview tags of a generated page."""
    title = f"{title} | judgekeeper"
    return (f"<title>{title}</title>\n"
            f'<meta name="description" content="{_attr(description)}">\n'
            f"{tags(target, title, description)}")
