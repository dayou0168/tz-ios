#!/usr/bin/env python3
"""Strict static gate for a fake-signed TZ arm64 IPA candidate."""

from __future__ import annotations

import hashlib
import json
import plistlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


EXPECTED_VERSION = "1.0.9"
EXPECTED_BRAND = "TZ"
EXPECTED_BUNDLE_ID = "com.tianze.tz"
EXPECTED_APP_GROUP = "group.com.tianze.tz"
EXPECTED_ENDPOINT_HOST = "tztg.tianze8.cc"
EXPECTED_ENDPOINT_PORT = 2398
EXPECTED_RSA_FRAGMENT = "MIIBCgKCAQEA7lyx4eQO/cyY9icmLgUQ2nxZ++xP+q1AQEfCRSvilbS72Qvyj/dJ"
FAKE_TEAM_ID = "C67CF9S4VU"
FAKE_SIGNING_AUTHORITY = "Authority=Apple Distribution: Telegram FZ-LLC (C67CF9S4VU)"
FAKE_CERT_SHA256 = "eccdeb43dd50f4abdadf0dc6204c314298c16005567fcbf5d0a20a5761a93ba4"
EXPECTED_EXTENSION_IDS = {
    "com.tianze.tz.Share",
    "com.tianze.tz.NotificationContent",
    "com.tianze.tz.NotificationService",
    "com.tianze.tz.Widget",
    "com.tianze.tz.SiriIntents",
    "com.tianze.tz.BroadcastUpload",
}
RESTRICTED_ENTITLEMENTS = {
    "com.apple.developer.applesignin",
    "com.apple.developer.background-tasks.continued-processing.gpu",
    "com.apple.developer.carplay-messaging",
    "com.apple.developer.icloud-container-identifiers",
    "com.apple.developer.icloud-services",
    "com.apple.developer.in-app-payments",
    "com.apple.developer.pushkit.unrestricted-voip",
    "com.apple.developer.siri",
    "com.apple.developer.ubiquity-kvstore-identifier",
    "com.apple.developer.usernotifications.communication",
    "com.apple.developer.usernotifications.filtering",
}


def run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, text=True, capture_output=True, check=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for item in archive.infolist():
        resolved = (destination / item.filename).resolve()
        if resolved != root and root not in resolved.parents:
            raise SystemExit(f"unsafe IPA member path: {item.filename!r}")
    archive.extractall(destination)


def load_info(bundle: Path) -> dict:
    path = bundle / "Info.plist"
    if not path.is_file():
        raise SystemExit(f"bundle is missing Info.plist: {bundle}")
    with path.open("rb") as stream:
        return plistlib.load(stream)


def read_codesign_entitlements(bundle: Path) -> dict:
    result = run("codesign", "-d", "--entitlements", ":-", str(bundle))
    text = result.stdout + result.stderr
    start = text.find("<?xml")
    end = text.find("</plist>")
    if result.returncode != 0 or start < 0 or end < 0:
        raise SystemExit(f"could not extract signed entitlements from {bundle}")
    return plistlib.loads(text[start : end + len("</plist>")].encode("utf-8"))


def verify_entitlements(
    bundle_id: str,
    entitlements: dict,
    *,
    is_main: bool,
    require_team_identifier: bool,
) -> None:
    expected_application_id = f"{FAKE_TEAM_ID}.{bundle_id}"
    if entitlements.get("application-identifier") != expected_application_id:
        raise SystemExit(f"application-identifier mismatch for {bundle_id}")
    team_identifier = entitlements.get("com.apple.developer.team-identifier")
    if require_team_identifier and team_identifier != FAKE_TEAM_ID:
        raise SystemExit(f"fake team identifier mismatch for {bundle_id}")
    if not require_team_identifier and team_identifier not in (None, FAKE_TEAM_ID):
        raise SystemExit(f"unexpected team identifier for {bundle_id}: {team_identifier!r}")
    if entitlements.get("com.apple.security.application-groups") != [EXPECTED_APP_GROUP]:
        raise SystemExit(f"App Group mismatch for {bundle_id}")
    forbidden = sorted(RESTRICTED_ENTITLEMENTS.intersection(entitlements))
    if forbidden:
        raise SystemExit(f"restricted Apple entitlements found in {bundle_id}: {forbidden}")
    aps_environment = entitlements.get("aps-environment")
    if is_main and aps_environment != "development":
        raise SystemExit("main app fake APS entitlement must be development")
    if not is_main and aps_environment is not None:
        raise SystemExit(f"unexpected APS entitlement on extension {bundle_id}")
    associated_domains = entitlements.get("com.apple.developer.associated-domains")
    if is_main and associated_domains != ["applinks:tg.tianze8.cc"]:
        raise SystemExit("main app associated domain must be applinks:tg.tianze8.cc")
    if not is_main and associated_domains is not None:
        raise SystemExit(f"unexpected associated domain on extension {bundle_id}")


