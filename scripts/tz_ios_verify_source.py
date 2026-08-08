#!/usr/bin/env python3
"""Fail closed unless the checked-out source is the auditable TZ build variant."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_UPSTREAM = "6ad963e5b62d354da79040f388ae2b9132fb17b8"
EXPECTED_BUNDLE_ID = "com.tianze.tz"
EXPECTED_APP_GROUP = "group.com.tianze.tz"
EXPECTED_GATEWAY = "tztg.tianze8.cc"
EXPECTED_PORT = "2398"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    lock = json.loads(read("TZ_UPSTREAM.lock"))
    identities = json.loads(read("TZ_IOS_IDENTITIES.json"))
    versions = json.loads(read("versions.json"))
    require(lock.get("commit") == EXPECTED_UPSTREAM, "upstream lock mismatch")
    require(versions.get("app") == "1.0.0", "TZ app version must be 1.0.0")
    require(versions.get("macos") == "26", "upstream macOS version changed")
    require(versions.get("xcode") == "26.2", "upstream Xcode version changed")
    require(str(versions.get("bazel", "")).startswith("8.4.2:"), "upstream Bazel version changed")
    require(identities.get("bundle_root") == EXPECTED_BUNDLE_ID, "identity manifest bundle root mismatch")
    require(identities.get("app_group") == EXPECTED_APP_GROUP, "identity manifest App Group mismatch")
    require(identities.get("gateway") == {
        "host": EXPECTED_GATEWAY,
        "port": int(EXPECTED_PORT),
        "numeric_origin_addresses_allowed_in_tz_configuration": False,
    }, "identity manifest gateway mismatch")

    renderer = read("scripts/tz_ios_render_build_config.py")
    fake_signing = read("scripts/tz_ios_prepare_fake_signing.py")
    ipa_verifier = read("scripts/tz_ios_verify_ipa.py")
    require(f'TZ_BUNDLE_ID = "{EXPECTED_BUNDLE_ID}"' in renderer, "rendered bundle root mismatch")
    require(f'TZ_BUNDLE_ID = "{EXPECTED_BUNDLE_ID}"' in fake_signing, "fake profile bundle root mismatch")
    require(f'TZ_APP_GROUP = "{EXPECTED_APP_GROUP}"' in fake_signing, "fake profile app group mismatch")
    require(f'EXPECTED_BUNDLE_ID = "{EXPECTED_BUNDLE_ID}"' in ipa_verifier, "IPA verifier bundle root mismatch")

    build = read("Telegram/BUILD")
    require('alternate_icon_folders = []' in build, "Telegram alternate icons are still enabled")
    require(build.count("<string>TZ</string>") >= 9, "main/extension TZ display-name coverage is incomplete")
    require("telegram_app_specific_url_scheme" in build, "TZ URL scheme is not configuration-driven")
    require("com.tianze.tz.theme" in build, "TZ theme UTI is missing")
    official_lists = build[build.index("official_bundle_ids = [") : build.index("apple_pay_merchants =")]
    require(EXPECTED_BUNDLE_ID not in official_lists, "TZ bundle must never activate Telegram-only entitlements")

    network = read("submodules/TelegramCore/Sources/Network/Network.swift")
    require(network.count(EXPECTED_GATEWAY) == 1, "TZ gateway hostname must have one canonical source definition")
    require(f"tzGatewayPort: UInt16 = {EXPECTED_PORT}" in network, "TZ gateway port mismatch")
    require("datacenterAddressOverrides = tzDatacenterAddressOverrides" in network, "gateway DC override is missing")
    require("1 ... 5" in network, "all logical datacenters are not covered")
    require(re.search(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])", network) is None,
            "numeric network address found in the TZ network source; origin IPs are forbidden")

    icon = read("Telegram/Telegram-iOS/Telegram.icon/Assets/Plane.svg")
    require("<title>TZ</title>" in icon and 'id="TZ"' in icon, "default app icon is not the TZ monogram")
    localized = read("Telegram/Telegram-iOS/en.lproj/Localizable.strings")
    for required_text in ("TZ · 天泽集团", "Enter your TZ Passcode", "Log in to TZ"):
        require(required_text in localized, f"missing minimum user-visible brand text: {required_text}")

    print(
        "TZ source verification passed: 1.0.0, com.tianze.tz namespace, "
        "restricted Telegram entitlements inactive, branded UI/icon, hostname-only gateway"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
