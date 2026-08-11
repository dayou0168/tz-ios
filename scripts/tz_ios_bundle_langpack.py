#!/usr/bin/env python3
"""Bundle and rebrand the pinned Simplified Chinese iOS language pack."""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
from pathlib import Path


ENTRY = re.compile(r'"((?:\\.|[^"\\])*)"\s*=\s*"((?:\\.|[^"\\])*)";', re.DOTALL)
BRAND = re.compile(r"(?<![A-Za-z0-9_./:@-])Telegram(?![A-Za-z0-9_-]|\.(?:org|me|dog)\b)")


def decode(value: str) -> str:
    return ast.literal_eval('"' + value + '"')


def encode(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-entries", type=int, required=True)
    args = parser.parse_args()

    source_bytes = args.source.read_bytes()
    digest = hashlib.sha256(source_bytes.replace(b"\r\n", b"\n")).hexdigest()
    if digest != args.expected_sha256.lower():
        raise SystemExit(f"unexpected language-pack SHA-256: {digest}")

    values: dict[str, str] = {}
    for match in ENTRY.finditer(source_bytes.decode("utf-8")):
        key = decode(match.group(1))
        if key in values:
            raise SystemExit(f"duplicate language-pack key: {key}")
        values[key] = BRAND.sub("TZ", decode(match.group(2)))
    if len(values) != args.expected_entries:
        raise SystemExit(f"unexpected language-pack entry count: {len(values)}")

    values.update({
        "TZ.LoginPassword.Title": "修改登录密码",
        "TZ.LoginPassword.Current": "当前登录密码",
        "TZ.LoginPassword.New": "新登录密码",
        "TZ.LoginPassword.Confirm": "确认新登录密码",
        "TZ.LoginPassword.Help": "此密码用于登录 TZ 账号，与两步验证密码无关。",
        "TZ.LoginPassword.Minimum": "请输入当前登录密码，新登录密码至少需要 8 个字符。",
        "TZ.LoginPassword.InvalidCurrent": "当前登录密码不正确。",
        "TZ.LoginPassword.Changed": "登录密码已修改。",
    })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as output:
        output.write(f"/* TZ iOS zh-Hans; source SHA-256 {digest} */\n\n")
        for key in sorted(values):
            output.write(f'"{encode(key)}" = "{encode(values[key])}";\n')
    print(f"Bundled {len(values)} Simplified Chinese iOS strings: {args.output}")


if __name__ == "__main__":
    main()
