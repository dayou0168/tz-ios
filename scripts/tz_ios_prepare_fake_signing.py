#!/usr/bin/env python3
"""Create TZ-specific, self-signed fake profiles for reproducible device builds.

This does not create or emulate Apple authorization. It rewrites the public
Telegram-iOS verification profiles to the TZ bundle namespace, removes every
restricted entitlement, and signs the CMS envelope with the upstream public
self-signed certificate already imported into ``temp.keychain``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import plistlib
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path


TZ_BUNDLE_ID = "com.tianze.tz"
TZ_APP_GROUP = "group.com.tianze.tz"
FAKE_TEAM_ID = "C67CF9S4VU"
FAKE_SIGNING_IDENTITY = "Apple Distribution: Telegram FZ-LLC (C67CF9S4VU)"

PROFILE_SUFFIXES = {
    "Telegram.mobileprovision": "",
    "Share.mobileprovision": ".Share",
    "NotificationContent.mobileprovision": ".NotificationContent",
    "NotificationService.mobileprovision": ".NotificationService",
    "Widget.mobileprovision": ".Widget",
    "Intents.mobileprovision": ".SiriIntents",
    "BroadcastUpload.mobileprovision": ".BroadcastUpload",
    "WatchApp.mobileprovision": ".watchkitapp",
    "WatchExtension.mobileprovision": ".watchkitapp.watchkitextension",
}

RESTRICTED_ENTITLEMENTS = {
    "beta-reports-active",
    "com.apple.developer.applesignin",
    "com.apple.developer.background-tasks.continued-processing.gpu",
    "com.apple.developer.carplay-messaging",
    "com.apple.developer.icloud-container-development-container-identifiers",
    "com.apple.developer.icloud-container-environment",
    "com.apple.developer.icloud-container-identifiers",
    "com.apple.developer.icloud-services",
    "com.apple.developer.in-app-payments",
    "com.apple.developer.pushkit.unrestricted-voip",
    "com.apple.developer.siri",
    "com.apple.developer.ubiquity-container-identifiers",
    "com.apple.developer.ubiquity-kvstore-identifier",
    "com.apple.developer.usernotifications.communication",
    "com.apple.developer.usernotifications.filtering",
}


def run(arguments: list[str], *, stdin: bytes | None = None) -> bytes:
    result = subprocess.run(arguments, input=stdin, capture_output=True, check=False)
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(f"command failed ({arguments[0]}): {message}")
    return result.stdout


def decode_profile(path: Path) -> dict:
    return plistlib.loads(run(["security", "cms", "-D", "-i", str(path)]))


def sanitized_entitlements(suffix: str) -> dict:
    bundle_id = TZ_BUNDLE_ID + suffix
    entitlements: dict[str, object] = {
        "application-identifier": f"{FAKE_TEAM_ID}.{bundle_id}",
        "com.apple.developer.team-identifier": FAKE_TEAM_ID,
        "com.apple.security.application-groups": [TZ_APP_GROUP],
        "get-task-allow": False,
        "keychain-access-groups": [f"{FAKE_TEAM_ID}.*"],
    }
    if suffix == "":
        entitlements["aps-environment"] = "development"
        entitlements["com.apple.developer.associated-domains"] = ["applinks:tg.tianze8.cc"]
    return entitlements


def rewrite_profile(source: Path, destination: Path, suffix: str) -> None:
    profile = decode_profile(source)
    expiration = profile.get("ExpirationDate")
    if not isinstance(expiration, dt.datetime) or expiration <= dt.datetime.now():
        raise SystemExit(f"source fake profile is expired: {source.name}")

    bundle_id = TZ_BUNDLE_ID + suffix
    profile["AppIDName"] = f"TZ fake profile {bundle_id}"
    profile["ApplicationIdentifierPrefix"] = [FAKE_TEAM_ID]
    profile["Entitlements"] = sanitized_entitlements(suffix)
    profile["Name"] = f"TZ SELF-SIGNED REQUIRES FULL RESIGN {bundle_id}"
    profile["TeamIdentifier"] = [FAKE_TEAM_ID]
    profile["TeamName"] = "TZ SELF-SIGNED - NOT APPLE AUTHORIZED"
    profile["UUID"] = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"tz-fake-profile:{bundle_id}"))
    profile.pop("DER-Encoded-Profile", None)

    unsigned_data = plistlib.dumps(profile, fmt=plistlib.FMT_XML, sort_keys=False)
    with tempfile.NamedTemporaryFile(suffix=".plist") as unsigned:
        unsigned.write(unsigned_data)
        unsigned.flush()
        run([
            "security",
            "cms",
            "-S",
            "-k",
            "temp.keychain",
            "-N",
            FAKE_SIGNING_IDENTITY,
            "-i",
            unsigned.name,
            "-o",
            str(destination),
        ])

    rewritten = decode_profile(destination)
    entitlements = rewritten.get("Entitlements", {})
    if entitlements != sanitized_entitlements(suffix):
        raise SystemExit(f"rewritten entitlements mismatch for {destination.name}")
    forbidden = RESTRICTED_ENTITLEMENTS.intersection(entitlements)
    if forbidden:
        raise SystemExit(f"restricted entitlements survived in {destination.name}: {sorted(forbidden)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()

    source = arguments.source.resolve()
    output = arguments.output.resolve()
    if source == output or source in output.parents:
        raise SystemExit("output must not be inside or equal to the source fake-signing directory")
    if output.exists():
        shutil.rmtree(output)
    (output / "profiles").mkdir(parents=True)
    shutil.copytree(source / "certs", output / "certs")

    for filename, suffix in PROFILE_SUFFIXES.items():
        input_profile = source / "profiles" / filename
        if not input_profile.is_file():
            raise SystemExit(f"missing source profile: {filename}")
        rewrite_profile(input_profile, output / "profiles" / filename, suffix)

    print(
        "prepared 9 TZ-specific self-signed fake profiles; "
        "restricted Apple entitlements removed; full re-signing remains mandatory"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
