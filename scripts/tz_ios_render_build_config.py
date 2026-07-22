#!/usr/bin/env python3
"""Render the ephemeral configuration used by the fake-signing build.

The temporary TZ bundle namespace is paired with runtime-generated self-signed
profiles. The fake team identifier is not TZ's long-term Apple identity.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path


TZ_BUNDLE_ID = "com.tianze.tz"
TEMPORARY_TEAM_ID = "C67CF9S4VU"


def require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"required environment variable {name} is missing")
    return value


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: tz_ios_render_build_config.py OUTPUT_JSON")

    api_id = require_env("TZ_IOS_API_ID")
    api_hash = require_env("TZ_IOS_API_HASH")
    if not re.fullmatch(r"[0-9]+", api_id):
        raise SystemExit("TZ_IOS_API_ID must contain decimal digits only")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
        raise SystemExit("TZ_IOS_API_HASH must contain exactly 32 hexadecimal characters")

    configuration = {
        "bundle_id": TZ_BUNDLE_ID,
        "api_id": api_id,
        "api_hash": api_hash,
        "team_id": TEMPORARY_TEAM_ID,
        "app_center_id": "0",
        "is_internal_build": "true",
        "is_appstore_build": "false",
        "appstore_id": "0",
        "app_specific_url_scheme": "tz",
        "premium_iap_product_id": "",
        "enable_siri": False,
        "enable_icloud": False,
    }

    output = Path(sys.argv[1]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(configuration, indent=2) + "\n", encoding="utf-8")
    output.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print("ephemeral build configuration created with temporary fake-signing identity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
