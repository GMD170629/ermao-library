"""Check the approved iOS Readium baseline in local builds and Mobile CI."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VERSION = "3.9.0"
REVISION = "de07026e9f825a5791f27a7ac4cd6bb1a784ab8d"
REPOSITORY = "https://github.com/readium/swift-toolkit.git"
PROJECT = Path("apps/mobile/iosApp/ErmaoLibrary.xcodeproj")
LOCK = PROJECT / "project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
MAPPER = Path(
    "apps/mobile/iosApp/ErmaoLibrary/Features/Reader/ReadiumSwiftLocatorMapper.swift"
)
POLICY = Path("docs/mobile-reader-architecture.md")


def verify(root: Path) -> None:
    project = (root / PROJECT / "project.pbxproj").read_text(encoding="utf-8")
    references = re.findall(
        r"isa = XCRemoteSwiftPackageReference;\s*repositoryURL = \"([^\"]+)\";"
        r"\s*requirement = \{([^}]+)\};",
        project,
    )
    readium = [requirement for url, requirement in references if "swift-toolkit" in url]
    if len(readium) != 1 or (REPOSITORY, readium[0]) not in references:
        raise ValueError("Readium must use exactly one official repository reference")
    requirement = dict(re.findall(r"(\w+)\s*=\s*([^;\s]+)\s*;", readium[0]))
    if requirement != {"kind": "revision", "revision": REVISION}:
        raise ValueError(
            f"Readium must remain pinned to approved {VERSION} ({REVISION})"
        )

    lock = json.loads((root / LOCK).read_text(encoding="utf-8"))
    pins = [pin for pin in lock["pins"] if pin["identity"] == "swift-toolkit"]
    if len(pins) != 1 or pins[0] != {
        "identity": "swift-toolkit",
        "kind": "remoteSourceControl",
        "location": REPOSITORY,
        "state": {"revision": REVISION},
    }:
        raise ValueError("Readium SwiftPM lock does not match the approved revision")

    mapper = (root / MAPPER).read_text(encoding="utf-8")
    if re.findall(r'version: "readium-swift:([^"]+)"', mapper) != [VERSION]:
        raise ValueError("Readium locator diagnostic version is stale")
    policy = (root / POLICY).read_text(encoding="utf-8")
    if (
        f"iOS pins official Readium Swift Toolkit {VERSION} to revision `{REVISION}`"
        not in policy
    ):
        raise ValueError(
            "Reader architecture policy must name the approved iOS baseline"
        )


if __name__ == "__main__":
    verify(ROOT)
    print(f"iOS Readium {VERSION}: official revision, lock, runtime and policy agree")
