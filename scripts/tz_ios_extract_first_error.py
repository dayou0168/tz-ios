#!/usr/bin/env python3
"""Print the first useful build failure line from a captured log."""

from __future__ import annotations

import re
import sys
from pathlib import Path


PATTERNS = [
    re.compile(r"\berror:\s+.+", re.IGNORECASE),
    re.compile(r"FAILED:\s+.+"),
    re.compile(r"No space left on device", re.IGNORECASE),
    re.compile(r"Traceback \(most recent call last\):"),
    re.compile(r"(?:Exception|CalledProcessError):\s+.+"),
    re.compile(r"Could not (?:find|load|resolve|build)\s+.+", re.IGNORECASE),
]


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: tz_ios_extract_first_error.py BUILD_LOG")
    path = Path(sys.argv[1])
    if not path.is_file():
        print("first real error unavailable: build log was not created")
        return 0
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if any(pattern.search(line) for pattern in PATTERNS):
            print(line[:2000])
            return 0
    print("first real error unavailable: no specific error pattern was found; inspect the build step")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
