"""Read and verify installed distribution RECORDs in the business interpreter.

Only called at initialization/preparation, never on ordinary startup or requests.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import json
import re
import sys
from pathlib import Path


def installed_records(prefix: Path | None = None) -> list[dict[str, object]]:
    if prefix is None and sys.prefix == sys.base_prefix:
        raise ValueError("business virtualenv required")
    prefix = (prefix or Path(sys.prefix)).resolve()
    sites = sorted(prefix.glob("lib/python*/site-packages"))
    if len(sites) != 1:
        raise ValueError("invalid business site-packages")
    records = []
    owners: set[str] = set()
    for distribution in importlib.metadata.distributions(path=[str(sites[0])]):
        files = []
        if distribution.files is None:
            raise ValueError("missing installed RECORD")
        for item in distribution.files:
            path = Path(distribution.locate_file(item)).resolve()
            if not path.is_relative_to(prefix) or not path.is_file():
                raise ValueError("invalid installed ownership")
            relative = path.relative_to(prefix).as_posix()
            if relative in owners:
                raise ValueError("overlapping installed ownership")
            owners.add(relative)
            content = path.read_bytes()
            if item.size is not None and len(content) != item.size:
                raise ValueError("installed RECORD size mismatch")
            if item.hash is not None:
                actual = (
                    base64.urlsafe_b64encode(
                        hashlib.new(item.hash.mode, content).digest()
                    )
                    .rstrip(b"=")
                    .decode()
                )
                if actual != item.hash.value:
                    raise ValueError("installed RECORD hash mismatch")
            files.append(
                {
                    "path": relative,
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "record_hash": None
                    if item.hash is None
                    else f"{item.hash.mode}={item.hash.value}",
                }
            )
        records.append(
            {
                "name": re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).lower(),
                "version": distribution.version,
                "files": files,
            }
        )
    for path in sites[0].rglob("*"):
        if path.is_symlink():
            raise ValueError("unexpected installed link")
        if path.is_file() and path.relative_to(prefix).as_posix() not in owners:
            if path.parent.name == "__pycache__" and path.suffix == ".pyc":
                continue
            raise ValueError("unowned installed file")
    return sorted(records, key=lambda item: str(item["name"]))


if __name__ == "__main__":
    print(json.dumps(installed_records(), sort_keys=True))
