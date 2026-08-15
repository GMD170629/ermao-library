from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "pdfium.lock.json"
EXPECTED_REVISION = "875172eae557a308d0c5b2be43822814c8a885bb"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if lock.get("pdfiumCommit") != EXPECTED_REVISION:
        raise SystemExit("PDFium lock revision changed")
    artifacts = lock.get("artifacts")
    if lock.get("status") != "frozen" or not isinstance(artifacts, list) or len(artifacts) != 2:
        raise SystemExit("PDFium lock is not frozen with Android and iOS artifacts")
    platforms = set()
    for artifact in artifacts:
        path = ROOT / artifact["path"]
        if not path.is_file():
            raise SystemExit(f"Missing PDFium artifact: {path}")
        if artifact.get("sha256") != sha256(path):
            raise SystemExit(f"PDFium artifact hash mismatch: {path}")
        if artifact.get("sizeBytes") != path.stat().st_size:
            raise SystemExit(f"PDFium artifact size mismatch: {path}")
        license_path = ROOT / artifact["licensePath"]
        if not license_path.is_file():
            raise SystemExit(f"Missing PDFium license bundle: {license_path}")
        platforms.add(artifact.get("platform"))
    if platforms != {"android", "ios"}:
        raise SystemExit("PDFium lock must contain one Android and one iOS artifact")


if __name__ == "__main__":
    main()
