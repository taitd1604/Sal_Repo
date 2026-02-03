#!/usr/bin/env python3
"""Build the GitHub Pages public site into `docs/`.

Why:
- GitHub Pages is static hosting: anything inside the published folder is public.
- To share only `public.html` and keep the private dashboard (`index.html`) offline,
  we publish only a sanitized site from `docs/`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SOURCE_PUBLIC_HTML = REPO_ROOT / "public.html"
SOURCE_PUBLIC_CSS = REPO_ROOT / "dashboard" / "public.css"
SOURCE_PUBLIC_JS = REPO_ROOT / "dashboard" / "public.js"
SOURCE_PUBLIC_CSV = REPO_ROOT / "data" / "shifts_public.csv"

DEST_ROOT = REPO_ROOT / "docs"
DEST_PUBLIC_HTML = DEST_ROOT / "public.html"
DEST_INDEX_HTML = DEST_ROOT / "index.html"
DEST_NOJEKYLL = DEST_ROOT / ".nojekyll"
DEST_PUBLIC_CSS = DEST_ROOT / "dashboard" / "public.css"
DEST_PUBLIC_JS = DEST_ROOT / "dashboard" / "public.js"
DEST_PUBLIC_CSV = DEST_ROOT / "data" / "shifts_public.csv"

FORBIDDEN_IN_PAGES = [
    DEST_ROOT / "data" / "shifts.csv",
]


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def write_redirect_index() -> None:
    DEST_INDEX_HTML.write_text(
        """<!DOCTYPE html>
<html lang="vi">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta http-equiv="refresh" content="0; url=./public.html" />
    <title>Soundman OT Summary</title>
    <script>
      window.location.replace("./public.html");
    </script>
  </head>
  <body>
    <p>Nếu không tự chuyển trang, mở <a href="./public.html">public dashboard</a>.</p>
  </body>
</html>
""",
        encoding="utf-8",
    )


def main() -> None:
    required_sources = [
        SOURCE_PUBLIC_HTML,
        SOURCE_PUBLIC_CSS,
        SOURCE_PUBLIC_JS,
        SOURCE_PUBLIC_CSV,
    ]
    missing = [path for path in required_sources if not path.exists()]
    if missing:
        joined = "\n".join(f"- {path.relative_to(REPO_ROOT)}" for path in missing)
        raise SystemExit(f"Missing required source file(s):\n{joined}")

    DEST_ROOT.mkdir(parents=True, exist_ok=True)
    DEST_NOJEKYLL.write_text("", encoding="utf-8")

    copy_file(SOURCE_PUBLIC_HTML, DEST_PUBLIC_HTML)
    write_redirect_index()
    copy_file(SOURCE_PUBLIC_CSS, DEST_PUBLIC_CSS)
    copy_file(SOURCE_PUBLIC_JS, DEST_PUBLIC_JS)
    copy_file(SOURCE_PUBLIC_CSV, DEST_PUBLIC_CSV)

    forbidden_present = [path for path in FORBIDDEN_IN_PAGES if path.exists()]
    if forbidden_present:
        joined = "\n".join(f"- {path.relative_to(REPO_ROOT)}" for path in forbidden_present)
        raise SystemExit(f"Refusing to publish forbidden file(s) into GitHub Pages:\n{joined}")

    print(f"✅ Built public site at {DEST_ROOT.relative_to(REPO_ROOT)}/")


if __name__ == "__main__":
    main()

