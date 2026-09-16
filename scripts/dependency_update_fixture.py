"""Small dependency fixtures for explicit D3 acceptance only; never shipped."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import zipfile
from pathlib import Path


def wheel(root: Path, name: str, version: str, files: dict[str, bytes]) -> Path:
    directory = f"{name}-{version}.dist-info"
    files = {
        **files,
        f"{directory}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n".encode(),
        f"{directory}/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = "".join(
        f"{n},sha256={base64.urlsafe_b64encode(hashlib.sha256(b).digest()).rstrip(b'=').decode()},{len(b)}\n"
        for n, b in files.items()
    )
    files[f"{directory}/RECORD"] = (record + f"{directory}/RECORD,,\n").encode()
    root.mkdir(parents=True, exist_ok=True)
    result = root / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(result, "w") as archive:
        for n, b in files.items():
            archive.writestr(n, b)
    return result


def seed_initial() -> None:
    sys.path.insert(0, "/opt/shuku-launcher")
    from shuku_dependencies import generate

    seed = Path("/opt/shuku-dependency-seed")
    for name in ("a", "b", "c", "d"):
        files = {f"d3_namespace/{name}.py": b"VALUE = 1\n"}
        if name == "b":
            files["d3_namespace/obsolete.py"] = b"old"
        artifact = wheel(seed / "wheels", "d3_" + name, "1", files)
        with (seed / "requirements.txt").open("a") as output:
            output.write(
                f"\nd3-{name}==1 --hash=sha256:{hashlib.sha256(artifact.read_bytes()).hexdigest()}\n"
            )
    (seed / "manifest.json").write_text(
        json.dumps(generate(Path("/opt/shuku-image"), seed))
    )


def target_dependencies(root: Path, seed: Path) -> None:
    from shuku_dependencies import generate

    for name in ("b", "c"):
        (seed / f"wheels/d3_{name}-1-py3-none-any.whl").unlink()
    wheel(seed / "wheels", "d3_b", "2", {"d3_namespace/b.py": b"VALUE = 2\n"})
    wheel(seed / "wheels", "d3_e", "1", {"d3_namespace/e.py": b"VALUE = 1\n"})
    manifest = json.loads((seed / "manifest.json").read_text())
    chosen = next(
        p
        for p in manifest["packages"]
        if p["ecosystem"] == "node" and p["name"] == "client-only"
    )
    with (root / chosen["location"] / "index.js").open("a") as output:
        output.write("\n// D3 isolated same-version replacement\n")
    (seed / "manifest.json").write_text(json.dumps(generate(root, seed)))


if __name__ == "__main__":
    seed_initial()
