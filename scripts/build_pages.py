"""Build the static site: the website at the root, the example reports under examples/.

    python scripts/build_pages.py website docs/examples _site

- website/ is copied as it is (its README.md and its local `examples` link are left out).
- docs/examples/ is copied to examples/. Each <name>/report.html is also written as
  <name>/index.html, so https://www.judgekeeper.com/examples/<name>/ serves it,
  and examples/index.html lists the folders that have a README.md or a report.md.
- The build stops if a page under examples/ has a <script> but not the
  Content-Security-Policy meta tag that judgekeeper's report pages carry: the site lets
  example pages run only the scripts that tag names by hash.

Standard library only; run by deploy/railway/Dockerfile.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import sys
from pathlib import Path

INDEX = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>judgekeeper example reports</title>
<style>
:root {{ color-scheme: dark; --bg: #0b0c0e; --fg: #e6e8eb; --muted: #8b919a; --line: #262a30;
  --link: #7aa2ff; }}
body {{ margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 760px; margin: 0 auto; padding: 32px 16px; }}
a {{ color: var(--link); }}
li {{ margin: 12px 0; }}
.meta {{ color: var(--muted); font-size: 14px; }}
</style>
</head>
<body>
<main>
<p><a href="../index.html">judgekeeper home</a></p>
<h1>judgekeeper example reports</h1>
<p>Reports committed under <code>docs/examples/</code> in the repository. All come
from real runs on public datasets (of judgekeeper, or of a check script that uses its
maths), except <code>site-example</code>: the made-up project the home page shows, and
<code>kept-aside</code>: what <code>fix</code> says on simulated new rules.</p>
<ul>
{items}
</ul>
</main>
</body>
</html>
"""


REPO = "https://github.com/judgekeeper/judgekeeper/blob/main/docs/examples/"
POLICY = re.compile(r'<meta http-equiv="Content-Security-Policy" content="[^"]*script-src '
                    r"'sha256-", re.IGNORECASE)


def unsafe_pages(examples: Path) -> list[str]:
    """The pages under `examples` that have a <script> but no meta policy naming it by hash."""
    return [p.relative_to(examples).as_posix() for p in sorted(Path(examples).rglob("*.html"))
            if re.search(r"<script\b", text := p.read_text(encoding="utf-8"), re.IGNORECASE)
            and not POLICY.search(text)]


def _listed(examples: Path) -> list[str]:
    """The example folders with a README.md or a report.md."""
    return [p.name for p in sorted(examples.iterdir()) if p.is_dir()
            and ((p / "README.md").is_file() or (p / "report.md").is_file())]


def _describe(folder: Path) -> str:
    """The report's judge, size and date (report.json, or result.json), after the title of its
    README.md, or else of its report.md."""
    title = None
    for name in ("README.md", "report.md"):
        if (folder / name).is_file():
            title = (folder / name).read_text(encoding="utf-8").splitlines()[0].lstrip("# ")
            title = title.strip()
            break
    report_json = next((p for p in (folder / "report.json", folder / "result.json")
                        if p.is_file()), None)
    r = json.loads(report_json.read_text(encoding="utf-8")) if report_json else {}
    fp, a = r.get("fingerprint", {}), r.get("anchors", {})
    parts = [title, fp.get("model"), f"{a.get('n_items')} items" if a.get("n_items") else None,
             f"{r.get('n_runs')} runs" if r.get("n_runs") else None,
             (r.get("generated_at") or r.get("made_at") or "")[:10] or None]
    return ", ".join(str(p) for p in parts if p)


def build(website: Path, examples: Path, out: Path) -> list[str]:
    """Write the site to `out`; return the report names."""
    website, examples, out = Path(website), Path(examples), Path(out)
    if unsafe := unsafe_pages(examples):
        raise SystemExit("an example page has a script but no Content-Security-Policy meta "
                         f"tag: {', '.join(unsafe)}")
    if out.exists():
        shutil.rmtree(out)
    def skip(folder: str, names: list[str]) -> set[str]:
        # README.md and the examples link only at the top: assets/examples/ is the check's own
        top = {"README.md", "examples"} if Path(folder) == website else set()
        return {n for n in names if n in top or n == "__pycache__"}

    shutil.copytree(website, out, ignore=skip)
    shutil.copytree(examples, out / "examples")
    names = []
    for report in sorted(examples.glob("*/report.html")):
        name = report.parent.name
        shutil.copyfile(report, out / "examples" / name / "index.html")
        names.append(name)
    listed = _listed(examples)
    # A folder with no report.html links to its report.md, which GitHub shows as a page.
    links = {n: f"{n}/" if n in names else f"{REPO}{n}/report.md" for n in listed}
    items = "\n".join(
        f'<li><a href="{html.escape(links[n])}">{html.escape(n)}</a>'
        f'<div class="meta">{html.escape(_describe(examples / n))}</div></li>'
        for n in listed)
    (out / "examples" / "index.html").write_text(INDEX.format(items=items), encoding="utf-8",
                                                 newline="\n")
    (out / ".nojekyll").write_text("", encoding="utf-8", newline="\n")
    return names


if __name__ == "__main__":
    defaults = ["website", "docs/examples", "_site"]
    args = sys.argv[1:4] + defaults[len(sys.argv[1:4]):]
    names = build(Path(args[0]), Path(args[1]), Path(args[2]))
    print(f"built {args[2]}: the website, and reports {', '.join(names)}")
