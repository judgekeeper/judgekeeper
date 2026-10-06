"""Build the static site: the website at the root, the example reports under examples/.

    python scripts/build_pages.py website docs/examples _site

- website/ is copied as it is (its README.md and its local `examples` link are left out).
- docs/examples/ is copied to examples/. Each <name>/report.html is also written as
  <name>/index.html, so https://www.judgekeeper.com/examples/<name>/ serves it,
  and examples/index.html lists the reports.

Standard library only; run by deploy/railway/Dockerfile.
"""

from __future__ import annotations

import html
import json
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
:root {{ --bg: #fff; --fg: #1a1a1a; --muted: #666; --line: #ddd; --link: #2457c5; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #161616; --fg: #ececec; --muted: #9a9a9a; --line: #333; --link: #7aa2ff; }} }}
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
<p>Validation reports written by judgekeeper and committed under
<code>docs/examples/</code> in the repository. Each one is the unedited
<code>report.html</code> of a real run.</p>
<ul>
{items}
</ul>
</main>
</body>
</html>
"""


def _describe(report_json: Path) -> str:
    if not report_json.is_file():
        return ""
    r = json.loads(report_json.read_text(encoding="utf-8"))
    fp, a = r.get("fingerprint", {}), r.get("anchors", {})
    parts = [fp.get("model"), f"{a.get('n_items')} items" if a.get("n_items") else None,
             f"{r.get('n_runs')} runs" if r.get("n_runs") else None,
             (r.get("generated_at") or "")[:10] or None]
    return ", ".join(str(p) for p in parts if p)


def build(website: Path, examples: Path, out: Path) -> list[str]:
    """Write the site to `out`; return the report names."""
    website, examples, out = Path(website), Path(examples), Path(out)
    if out.exists():
        shutil.rmtree(out)
    skip = shutil.ignore_patterns("README.md", "examples", "__pycache__")
    shutil.copytree(website, out, ignore=skip)
    shutil.copytree(examples, out / "examples")
    names = []
    for report in sorted(examples.glob("*/report.html")):
        name = report.parent.name
        shutil.copyfile(report, out / "examples" / name / "index.html")
        names.append(name)
    items = "\n".join(
        f'<li><a href="{html.escape(n)}/">{html.escape(n)}</a>'
        f'<div class="meta">{html.escape(_describe(examples / n / "report.json"))}</div></li>'
        for n in names)
    (out / "examples" / "index.html").write_text(INDEX.format(items=items), encoding="utf-8",
                                                 newline="\n")
    (out / ".nojekyll").write_text("", encoding="utf-8", newline="\n")
    return names


if __name__ == "__main__":
    defaults = ["website", "docs/examples", "_site"]
    args = sys.argv[1:4] + defaults[len(sys.argv[1:4]):]
    names = build(Path(args[0]), Path(args[1]), Path(args[2]))
    print(f"built {args[2]}: the website, and reports {', '.join(names)}")
