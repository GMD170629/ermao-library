"""Small package fixtures; no Web build in ordinary tests."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import venv
import zipfile
from pathlib import Path
from unittest.mock import patch

import test_container_install
from container_install import InstallError
from dependency_environment import (
    DependencyError,
    business_environment,
    initialize_dependencies,
)
from dependency_packages import node_packages, python_packages
from test_container_entry import entry


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def package(self, location, version):
        path = self.root / "runtime" / location
        path.mkdir(parents=True)
        (path / "package.json").write_text(
            json.dumps({"name": "@scope/same", "version": version})
        )
        (path / "index.js").write_text("module.exports=" + json.dumps(version))
        return path

    def test_instances_nested_scopes_vendored_links_and_node_resolution(self):
        first = self.package("node_modules/@scope/same", "1.0.0")
        self.package("node_modules/@scope/same/node_modules/@scope/same", "2.0.0")
        third = self.package(
            "node_modules/.pnpm/same@3/node_modules/@scope/same", "3.0.0"
        )
        (first / "vendored").mkdir()
        (first / "vendored/library.js").write_text("vendored")
        (self.root / "runtime/node_modules/alias").symlink_to(
            ".pnpm/same@3/node_modules/@scope/same"
        )
        packages, links, scopes = node_packages(
            self.root / "runtime", self.root / "artifacts"
        )
        self.assertEqual(
            sorted(p.version for p in packages), ["1.0.0", "2.0.0", "3.0.0"]
        )
        files = [file for package in packages for file in package.files]
        self.assertEqual(len(files), len(set(files)))
        self.assertIn("node_modules", scopes)
        self.assertEqual(links[0]["target"], ".pnpm/same@3/node_modules/@scope/same")
        parent = next(p for p in packages if p.version == "1.0.0")
        self.assertIn("node_modules/@scope/same/vendored/library.js", parent.files)
        self.assertFalse(
            any(
                "/node_modules/@scope/same/node_modules/" in "/" + f
                for f in parent.files
            )
        )
        for package in packages:
            with tarfile.open(
                self.root / "artifacts" / package.artifact.filename
            ) as archive:
                self.assertEqual(archive.getnames(), list(package.files))
        result = subprocess.check_output(
            [
                "node",
                "-e",
                "console.log(require('@scope/same'),require('./node_modules/@scope/same/node_modules/@scope/same'),require('alias'))",
            ],
            cwd=self.root / "runtime",
            text=True,
        )
        self.assertEqual(result.strip(), "1.0.0 2.0.0 3.0.0")
        before = {p.location: p.content_sha256 for p in packages}
        (third / "index.js").write_text('module.exports="changed"')
        after, _, _ = node_packages(self.root / "runtime", self.root / "artifacts")
        self.assertEqual(sum(before[p.location] != p.content_sha256 for p in after), 1)

    def test_link_escape_and_unowned_files_fail_closed(self):
        self.package("node_modules/demo", "1")
        (self.root / "runtime/node_modules/escape").symlink_to(self.root)
        with self.assertRaisesRegex(ValueError, "unsafe node link"):
            node_packages(self.root / "runtime", self.root / "artifacts")
        (self.root / "runtime/node_modules/escape").unlink()
        (self.root / "runtime/node_modules/orphan.js").write_text("x")
        with self.assertRaisesRegex(ValueError, "unowned"):
            node_packages(self.root / "runtime", self.root / "artifacts")

    def test_wheel_identity_is_artifact_not_installed_tree(self):
        wheels = self.root / "wheels"
        wheels.mkdir()
        wheel = wheels / "Demo_Pkg-1.0-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(
                "Demo_Pkg-1.0.dist-info/METADATA", "Name: Demo_Pkg\nVersion: 1.0\n"
            )
            archive.writestr("Demo_Pkg-1.0.dist-info/RECORD", "demo.py,,\n")
        (package,) = python_packages(wheels)
        self.assertEqual((package.name, package.platform), ("demo-pkg", "py3-none-any"))
        self.assertEqual(package.artifact.size, wheel.stat().st_size)
        self.assertIsNone(package.content_sha256)

    def test_second_start_ignores_absent_seed_and_never_runs_installer(self):
        python = self.root / "dependencies/python/bin"
        python.mkdir(parents=True)
        (python / "python").touch()
        (self.root / "dependencies/installed.json").write_text('{"protocol":2}')
        with patch(
            "dependency_environment.subprocess.run",
            side_effect=AssertionError("installer on restart"),
        ):
            initialize_dependencies(self.root, self.root / "absent")
        (self.root / "dependencies/installed.json").unlink()
        with self.assertRaises(DependencyError):
            initialize_dependencies(self.root, self.root / "absent")

    def test_python_environment_discards_injected_global_paths(self):
        with patch.dict(
            os.environ,
            {"PYTHONPATH": "/global", "PYTHONHOME": "/global", "VIRTUAL_ENV": "/old"},
        ):
            environment = business_environment(self.root)
        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("PYTHONHOME", environment)
        self.assertNotIn("VIRTUAL_ENV", environment)
        self.assertEqual(environment["PYTHONNOUSERSITE"], "1")
        self.assertEqual(
            environment["SHUKU_BUSINESS_PYTHON"],
            str(self.root / "dependencies/python/bin/python"),
        )

    def test_base_identity_ignores_application_and_business_distributions(self):
        spec = importlib.util.spec_from_file_location(
            "base_environment", Path(__file__).with_name("build-runtime-environment.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        before = module.snapshot([])
        self.package("node_modules/demo", "99")
        with patch(
            "importlib.metadata.distributions",
            side_effect=AssertionError("business package scan"),
        ):
            after = module.snapshot([])
        self.assertEqual(before, after)
        self.assertEqual(before["inventory"]["launcher_protocol"], 2)

    def test_installed_record_checks_hashes_and_rejects_escape(self):
        environment = self.root / "business"
        venv.EnvBuilder(with_pip=False).create(environment)
        site = (
            environment
            / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
        )
        distribution = site / "demo-1.0.dist-info"
        distribution.mkdir()
        (distribution / "METADATA").write_text("Name: Demo\nVersion: 1.0\n")
        content = b"original"
        (site / "demo.py").write_bytes(content)
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(content).digest())
            .rstrip(b"=")
            .decode()
        )
        record = distribution / "RECORD"
        record.write_text(
            f"demo.py,sha256={digest},8\ndemo-1.0.dist-info/METADATA,,\ndemo-1.0.dist-info/RECORD,,\n"
        )
        command = [
            str(environment / "bin/python"),
            "-I",
            str(Path(__file__).with_name("dependency_records.py")),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)[0]["name"], "demo")
        (site / "demo.py").write_bytes(b"modified")
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hash mismatch", result.stderr)
        record.write_text("../../../../outside,,\n")
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid installed ownership", result.stderr)


class ProtocolTests(unittest.TestCase):
    setUp = test_container_install.InstallationTests.setUp

    # Reuse installation fixture; test only the new refusal boundaries here.
    def test_new_protocol_cannot_claim_or_copy(self):
        self.installer.state["target"]["format"] = 2
        with self.assertRaisesRegex(InstallError, "UNSUPPORTED_UPDATE_PROTOCOL"):
            self.installer.synchronize()
        self.installer.state["target"]["format"] = 1
        (self.runtime / "application.json").write_text('{"protocol":2}')
        with self.assertRaisesRegex(InstallError, "UNSUPPORTED_UPDATE_PROTOCOL"):
            self.installer.synchronize()
        self.assertTrue((self.runtime / "old").exists())

    def test_conversion_refuses_version_change_before_any_write(self):
        seed = self.storage / "seed"
        seed.mkdir()
        (seed / "application.json").write_text(
            '{"protocol":2,"version":"1.0.4","environment":{"platform":"linux-aarch64"}}'
        )
        (self.runtime / "application.json").write_text(
            '{"version":"1.0.5","environment":{"platform":"linux-aarch64"}}'
        )
        with self.assertRaisesRegex(entry.StartupError, "same release"):
            entry.convert_legacy(
                seed, self.runtime, self.storage, self.storage / "seed-deps"
            )
        self.assertFalse((self.storage / "dependencies").exists())


if __name__ == "__main__":
    unittest.main()
