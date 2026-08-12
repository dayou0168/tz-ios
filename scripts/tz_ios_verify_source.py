#!/usr/bin/env python3
"""Fail closed unless the checkout is the auditable TZ iOS 1.0.11 variant."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_UPSTREAM = "6ad963e5b62d354da79040f388ae2b9132fb17b8"
EXPECTED_BUNDLE_ID = "com.tianze.tz"
EXPECTED_GATEWAY = "tztg.tianze8.cc"
EXPECTED_PUBLIC_HOST = "tg.tianze8.cc"
EXPECTED_PORT = "2398"
EXPECTED_RSA_FRAGMENT = "MIIBCgKCAQEA7lyx4eQO/cyY9icmLgUQ2nxZ++xP+q1AQEfCRSvilbS72Qvyj/dJ"
VISIBLE_TELEGRAM = re.compile(r"(?<![A-Za-z0-9_./:@-])Telegram(?![A-Za-z0-9_-]|\.(?:org|me|dog)\b)")


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
    require(versions.get("app") == "1.0.11", "TZ app version must be 1.0.11")
    require(identities.get("bundle_root") == EXPECTED_BUNDLE_ID, "bundle root mismatch")
    require(identities.get("app_group") is None, "single-target build must not declare an App Group")
    require(identities.get("targets") == {"main": EXPECTED_BUNDLE_ID}, "single-target manifest mismatch")
    require(identities.get("runtime_storage") == {
        "mode": "private Application Support/com.tianze.tz",
        "app_group_required": False,
        "architecture": "single-target",
    }, "runtime storage manifest mismatch")
    require(identities.get("gateway") == {
        "host": EXPECTED_GATEWAY,
        "port": int(EXPECTED_PORT),
        "numeric_origin_addresses_allowed_in_tz_configuration": False,
    }, "gateway manifest mismatch")

    build = read("Telegram/BUILD")
    require(build.count("<string>TZ</string>") >= 9, "TZ display-name coverage is incomplete")
    require('associated_domains_fragment = "" if telegram_bundle_id == "com.tianze.tz"' in build,
            "TZ must not request Associated Domains")
    require('app_groups_fragment = "" if telegram_bundle_id == "com.tianze.tz"' in build,
            "TZ must not request App Groups")
    require("com.tianze.tz.theme" in build, "TZ theme UTI is missing")

    network = read("submodules/TelegramCore/Sources/Network/Network.swift")
    require(network.count(EXPECTED_GATEWAY) == 1, "gateway must have one canonical definition")
    require(f"tzGatewayPort: UInt16 = {EXPECTED_PORT}" in network, "gateway port mismatch")
    require("datacenterAddressOverrides = tzDatacenterAddressOverrides" in network, "DC override is missing")
    require("1 ... 5" in network, "all logical DCs are not covered")
    require(re.search(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])", network) is None,
            "numeric origin address found in network source")

    auth_service = read("submodules/MtProtoKit/Sources/MTDatacenterAuthMessageService.m")
    require(auth_service.count(EXPECTED_RSA_FRAGMENT) == 2, "gramsrv RSA must cover test and production")
    require("MIIBCgKCAQEAyMEdY1aR+sCR3ZSJrtzt" not in auth_service, "official test RSA remains")
    require("MIIBCgKCAQEA6LszBcC1LGzyr992NzE0" not in auth_service, "official production RSA remains")

    for relative in (
        "submodules/UrlHandling/Sources/UrlHandling.swift",
        "submodules/TelegramUI/Sources/OpenUrl.swift",
        "submodules/TelegramUI/Sources/Chat/ChatControllerOpenLinkContextMenu.swift",
    ):
        require(EXPECTED_PUBLIC_HOST in read(relative), f"public host missing from {relative}")

    require("length == 8 ? .loginPassword" in read("submodules/TelegramCore/Sources/State/AccountState.swift"),
            "gramsrv password challenge is not explicit")
    require("case loginPassword" in read("submodules/TelegramCore/Sources/SyncCore/SyncCore_UnauthorizedAccountState.swift"),
            "login-password authorization type is missing")
    require('languageCode: "zh-hans"' in read("submodules/TelegramPresentationData/Sources/DefaultPresentationStrings.swift"),
            "default language is not Simplified Chinese")
    require('"TZ.LoginPassword.Title" = "修改登录密码";' in read("Telegram/Telegram-iOS/zh-Hans.lproj/Localizable.strings"),
            "Chinese login-password strings are missing")
    require("self.strings.TZ_LoginPassword_Help" in read("submodules/AuthorizationUI/Sources/AuthorizationSequenceCodeEntryControllerNode.swift"),
            "login-password screen does not use the TZ-specific help text")
    presentation_data = read("submodules/TelegramPresentationData/Sources/PresentationData.swift")
    require('forLocalization: "zh-Hans"' in presentation_data and "bundledDict.merge(primaryDict" in presentation_data,
            "saved Simplified Chinese settings do not fall back to the bundled language pack")

    for strings_path in (ROOT / "Telegram" / "Telegram-iOS").glob("*.lproj/*.strings"):
        for line_number, line in enumerate(strings_path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.match(r'^\s*"(?:[^"\\]|\\.)*"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;', line)
            if match and VISIBLE_TELEGRAM.search(match.group(1)):
                raise SystemExit(f"visible Telegram brand remains in {strings_path.relative_to(ROOT)}:{line_number}")

    app_delegate = (ROOT / "submodules/TelegramUI/Sources/AppDelegate.swift").read_text(encoding="utf-8")
    require("Using private application container %@" in app_delegate, "private-container storage is missing")
    require("applicationSupportDirectory" in app_delegate, "private-container storage location is missing")
    require("containerURL(forSecurityApplicationGroupIdentifier: appGroupName)" not in app_delegate,
            "main app still depends on App Groups")
    require("configuration.sharedContainerIdentifier" not in app_delegate,
            "main app background URLSession still depends on App Groups")

    workflow = read(".github/workflows/tz-ios-macos-build.yml")
    require("--disableExtensions" in workflow, "single-target build must disable extensions")
    require("--disablePushNotifications" in workflow, "unsigned build must not require APNs signing permission")

    print("TZ iOS source verification passed: 1.0.11 single-target private-container client, working Chinese default, TZ branding, public links, explicit login password, gramsrv network/RSA")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
