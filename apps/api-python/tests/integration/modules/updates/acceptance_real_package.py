"""Explicit real-artifact acceptance; excluded by pytest's default filename pattern.

Run: python -m pytest tests/integration/modules/updates/acceptance_real_package.py -q
Missing build prerequisites are errors, never skips.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.integration.modules.updates import test_preparation as shared
from tests.integration.modules.updates.test_preparation import (
    ROOT,
    assert_package_prepared,
    load_script,
)

source = shared.source
preparation = shared.preparation


@pytest.fixture(scope="module")
def program_package(tmp_path_factory):
    directory = tmp_path_factory.mktemp("actual-update-package")
    root = directory / "image"
    standalone = ROOT / "apps/web/.next/standalone"
    assert (standalone / "apps/web/server.js").is_file(), (
        "Run pnpm --filter @shuku/web build first"
    )
    shutil.copytree(standalone, root, symlinks=True)
    for source, destination in (
        ("apps/web/.next/static", "apps/web/.next/static"),
        ("apps/web/public", "apps/web/public"),
        ("apps/api-python/app", "apps/api-python/app"),
    ):
        shutil.copytree(ROOT / source, root / destination, dirs_exist_ok=True)
    (root / "scripts").mkdir(exist_ok=True)
    for name in (
        "scripts/start-unified-app.sh",
        "scripts/unified-http-gateway.mjs",
        "apps/api-python/pyproject.toml",
        "apps/api-python/uv.lock",
    ):
        shutil.copy2(ROOT / name, root / name)
    # Actual build-time environment capture, using this isolated host's runtime.
    command = [
        sys.executable,
        str(ROOT / "scripts/build-runtime-environment.py"),
        "--output",
        str(directory / "environment.json"),
        "--program-root",
        str(root),
    ]
    if sys.platform == "linux":
        import os

        command.extend(
            [
                "--native",
                os.environ.get(
                    "ERMAO_MOBI_CORE_LIBRARY", "/usr/local/lib/libermao_mobi_core.so"
                ),
                "--native",
                os.environ.get(
                    "ERMAO_CHAPTER_CORE_LIBRARY", "/usr/local/lib/libermao_chapters.so"
                ),
            ]
        )
    if sys.platform == "linux":
        for index, argument in enumerate(command):
            if argument == "--native":
                assert Path(command[index + 1]).is_file(), (
                    "Real Linux acceptance requires both built native libraries; "
                    "set ERMAO_MOBI_CORE_LIBRARY and ERMAO_CHAPTER_CORE_LIBRARY "
                    "to libermao_mobi_core.so and libermao_chapters.so"
                )
    subprocess.run(command, check=True)
    # Sentinels prove these never enter an application package.
    for name in (
        "storage/database/book.db",
        "apps/api-python/app/.env",
        "apps/web/.next/cache/private",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("must not ship")
    package = load_script("build-application-package").build_package(
        root, directory / "output"
    )
    return root, package, (directory / "output" / package.filename).read_bytes()


def test_real_build_download_verification_extraction_and_persistence(
    program_package, preparation, source
):
    assert_package_prepared(program_package, preparation, source)
