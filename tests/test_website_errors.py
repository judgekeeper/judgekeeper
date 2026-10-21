"""The page for a wrong address (website/errors/404.html) and the Caddyfile that serves it.

Caddy shows the page for a wrong address at any depth (/examples/a/b as well as /guide), so
every link and file on it starts at the site's root. It sits in errors/, away from the pages
scripts/site_frame.py rewrites with links relative to the page. The security headers apply to
it too: the Caddyfile sets them in one snippet, used by the normal route and the error route.
"""

from __future__ import annotations

import importlib.util
import os
import re
import urllib.error
import urllib.request

import pytest

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
    # every other error (400, 405) too: one handle_errors with no status, the headers only
    other = re.search(r"^\thandle_errors \{\n(.*?)^\t\}", site, flags=re.DOTALL | re.MULTILINE)
    assert other and other.group(1).strip() == "import security"


def _policies() -> dict[str, str]:
    """The Content-Security-Policy each matcher sets: "" for the site's own (the snippet)."""
    out = {"": re.search(r'Content-Security-Policy "([^"]+)"', CADDYFILE).group(1)}
    for name, policy in re.findall(r'header @(\w+) >Content-Security-Policy "([^"]+)"', CADDYFILE):
        out[name] = policy
    return out


def test_only_the_example_reports_may_run_inline_scripts_and_fonts_in_the_file():
    policies = _policies()
    assert set(policies) == {"", "check", "examples"}
    assert re.search(r"^\t@examples path /examples/\*$", CADDYFILE, flags=re.MULTILINE)
    site, report = policies[""], policies["examples"]
    assert "unsafe-inline" not in site.replace("style-src 'self' 'unsafe-inline'", "")
    assert "font-src" not in site and "script-src" not in site
    # the report's policy is the site's, plus these two and nothing else
    extra = "script-src 'self' 'unsafe-inline'; font-src 'self' data:; "
    assert sorted(report.split("; ")) == sorted(site.split("; ") + extra.rstrip("; ").split("; "))


SECURITY = ("Content-Security-Policy", "Strict-Transport-Security", "X-Content-Type-Options",
            "X-Frame-Options", "Referrer-Policy")


@pytest.mark.skipif(not os.environ.get("JK_SITE_URL"), reason="needs the site's image running: "
                    "JK_SITE_URL=http://127.0.0.1:8098 after docker build -f "
                    "deploy/railway/Dockerfile and docker run -p 127.0.0.1:8098:8080")
@pytest.mark.parametrize(("method", "path", "status"), [
    ("GET", "/", 200), ("GET", "/nope", 404), ("GET", "/check%00", 400), ("POST", "/", 405)])
def test_the_image_sends_the_headers_and_no_server_on_every_status(method, path, status):
    request = urllib.request.Request(os.environ["JK_SITE_URL"].rstrip("/") + path, method=method,
                                     data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(request, timeout=10) as reply:
            got, headers = reply.status, reply.headers
    except urllib.error.HTTPError as error:
        got, headers = error.code, error.headers
    assert got == status
    for name in SECURITY:
        assert headers.get(name), (path, name)
    assert headers.get("Server") is None


@pytest.mark.skipif(not os.environ.get("JK_SITE_URL"), reason="needs the site's image running")
@pytest.mark.parametrize(("path", "loose"), [
    ("/examples/site-example/report.html", True), ("/examples/", True), ("/", False),
    ("/start", False), ("/check", False), ("/examples/nope/x", False), ("/examplesx", False)])
def test_the_image_loosens_the_policy_only_for_the_example_reports(path, loose):
    request = urllib.request.Request(os.environ["JK_SITE_URL"].rstrip("/") + path)
    try:
        with urllib.request.urlopen(request, timeout=10) as reply:
            policy = reply.headers["Content-Security-Policy"]
    except urllib.error.HTTPError as error:
        policy = error.headers["Content-Security-Policy"]
    assert ("script-src 'self' 'unsafe-inline'" in policy) is loose, path
    assert ("font-src 'self' data:" in policy) is loose, path


def test_its_frame_is_the_sites_frame_with_links_from_the_root():
    spec = importlib.util.spec_from_file_location("site_frame", ROOT / "scripts/site_frame.py")
    frame = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(frame)
    text = PAGE.read_text(encoding="utf-8")
    for block in (frame.head_links(), frame.header(""), frame.footer()):
        rooted = re.sub(r'(href|src)="(?!https://|#|/)([^"]+)"', r'\1="/\2"', block)
        assert rooted in text


# Old addresses: a 301 to the page that has their content now. The pages that were removed
# (reference, learn, and docs and how-it-works that led to them) get the page for a wrong
# address, with its links to Home and the Guide.

REDIRECTS = {"/setup": "/start#keys", "/assistant": "/start", "/own-metric": "/start#own-format",
             "/tutorial": "/start", "/guide": "/start"}
GONE = ("/docs", "/how-it-works", "/reference", "/learn")


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
    for gone in GONE:
        assert gone not in found and not (WEBSITE / f"{gone[1:]}.html").exists(), gone


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