def verify_bundle(bundle: Path, main_bundle_id: str, report_root: Path, *, require_entitlements: bool) -> dict:
    info = load_info(bundle)
    executable_name = info.get("CFBundleExecutable")
    bundle_id = info.get("CFBundleIdentifier")
    if not isinstance(executable_name, str) or not executable_name:
        raise SystemExit(f"CFBundleExecutable is missing in {bundle}")
    if not isinstance(bundle_id, str) or not bundle_id:
        raise SystemExit(f"CFBundleIdentifier is missing in {bundle}")
    if bundle_id != main_bundle_id and not bundle_id.startswith(main_bundle_id + "."):
        raise SystemExit(f"nested bundle identifier is outside the main prefix: {bundle_id}")
    if bundle.suffix in {".app", ".appex"}:
        version = info.get("CFBundleShortVersionString")
        brand = info.get("CFBundleDisplayName") or info.get("CFBundleName")
        if version != EXPECTED_VERSION:
            raise SystemExit(f"version mismatch in {bundle_id}: {version!r}")
        if brand != EXPECTED_BRAND:
            raise SystemExit(f"brand mismatch in {bundle_id}: {brand!r}")

    executable = bundle / executable_name
    if not executable.is_file():
        raise SystemExit(f"bundle executable does not exist: {executable}")
    arch_result = run("lipo", "-archs", str(executable))
    if arch_result.returncode != 0:
        raise SystemExit(f"lipo could not inspect {executable}: {arch_result.stderr.strip()}")
    architectures = arch_result.stdout.split()
    if "arm64" not in architectures:
        raise SystemExit(f"arm64 is missing from {bundle_id}: {architectures}")
    forbidden = sorted({"armv7", "armv7s", "i386", "x86_64"}.intersection(architectures))
    if forbidden:
        raise SystemExit(f"non-arm64 device/simulator slices found in {bundle_id}: {forbidden}")

    signing_result = run("codesign", "-d", "--verbose=4", str(bundle))
    signing_text = signing_result.stdout + signing_result.stderr
    if signing_result.returncode != 0:
        raise SystemExit(f"codesign could not inspect {bundle_id}: {signing_text.strip()}")
    if FAKE_SIGNING_AUTHORITY not in signing_text:
        raise SystemExit(f"unexpected signing authority for {bundle_id}; refusing to mislabel signature state")

    if require_entitlements:
        verify_entitlements(
            bundle_id,
            read_codesign_entitlements(bundle),
            is_main=bundle_id == main_bundle_id,
            require_team_identifier=False,
        )
        verify_fake_profile(bundle, bundle_id)

    return {
        "relative_path": str(bundle.relative_to(report_root)),
        "bundle_id": bundle_id,
        "architectures": architectures,
        "fake_signing_authority_confirmed": True,
        "restricted_entitlements_absent": require_entitlements,
    }


def verify_fake_profile(bundle: Path, expected_bundle_id: str) -> None:
    profile = bundle / "embedded.mobileprovision"
    if not profile.is_file():
        raise SystemExit(f"bundle is missing embedded.mobileprovision: {expected_bundle_id}")
    result = run("security", "cms", "-D", "-i", str(profile))
    if result.returncode != 0:
        raise SystemExit(f"could not decode embedded.mobileprovision: {result.stderr.strip()}")
    data = plistlib.loads(result.stdout.encode("utf-8"))
    certificates = data.get("DeveloperCertificates", [])
    fingerprints = {hashlib.sha256(bytes(certificate)).hexdigest() for certificate in certificates}
    if FAKE_CERT_SHA256 not in fingerprints:
        raise SystemExit("embedded profile does not contain the locked upstream fake certificate")
    entitlements = data.get("Entitlements", {})
    verify_entitlements(
        expected_bundle_id,
        entitlements,
        is_main=expected_bundle_id == EXPECTED_BUNDLE_ID,
        require_team_identifier=True,
    )


def contains_bytes(root: Path, needle: bytes) -> bool:
    for path in root.rglob("*"):
        if not path.is_file() or path.stat().st_size > 1024 * 1024 * 1024:
            continue
        with path.open("rb") as stream:
            overlap = b""
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                data = overlap + chunk
                if needle in data:
                    return True
                overlap = data[-max(0, len(needle) - 1) :]
    return False


