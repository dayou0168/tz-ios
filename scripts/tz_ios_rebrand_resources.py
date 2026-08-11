#!/usr/bin/env python3
"""Replace the upstream product name in iOS user-visible resource values."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRAND = re.compile(r"(?<![A-Za-z0-9_./:@-])Telegram(?![A-Za-z0-9_-]|\.(?:org|me|dog)\b)")
ENTRY = re.compile(r'("(?:\\.|[^"\\])*"\s*=\s*")((?:\\.|[^"\\])*)(";)', re.DOTALL)
PLIST_STRING = re.compile(r"(<string>)(.*?)(</string>)", re.DOTALL)


def rewrite(path: Path, pattern: re.Pattern[str]) -> int:
    source = path.read_text(encoding="utf-8")
    replacements = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal replacements
        body, count = BRAND.subn("TZ", match.group(2))
        replacements += count
        return match.group(1) + body + match.group(3)

    updated = pattern.sub(replace, source)
    if updated != source:
        path.write_text(updated, encoding="utf-8", newline="\n")
    return replacements


def main() -> None:
    strings = sorted((ROOT / "Telegram/Telegram-iOS").glob("*.lproj/*.strings"))
    plists = sorted((ROOT / "Telegram/Telegram-iOS").glob("*.lproj/AppIntentVocabulary.plist"))
    plists.extend([
        ROOT / "Telegram/Telegram-iOS/Info.plist",
        ROOT / "Telegram/Telegram-iOS/InfoBazel.plist",
    ])
    total = sum(rewrite(path, ENTRY) for path in strings)
    total += sum(rewrite(path, PLIST_STRING) for path in plists)
    print(f"Rebranded {total} user-visible iOS resource values")


if __name__ == "__main__":
    main()
