"""Whether a pull request changes code, for the workflows: reads the changed paths from stdin,
one a line, and prints code=true or code=false for $GITHUB_OUTPUT. Only docs and website pages
are not code. Anything else, a new folder too, and no paths at all, is: every job runs."""

from __future__ import annotations

import sys

NOT_CODE = ("docs/", "website/")


def is_code(path: str) -> bool:
    return not (path.startswith(NOT_CODE) or "/" not in path and path.endswith(".md"))


def changes_code(paths: list[str]) -> bool:
    return not paths or any(is_code(path) for path in paths)


def main() -> None:
    paths = [line.strip() for line in sys.stdin if line.strip()]
    print(f"code={'true' if changes_code(paths) else 'false'}")


if __name__ == "__main__":
    main()
