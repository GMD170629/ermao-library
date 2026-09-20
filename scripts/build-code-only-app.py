#!/usr/bin/env python3
"""Assemble application code inside an existing immutable runtime; no image build."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

PNPM_INTEGRITY = "InIbOhH4FmGuHsaM4ae4eUJaHKW5kcl1sHSsIgsYfOVscI/l22n0yWLJiUUu7nbIKHf07oD0dM69Ye4TRhtiKA=="


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def main() -> None:
    source, work, program = Path("/source"), Path("/tmp/source"), Path("/tmp/program")
    fixed = json.loads(Path("/opt/shuku-launcher/environment.json").read_text())
    seed = json.loads(Path("/opt/shuku-image/application.json").read_text())
    if (
        seed["version"] != os.environ["SHUKU_SEED_VERSION"]
        or seed["protocol"] != 2
        or seed["environment"] != fixed["environment"]
    ):
        raise ValueError(
            "Runtime seed version/protocol/environment does not match the declared baseline"
        )
    shutil.copytree(source, work, symlinks=True)
    metadata = json.loads((work / "package.json").read_text())
    if metadata["packageManager"] != "pnpm@9.12.2":
        raise ValueError("Unsupported locked pnpm version")
    if (
        subprocess.check_output(["node", "--version"], text=True).strip()
        != "v" + (work / ".nvmrc").read_text().strip()
    ):
        raise ValueError("Source Node version differs from fixed runtime")
    # The runner image has Node but no npm/Corepack. Verify the standalone JS tool.
    archive = Path("/tmp/pnpm.tgz")
    with urllib.request.urlopen(
        "https://registry.npmjs.org/pnpm/-/pnpm-9.12.2.tgz", timeout=60
    ) as response:
        body = response.read(16 * 1024 * 1024 + 1)
    if (
        len(body) > 16 * 1024 * 1024
        or base64.b64encode(hashlib.sha512(body).digest()).decode() != PNPM_INTEGRITY
    ):
        raise ValueError("pnpm distribution integrity mismatch")
    archive.write_bytes(body)
    tools = Path("/tmp/pnpm-tool")
    tools.mkdir()
    with tarfile.open(archive) as bundle:
        bundle.extractall(tools, filter="data")
    bin_dir = tools / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "pnpm"
    shim.write_text('#!/bin/sh\nexec node /tmp/pnpm-tool/package/bin/pnpm.cjs "$@"\n')
    shim.chmod(0o755)
    os.environ["PATH"] = str(bin_dir) + ":" + os.environ["PATH"]
    os.environ["NEXT_TELEMETRY_DISABLED"] = "1"
    os.environ["NEXT_PUBLIC_BASE_PATH"] = fixed["inventory"]["web_base_path"]
    # Install build-time dependencies in this disposable container, never in user storage.
    os.environ.pop("NODE_ENV", None)
    run("pnpm", "install", "--frozen-lockfile", "--filter", "@shuku/web...", cwd=work)
    run("pnpm", "--filter", "@shuku/web", "build", cwd=work)
    shutil.copytree(work / "apps/web/.next/standalone", program, symlinks=True)
    for relative in (
        "apps/web/.next/static",
        "apps/web/public",
        "apps/api-python/app",
        "apps/api-python/shuku_dependencies",
    ):
        target = program / relative
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(work / relative, target, symlinks=True)
    for relative in (
        "apps/api-python/pyproject.toml",
        "apps/api-python/uv.lock",
        "scripts/start-unified-app.sh",
        "scripts/unified-http-gateway.mjs",
        "scripts/install-python-runtime.sh",
    ):
        target = program / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(work / relative, target)
    actual_base = json.loads(
        (program / "apps/web/.next/required-server-files.json").read_text()
    )["config"]["basePath"]
    if actual_base != fixed["inventory"]["web_base_path"]:
        raise ValueError("Web basePath differs from fixed environment")
    (program / "application.json").write_text(
        json.dumps(
            {
                "version": metadata["version"],
                "environment": fixed["environment"],
                "protocol": 2,
            }
        )
        + "\n"
    )
    run(
        "uv",
        "--offline",
        "--no-cache",
        "--no-config",
        "--no-python-downloads",
        "venv",
        "--python",
        "/usr/local/bin/python3.11",
        "/tmp/package-tools",
    )
    run(
        "uv",
        "--offline",
        "--no-cache",
        "--no-config",
        "--no-python-downloads",
        "pip",
        "install",
        "--python",
        "/tmp/package-tools/bin/python",
        "--no-index",
        "--no-deps",
        "--no-build",
        *map(str, sorted(Path("/opt/shuku-dependency-seed/wheels").glob("*.whl"))),
    )
    # Existing packager compares actual Node identities/layout with the untouched seed,
    # verifies every seed blob and extracts the resulting code through the real reader.
    run(
        "/tmp/package-tools/bin/python",
        "/source/scripts/build-application-package.py",
        "--program-root",
        str(program),
        "--output-dir",
        "/packages",
        "--dependency-seed",
        "/opt/shuku-dependency-seed",
        "--fixed-environment",
        "/opt/shuku-launcher/environment.json",
        "--verify",
    )


if __name__ == "__main__":
    main()
