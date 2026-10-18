"""The page for a wrong address (website/errors/404.html) and the Caddyfile that serves it.

Caddy shows the page for a wrong address at any depth (/examples/a/b as well as /guide), so
every link and file on it starts at the site's root. It sits in errors/, away from the pages
scripts/site_frame.py rewrites with links relative to the page. The security headers apply to
it too: the Caddyfile sets them in one snippet, used by the normal route and the error route.
"""

from __future__ import annotations

import importlib.util
import re

from tests.website_pages import NAV, ROOT, WEBSITE, pages, parse

PAGE = WEBSITE / "errors" / "404.html"
CADDYFILE = (ROOT / "deploy" / "railway" / "Caddyfile").read_text(encoding="utf-8")


def _els():
    return list(parse(PAGE).iter())


def _links() -> list[str]:
    return [el.attrs[a] for el in _els() for a in ("href", "src") if a in el.attrs]


def test_every_link_starts_at_the_root_and_reaches_a_file_of_the_site():
    for link in _links():
        if link.startswith(("https://", "#")):
            continue
        assert link.startswith("/") and not link.startswith("//"), link
        assert (WEBSITE / re.split(r"[#?]", link.lstrip("/"))[0]).is_file(), link


def test_it_loads_only_the_sites_own_files():
    text = PAGE.read_text(encoding="utf-8")
    assert "<style" not in text and " style=" not in text and "<script>" not in text
    for el in _els():
        if el.tag in {"script", "link", "img"}:
            source = el.attrs.get("src") or el.attrs.get("href")
            assert source.startswith("/assets/"), source


def test_it_has_the_sites_header_and_a_way_back():
    (header,) = [el for el in _els() if el.tag == "header" and "menu" in el.classes()]
    nav = [(a.attrs["href"], a.text().strip()) for a in header.iter() if a.tag == "a"
           and a.parent.tag == "nav"]
    assert nav == [(f"/{href}", label) for href, label in NAV]
    assert not [el for el in header.iter() if el.tag == "button"]  # no theme switch
    (main,) = [el for el in _els() if el.tag == "main"]
    flat = " ".join(main.text().split())
    assert flat.startswith("Page not found")
    assert "There is no page at this address. The link may be old, or have a typo." in flat
    links = [(a.attrs["href"], a.text().strip()) for a in main.iter() if a.tag == "a"]
    assert links == [("/index.html", "Go to the home page"), ("/start.html", "Open the Guide")]


def test_it_is_not_a_page_of_the_site():
    text = PAGE.read_text(encoding="utf-8")
    assert '<meta name="robots" content="noindex">' in text
    assert PAGE not in pages()
    assert "errors/" not in (WEBSITE / "sitemap.xml").read_text(encoding="utf-8")


def test_caddy_serves_it_for_a_wrong_address_and_finds_pages_without_html():
    assert "try_files {path} {path}.html" in CADDYFILE
    errors = CADDYFILE[CADDYFILE.index("handle_errors 404 {"):]
    assert "rewrite * /errors/404.html" in errors and "file_server" in errors


def test_the_security_headers_apply_to_every_response():
    snippet = re.search(r"^\(security\) \{\n(.*?)^\}", CADDYFILE, flags=re.DOTALL | re.MULTILINE)
    assert snippet
    for header in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy",
                   "Strict-Transport-Security", "Content-Security-Policy"):
        assert header in snippet.group(1), header
    assert "default-src 'self'" in snippet.group(1)
    site = CADDYFILE[CADDYFILE.index(":{$PORT:8080} {"):]
    errors = site[site.index("handle_errors 404 {"):]
    assert "import security" in site[:site.index("handle_errors")]
    assert "import security" in errors


def test_its_frame_is_the_sites_frame_with_links_from_the_root():
    spec = importlib.util.spec_from_file_location("site_frame", ROOT / "scripts/site_frame.py")
    frame = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(frame)
    text = PAGE.read_text(encoding="utf-8")
    for block in (frame.head_links(), frame.header(""), frame.footer()):
        rooted = re.sub(r'(href|src)="(?!https://|#|/)([^"]+)"', r'\1="/\2"', block)
        assert rooted in text


# Old addresses: a 301 to the page that has their content now

REDIRECTS = {"/docs": "/reference", "/setup": "/start#keys", "/assistant": "/start",
             "/own-metric": "/start#own-format", "/tutorial": "/start", "/guide": "/start",
             "/how-it-works": "/learn"}


def _redirects() -> dict[str, str]:
    site = CADDYFILE[CADDYFILE.index(":{$PORT:8080} {"):]
    site = site[:site.index("handle_errors 404 {")]
    found = {}
    for old, new, code in re.findall(r"^\s*redir (\S+) (\S+) (\d+)$", site, re.MULTILINE):
        assert code == "301", old
        found[old] = new
    return found


def test_old_addresses_move_to_their_new_page():
    found = _redirects()
    for old, new in REDIRECTS.items():
        assert found.get(old) == new, old
        assert found.get(f"{old}.html") == new, f"{old}.html"
    assert set(found) == set(REDIRECTS) | {f"{old}.html" for old in REDIRECTS}


def test_each_redirect_lands_on_a_page_and_a_place_it_has():
    for new in set(_redirects().values()):
        path, _, anchor = new.partition("#")
        page = WEBSITE / f"{path.lstrip('/')}.html"
        assert page.is_file() and page in pages(), new
        if anchor:
            assert anchor in {el.attrs.get("id") for el in parse(page).iter()}, new


def test_the_redirects_come_before_the_files_and_keep_the_security_headers():
    site = CADDYFILE[CADDYFILE.index(":{$PORT:8080} {"):]
    assert site.index("import security") < site.index("redir ") < site.index("file_server")
