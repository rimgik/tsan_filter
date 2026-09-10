#!/usr/bin/env python3

import re
import sys
from collections import deque
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
START = ROOT / "README.md"
ARCHIVE = ROOT / "docs" / "archive"
LINK = re.compile(r"(?<!!)\[[^]]*\]\(([^)]+)\)")


def markdown_links(path):
    for target in LINK.findall(path.read_text()):
        target = target.strip().split(maxsplit=1)[0].strip("<>")
        parts = urlsplit(target)
        if parts.scheme or parts.netloc or not parts.path:
            continue
        yield (path.parent / unquote(parts.path)).resolve()


def is_below(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def main():
    queue = deque([START.resolve()])
    reached = set()
    errors = []

    while queue:
        page = queue.popleft()
        if page in reached:
            continue
        reached.add(page)
        for target in markdown_links(page):
            if not is_below(target, ROOT):
                errors.append(f"link leaves repository: {page} -> {target}")
                continue
            if not target.exists():
                errors.append(f"broken link: {page.relative_to(ROOT)} -> {target}")
                continue
            if is_below(target, ARCHIVE):
                errors.append(f"active page links archive: {page.relative_to(ROOT)}")
                continue
            if target.suffix.lower() == ".md":
                queue.append(target)

    active = {START.resolve()}
    active.update(
        path.resolve()
        for path in (ROOT / "docs").rglob("*.md")
        if not is_below(path.resolve(), ARCHIVE.resolve())
    )
    for page in sorted(active - reached):
        errors.append(f"unreachable active page: {page.relative_to(ROOT)}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"documentation check passed: {len(active)} active pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
