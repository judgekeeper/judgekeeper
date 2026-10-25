"""Make the picture shown when a link to the site is pasted in a chat.

    python scripts/make_social_preview.py                  # writes website/assets/social-preview.png
    python scripts/make_social_preview.py --chrome PATH    # a Chrome or Chromium to use

It writes a small page with the site's colours and fonts (website/assets/fonts/) and the logo
at left: the headline, the five steps and the install command. Headless Chrome takes it as a
1200 x 630 PNG. scripts/share_preview.py holds the picture's size and alt text.
Standard library only.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "website" / "assets"
OUT = ASSETS / "social-preview.png"
WIDTH, HEIGHT = 1200, 630
CHROMES = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
           "/Applications/Chromium.app/Contents/MacOS/Chromium")
CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                "chrome")

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>
@font-face {{ font-family: "Manrope"; font-weight: 200 800;
  src: url("{fonts}/manrope-latin-wght-normal.woff2") format("woff2"); }}
@font-face {{ font-family: "JetBrains Mono"; font-weight: 500;
  src: url("{fonts}/jetbrains-mono-latin-500-normal.woff2") format("woff2"); }}
html, body {{ margin: 0; width: {width}px; height: {height}px; overflow: hidden; }}
body {{ background: #0b0c0e; color: #e6e8eb; font-family: "Manrope", sans-serif;
  display: flex; align-items: center; gap: 64px; padding: 0 88px; box-sizing: border-box;
  -webkit-font-smoothing: antialiased; }}
.logo {{ width: 200px; height: 225px; flex: none; }}
h1 {{ font-size: 64px; line-height: 1.04; letter-spacing: -.028em; font-weight: 800;
  margin: 0 0 28px; }}
.steps {{ font-size: 30px; font-weight: 600; color: #8b919a; margin: 0 0 40px; }}
.cmd {{ display: inline-block; font-family: "JetBrains Mono", monospace; font-weight: 500;
  font-size: 30px; padding: 14px 26px; border: 1px solid #262a30; border-radius: 10px;
  background: #07080a; }}
.cmd b {{ color: #10B981; font-weight: 500; }}
</style></head><body>
<div class="logo">{logo}</div>
<div>
<h1>Check your<br>LLM-as-a-judge<br>in 5 steps.</h1>
<p class="steps">Find. Mark. Measure. Fix. Re-check.</p>
<div class="cmd"><b>$</b> uvx judgekeeper</div>
</div>
</body></html>
"""


def find_chrome(given: str | None) -> str:
    for candidate in ([given] if given else [*CHROMES, *CHROME_NAMES]):
        path = candidate if Path(candidate).is_file() else shutil.which(candidate)
        if path:
            return path
    raise SystemExit("no Chrome or Chromium found: pass --chrome PATH")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chrome", help="a Chrome or Chromium to use")
    chrome = find_chrome(ap.parse_args().chrome)
    logo = (ASSETS / "logo.svg").read_text(encoding="utf-8")
    page = PAGE.format(fonts=(ASSETS / "fonts").as_uri(), width=WIDTH, height=HEIGHT,
                       logo=logo[logo.index("<svg"):])
    with tempfile.TemporaryDirectory() as tmp:
        html = Path(tmp) / "preview.html"
        html.write_text(page, encoding="utf-8")
        shot = Path(tmp) / "preview.png"
        # Chrome can stay open after it writes the picture, so it is stopped once it says so.
        proc = subprocess.Popen(
            [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--force-device-scale-factor=1", f"--window-size={WIDTH},{HEIGHT}",
             f"--user-data-dir={tmp}/profile", f"--screenshot={shot}", html.as_uri()],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            for line in proc.stderr:
                if "bytes written to file" in line:
                    break
        finally:
            proc.kill()
            proc.wait()
        if not shot.is_file():
            raise SystemExit("Chrome wrote no picture")
        data = shot.read_bytes()
    size = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:8] != b"\x89PNG\r\n\x1a\n" or size != (WIDTH, HEIGHT):
        raise SystemExit(f"Chrome wrote no {WIDTH} x {HEIGHT} PNG (got {size})")
    OUT.write_bytes(data)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(data):,} bytes")


if __name__ == "__main__":
    sys.exit(main())
