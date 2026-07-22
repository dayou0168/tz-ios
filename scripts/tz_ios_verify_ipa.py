#!/usr/bin/env python3
"""Strict static gate for a fake-signed TZ arm64 IPA candidate."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


EXPECTED_VERSION = "1.0.1"
EXPECTED_BRAND = "TZ"
TEMPORARY_BUNDLE_ID = "ph.telegra.Telegraph"
FAKE_SIGNING_AUTHORITY = "Authority=Apple Distribution: Telegram FZ-LLC (C67CF9S4VU)"
FAKE_CERT_SHA256 = "eccdeb43dd50f4abdadf0dc6204c314298c16005567fcbf5d0a20a5761a93ba4"


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


def verify_bundle(bundle: Path, main_bundle_id: str) -> dict:
    info = load_info(bundle)
    executable_name = info.get("CFBundleExecutable")
    bundle_id = info.get("CFBundleIdentifier")
    if not isinstance(executable_name, str) or not executable_name:
        raise SystemExit(f"CFBundleExecutable is missing in {bundle}")
    if not isinstance(bundle_id, str) or not bundle_id:
        raise SystemExit(f"CFBundleIdentifier is missing in {bundle}")
    if bundle_id != main_bundle_id and not bundle_id.startswith(main_bundle_id + "."):
        raise SystemExit(f"nested bundle identifier is outside the main prefix: {bundle_id}")

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

    return {
        "relative_path": str(bundle),
        "bundle_id": bundle_id,
        "architectures": architectures,
        "fake_signing_authority_confirmed": True,
    }


def verify_fake_profile(app: Path) -> None:
    profile = app / "embedded.mobileprovision"
    if not profile.is_file():
        raise SystemExit("main app is missing embedded.mobileprovision")
    result = run("security", "cms", "-D", "-i", str(profile))
    if result.returncode != 0:
        raise SystemExit(f"could not decode embedded.mobileprovision: {result.stderr.strip()}")
    data = plistlib.loads(result.stdout.encode("utf-8"))
    certificates = data.get("DeveloperCertificates", [])
    fingerprints = {hashlib.sha256(bytes(certificate)).hexdigest() for certificate in certificates}
    if FAKE_CERT_SHA256 not in fingerprints:
        raise SystemExit("embedded profile does not contain the locked upstream fake certificate")


def verify_endpoint(root: Path) -> None:
    expected = os.environ.get("TZ_IOS_EXPECTED_ENDPOINT", "")
    if len(expected) < 8:
        raise SystemExit("TZ_IOS_EXPECTED_ENDPOINT is missing or implausibly short")
    needle = expected.encode("utf-8")
    for path in root.rglob("*"):
        if not path.is_file() or path.stat().st_size > 1024 * 1024 * 1024:
            continue
        with path.open("rb") as stream:
            overlap = b""
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                data = overlap + chunk
                if needle in data:
                    return
                overlap = data[-max(0, len(needle) - 1) :]
    raise SystemExit("expected private endpoint was not found in the unpacked IPA")


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
        if bundle_id != TEMPORARY_BUNDLE_ID:
            raise SystemExit("fake-signing build must use the documented temporary bundle identity")

        verify_endpoint(extracted)
        verify_fake_profile(app)

        bundles = [app]
        bundles.extend(sorted(path for path in app.rglob("*.appex") if path.is_dir()))
        bundle_reports = [verify_bundle(bundle, bundle_id) for bundle in bundles]

    final_ipa = output / "TZ-1.0.1-ios-arm64-REQUIRES-FULL-RESIGN.ipa"
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
        "endpoint_static_check": "present_without_disclosure",
        "bundle_identity": "TEMPORARY_UPSTREAM_FAKE_SIGNING_IDENTITY_NOT_TZ_LONG_TERM_IDENTITY",
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
