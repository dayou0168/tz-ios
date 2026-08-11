#!/usr/bin/env python3
"""Remove every Apple code signature and provisioning profile from an IPA."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


def run(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, cwd=cwd, text=True, capture_output=True, check=False)


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"required macOS tool is unavailable: {name}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_archive_members(ipa: Path) -> None:
    with zipfile.ZipFile(ipa) as archive:
        for item in archive.infolist():
            member = Path(item.filename)
            if member.is_absolute() or ".." in member.parts:
                raise SystemExit(f"unsafe IPA member path: {item.filename!r}")


def is_macho(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    result = run("file", "-b", str(path))
    return result.returncode == 0 and "Mach-O" in result.stdout


def remove_signature(path: Path) -> bool:
    load_commands = run("otool", "-l", str(path))
    if load_commands.returncode != 0:
        raise SystemExit(f"otool could not inspect {path}: {load_commands.stderr.strip()}")
    was_signed = "cmd LC_CODE_SIGNATURE" in load_commands.stdout
    if was_signed:
        result = run("codesign", "--remove-signature", str(path))
        if result.returncode != 0:
            raise SystemExit(f"could not remove code signature from {path}: {result.stderr.strip()}")
    verification = run("otool", "-l", str(path))
    if verification.returncode != 0 or "cmd LC_CODE_SIGNATURE" in verification.stdout:
        raise SystemExit(f"LC_CODE_SIGNATURE remains in {path}")
    return was_signed


def load_bundle_identity(app: Path) -> tuple[str, str, str]:
    info_path = app / "Info.plist"
    if not info_path.is_file():
        raise SystemExit("main app is missing Info.plist")
    with info_path.open("rb") as stream:
        info = plistlib.load(stream)
    return (
        str(info.get("CFBundleIdentifier", "")),
        str(info.get("CFBundleShortVersionString", "")),
        str(info.get("CFBundleDisplayName") or info.get("CFBundleName") or ""),
    )


def make_unsigned(
    input_ipa: Path,
    output_ipa: Path,
    report_path: Path,
    *,
    preserve_provisioning_profiles: bool,
) -> None:
    for tool in ("codesign", "ditto", "file", "otool", "zip"):
        require_tool(tool)
    validate_archive_members(input_ipa)
    output_ipa.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="tz-ios-unsigned-") as temporary:
        root = Path(temporary) / "unpacked"
        root.mkdir()
        extracted = run("ditto", "-x", "-k", str(input_ipa), str(root))
        if extracted.returncode != 0:
            raise SystemExit(f"could not unpack IPA: {extracted.stderr.strip()}")

        apps = sorted((root / "Payload").glob("*.app"))
        if len(apps) != 1:
            raise SystemExit(f"expected one Payload/*.app, found {len(apps)}")
        bundle_id, version, brand = load_bundle_identity(apps[0])

        provisioning_profiles = [
            path for path in root.rglob("embedded.mobileprovision") if path.is_file()
        ]
        if preserve_provisioning_profiles:
            signing_targets = {apps[0], *apps[0].rglob("*.appex")}
            profile_targets = {path.parent for path in provisioning_profiles}
            if profile_targets != signing_targets:
                raise SystemExit(
                    "embedded provisioning profile set does not match the main app and extensions"
                )
        else:
            for path in provisioning_profiles:
                path.unlink()

        signature_directories = [
            path for path in root.rglob("_CodeSignature") if path.is_dir()
        ]
        for path in sorted(signature_directories, key=lambda value: len(value.parts), reverse=True):
            shutil.rmtree(path)

        macho_files = [path for path in root.rglob("*") if is_macho(path)]
        signed_macho_count = sum(1 for path in macho_files if remove_signature(path))

        leftovers = list(root.rglob("_CodeSignature"))
        if not preserve_provisioning_profiles:
            leftovers += list(root.rglob("embedded.mobileprovision"))
        if leftovers:
            raise SystemExit(f"signing metadata remains: {[str(path) for path in leftovers]}")
        for path in macho_files:
            commands = run("otool", "-l", str(path))
            if commands.returncode != 0 or "cmd LC_CODE_SIGNATURE" in commands.stdout:
                raise SystemExit(f"unsigned verification failed for {path}")

        if output_ipa.exists():
            output_ipa.unlink()
        packaged = run("zip", "-qry", "-y", str(output_ipa), ".", cwd=root)
        if packaged.returncode != 0:
            raise SystemExit(f"could not package unsigned IPA: {packaged.stderr.strip()}")

    report = {
        "artifact": output_ipa.name,
        "brand": brand,
        "bundle_id": bundle_id,
        "input_sha256": sha256_file(input_ipa),
        "mach_o_files_verified_unsigned": len(macho_files),
        "provisioning_profiles_preserved": (
            len(provisioning_profiles) if preserve_provisioning_profiles else 0
        ),
        "provisioning_profiles_removed": (
            0 if preserve_provisioning_profiles else len(provisioning_profiles)
        ),
        "sha256": sha256_file(output_ipa),
        "signature_directories_removed": len(signature_directories),
        "signed_mach_o_files_stripped": signed_macho_count,
        "signature_status": "UNSIGNED_REQUIRES_COMPLETE_APPLE_RESIGN_NOT_DIRECTLY_INSTALLABLE",
        "version": version,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_ipa", type=Path)
    parser.add_argument("output_ipa", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument(
        "--preserve-provisioning-profiles",
        action="store_true",
        help="retain embedded profiles as entitlement templates for a downstream signing platform",
    )
    args = parser.parse_args()
    input_ipa = args.input_ipa.resolve()
    if not input_ipa.is_file():
        raise SystemExit(f"input IPA does not exist: {input_ipa}")
    make_unsigned(
        input_ipa,
        args.output_ipa.resolve(),
        args.report.resolve(),
        preserve_provisioning_profiles=args.preserve_provisioning_profiles,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
