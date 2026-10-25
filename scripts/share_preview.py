"""The top of every page's <head>: its title, its description and its share-preview tags.

The share-preview tags (Open Graph, and the ones X reads) are what WhatsApp, LinkedIn, Slack
and X use to show a picture, a title and one line when someone pastes a link to the site.

The address of the picture and its alt text are written here, once. The pages carry the same
block, typed in, and tests/test_website.py compares every page with tags(). The addresses are absolute and on
the site's own domain, because the apps that read them fetch the picture themselves. No page
loads it. Standard library only.
"""

from __future__ import annotations

import html

SITE = "https://www.judgekeeper.com/"
IMAGE = SITE + "assets/social-preview.png"  # the file is website/assets/social-preview.png
IMAGE_SIZE = (1200, 630)  # made by scripts/make_social_preview.py
IMAGE_ALT = ("The judgekeeper logo and the words: Check your LLM-as-a-judge in 5 steps. "
             "Find. Mark. Measure. Fix. Re-check. uvx judgekeeper")


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