def verify_network_profile(root: Path, info: dict) -> None:
    if info.get("TZGatewayHost") != EXPECTED_ENDPOINT_HOST:
        raise SystemExit("main Info.plist TZGatewayHost mismatch")
    if info.get("TZGatewayPort") != EXPECTED_ENDPOINT_PORT:
        raise SystemExit("main Info.plist TZGatewayPort mismatch")
    if info.get("TZSigningStatus") != "REQUIRES-FULL-RESIGN":
        raise SystemExit("main Info.plist does not disclose the fake-signing boundary")
    if not contains_bytes(root, EXPECTED_ENDPOINT_HOST.encode("utf-8")):
        raise SystemExit("expected private endpoint was not found in the unpacked IPA")
    if not contains_bytes(root, EXPECTED_RSA_FRAGMENT.encode("ascii")):
        raise SystemExit("expected gramsrv RSA public key was not found in the unpacked IPA")


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: tz_ios_verify_ipa.py INPUT_IPA OUTPUT_DIRECTORY")
    ipa = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    if not ipa.is_file():
        raise SystemExit(f"IPA does not exist: {ipa}")
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="tz-ipa-verify-") as temp_dir:
        extracted = Path(temp_dir)
        with zipfile.ZipFile(ipa) as archive:
            safe_extract(archive, extracted)

        payload = extracted / "Payload"
        apps = sorted(path for path in payload.glob("*.app") if path.is_dir())
        if len(apps) != 1:
            raise SystemExit(f"expected exactly one Payload/*.app, found {len(apps)}")
        app = apps[0]
        info = load_info(app)
        version = info.get("CFBundleShortVersionString")
        brand = info.get("CFBundleDisplayName") or info.get("CFBundleName")
        bundle_id = info.get("CFBundleIdentifier")
        if version != EXPECTED_VERSION:
            raise SystemExit(f"unexpected app version: {version!r}; expected {EXPECTED_VERSION!r}")
        if brand != EXPECTED_BRAND:
            raise SystemExit(f"unexpected app brand: {brand!r}; expected {EXPECTED_BRAND!r}")
        if bundle_id != EXPECTED_BUNDLE_ID:
            raise SystemExit(f"unexpected main Bundle ID: {bundle_id!r}")

        verify_network_profile(extracted, info)

        code_verify = run("codesign", "--verify", "--deep", "--strict", str(app))
        if code_verify.returncode != 0:
            raise SystemExit(f"fake signature integrity check failed: {code_verify.stderr.strip()}")

        extensions = sorted(path for path in app.rglob("*.appex") if path.is_dir())
        extension_ids = {load_info(path).get("CFBundleIdentifier") for path in extensions}
        if None in extension_ids:
            raise SystemExit("an extension is missing CFBundleIdentifier")
        if extension_ids != EXPECTED_EXTENSION_IDS:
            raise SystemExit(
                f"extension Bundle ID set mismatch: missing={sorted(EXPECTED_EXTENSION_IDS - extension_ids)}, "
                f"unexpected={sorted(extension_ids - EXPECTED_EXTENSION_IDS)}"
            )
        if (app / "Watch").exists():
            raise SystemExit("Watch app is unexpectedly embedded without a finalized Apple identity")

        frameworks = sorted(path for path in app.rglob("*.framework") if path.is_dir())
        bundle_reports = [verify_bundle(app, bundle_id, payload, require_entitlements=True)]
        bundle_reports.extend(
            verify_bundle(bundle, bundle_id, payload, require_entitlements=True) for bundle in extensions
        )
        bundle_reports.extend(
            verify_bundle(bundle, bundle_id, payload, require_entitlements=False) for bundle in frameworks
        )

    final_ipa = output / "TZ-1.0.9-ios-arm64-REQUIRES-FULL-RESIGN.ipa"
    shutil.copy2(ipa, final_ipa)
    ipa_sha256 = sha256_file(final_ipa)
    (output / "SHA256SUMS.txt").write_text(
        f"{ipa_sha256}  {final_ipa.name}\n", encoding="utf-8"
    )
    report = {
        "artifact": final_ipa.name,
        "sha256": ipa_sha256,
        "version": EXPECTED_VERSION,
        "brand": EXPECTED_BRAND,
        "endpoint_static_check": "hostname_and_port_confirmed",
        "mtproto_rsa_static_check": "gramsrv_public_key_confirmed",
        "bundle_id": EXPECTED_BUNDLE_ID,
        "app_group": EXPECTED_APP_GROUP,
        "extensions": sorted(EXPECTED_EXTENSION_IDS),
        "bundle_identity": "TZ_BUNDLE_NAMESPACE_WITH_TEMPORARY_SELF_SIGNED_TEAM_NOT_LONG_TERM_APPLE_IDENTITY",
        "signature_status": "FAKE_SELF_SIGNED_REQUIRES_FULL_RESIGN_NOT_DIRECTLY_INSTALLABLE",
        "install_tested": False,
        "runtime_tested": False,
        "bundles": bundle_reports,
    }
    (output / "IPA_STATIC_VERIFICATION.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("IPA static verification passed; package remains fake-signed and requires full re-signing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
