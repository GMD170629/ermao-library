from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "pdfium.lock.json"
EXPECTED_REVISION = "875172eae557a308d0c5b2be43822814c8a885bb"
ANDROID_ABIS = ("arm64-v8a", "armeabi-v7a", "x86_64")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_artifact(artifact: object) -> tuple[str, Path]:
    if not isinstance(artifact, dict):
        raise SystemExit("PDFium artifact entry must be an object")
    platform = artifact.get("platform")
    relative_path = artifact.get("path")
    expected_hash = artifact.get("sha256")
    expected_size = artifact.get("sizeBytes")
    license_relative_path = artifact.get("licensePath")
    if not all(
        isinstance(value, str)
        for value in (platform, relative_path, expected_hash, license_relative_path)
    ) or not isinstance(expected_size, int):
        raise SystemExit("PDFium artifact entry is incomplete")

    path = ROOT / relative_path
    if not path.is_file():
        raise SystemExit(f"Missing PDFium artifact: {path}")
    if expected_hash != sha256(path):
        raise SystemExit(f"PDFium artifact hash mismatch: {path}")
    if expected_size != path.stat().st_size:
        raise SystemExit(f"PDFium artifact size mismatch: {path}")
    license_path = ROOT / license_relative_path
    if not license_path.is_file():
        raise SystemExit(f"Missing PDFium license bundle: {license_path}")
    return platform, path


def validate_android_aar(path: Path) -> None:
    expected_members = {f"jni/{abi}/libshuku_pdfium.so" for abi in ANDROID_ABIS}
    try:
        with zipfile.ZipFile(path) as archive:
            actual_members = {
                name
                for name in archive.namelist()
                if name.startswith("jni/") and name.endswith("/libshuku_pdfium.so")
            }
            if actual_members != expected_members:
                raise SystemExit(
                    "Android PDFium AAR ABI set does not match the lock: "
                    f"{sorted(actual_members)}"
                )
            for abi in ANDROID_ABIS:
                member = f"jni/{abi}/libshuku_pdfium.so"
                source_library = (
                    ROOT / "artifacts" / "android" / "jni" / abi / "libshuku_pdfium.so"
                )
                if not source_library.is_file():
                    raise SystemExit(
                        f"Missing Android PDFium JNI library: {source_library}"
                    )
                if hashlib.sha256(archive.read(member)).hexdigest() != sha256(
                    source_library
                ):
                    raise SystemExit(
                        f"Android PDFium AAR does not contain the tracked {abi} library"
                    )
    except zipfile.BadZipFile as error:
        raise SystemExit(
            f"Android PDFium artifact is not a valid AAR: {path}"
        ) from error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--platform",
        choices=("all", "android"),
        default="all",
        help="Validate a physically accepted platform or require the final cross-platform freeze.",
    )
    arguments = parser.parse_args()
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if lock.get("pdfiumCommit") != EXPECTED_REVISION:
        raise SystemExit("PDFium lock revision changed")
    artifacts = lock.get("artifacts")
    if not isinstance(artifacts, list):
        raise SystemExit("PDFium lock artifacts must be a list")

    validated = [validate_artifact(artifact) for artifact in artifacts]
    if arguments.platform == "android":
        android_artifacts = [
            path for platform, path in validated if platform == "android"
        ]
        if len(android_artifacts) != 1:
            raise SystemExit("PDFium lock must contain one accepted Android artifact")
        validate_android_aar(android_artifacts[0])
        return

    if lock.get("status") != "frozen" or len(validated) != 2:
        raise SystemExit("PDFium lock is not frozen with Android and iOS artifacts")
    platforms = {platform for platform, _path in validated}
    if platforms != {"android", "ios"}:
        raise SystemExit("PDFium lock must contain one Android and one iOS artifact")


if __name__ == "__main__":
    main()
