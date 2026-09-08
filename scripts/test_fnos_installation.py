"""Exercise the packaged fnOS lifecycle in isolated directories without a NAS."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

TEMPLATE = Path(
    os.environ.get(
        "FNOS_TEMPLATE_DIR", Path(__file__).resolve().parents[1] / "deploy" / "fnos"
    )
).resolve()


class FnosInstallationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="fnos-install-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package_var = self.root / "var"
        self.storage = self.package_var / "storage"
        self.library = self.root / "library"
        self.etc = self.root / "etc"
        self.bin = self.root / "bin"
        for directory in (self.storage, self.library, self.etc, self.bin):
            directory.mkdir(parents=True)
        self.database = self.storage / "database" / "library.db"
        self.database.parent.mkdir()
        self.database.write_bytes(b"existing database")
        (self.storage / ".settings").write_bytes(b"hidden settings")
        (self.library / "book.epub").write_bytes(b"original publication")
        (self.etc / "config").write_bytes(b"fnOS configuration")
        self.log = self.root / "error.log"
        self.docker_calls = self.root / "docker.calls"
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("TRIM_", "wizard_"))
        }
        self.environment.update(
            PATH=f"{self.bin}:{os.environ['PATH']}",
            TRIM_APPDEST=str(TEMPLATE / "app"),
            TRIM_PKGVAR=str(self.package_var),
            TRIM_PKGETC=str(self.etc),
            TRIM_DATA_SHARE_PATHS=str(self.library),
            TRIM_OLD_APPVER="1.0.0",
            TRIM_APPVER="1.0.1",
            TRIM_SYS_LANGUAGE="en-US",
            TRIM_TEMP_LOGFILE=str(self.log),
            wizard_install_mode="update",
            wizard_port="3000",
            TEST_DOCKER_CALLS=str(self.docker_calls),
            TEST_CONTAINER_STATES="exited",
            TEST_DOCKER_EXIT="0",
        )
        self.write_executable(
            "docker",
            """#!/bin/bash
set -eu
printf '%s\\n' "$*" >> "$TEST_DOCKER_CALLS"
if [ "$*" != "ps --all --filter label=com.docker.compose.project=ermao-books --filter label=com.docker.compose.service=web --format {{.State}}" ]; then
  exit 99
fi
printf '%s\\n' "$TEST_CONTAINER_STATES"
exit "$TEST_DOCKER_EXIT"
""",
        )

    def write_executable(self, name: str, source: str) -> None:
        executable = self.bin / name
        executable.write_text(source, encoding="utf-8")
        executable.chmod(0o755)

    def invoke(self, script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(TEMPLATE / "cmd" / script), *arguments],
            env=self.environment,
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def assert_originals_preserved(self) -> None:
        self.assertEqual(
            (self.library / "book.epub").read_bytes(), b"original publication"
        )
        self.assertEqual((self.etc / "config").read_bytes(), b"fnOS configuration")

    def assert_storage_preserved(self) -> None:
        self.assertEqual(self.database.read_bytes(), b"existing database")
        self.assertEqual((self.storage / ".settings").read_bytes(), b"hidden settings")
        self.assert_originals_preserved()

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_legacy_update_is_rejected_in_both_entrypoints_and_callbacks(self) -> None:
        self.environment.update(TRIM_OLD_APPVER="0.9.0", TRIM_APPVER="1.0.0")
        for script in (
            "install_init",
            "upgrade_init",
            "install_callback",
            "upgrade_callback",
        ):
            for locale, message in (
                ("zh-CN", "当前版本无法自动升级到 v1"),
                ("en-US", "cannot be upgraded automatically to v1"),
            ):
                with self.subTest(script=script, locale=locale):
                    self.environment["TRIM_SYS_LANGUAGE"] = locale
                    self.assertEqual(self.invoke(script).returncode, 1)
                    self.assertIn(message, self.log.read_text(encoding="utf-8"))
                    self.assert_storage_preserved()
                    self.assertFalse(self.docker_calls.exists())

    def test_fresh_preflight_does_not_require_installed_files_or_erase_storage(
        self,
    ) -> None:
        self.environment.update(
            TRIM_APPDEST=str(self.root / "not-installed"),
            TRIM_OLD_APPVER="0.9.0",
            TRIM_APPVER="1.0.0",
            wizard_install_mode="fresh",
        )
        for script in ("install_init", "upgrade_init"):
            self.assert_success(self.invoke(script))
            self.assert_storage_preserved()
        self.assertFalse(self.docker_calls.exists())

    def test_update_preserves_storage_without_querying_docker(self) -> None:
        self.environment["TEST_DOCKER_EXIT"] = "1"
        for script in (
            "install_init",
            "upgrade_init",
            "install_callback",
            "upgrade_callback",
        ):
            self.assert_success(self.invoke(script))
            self.assert_storage_preserved()
        self.assertFalse(self.docker_calls.exists())

    def test_fresh_callbacks_reset_contents_and_preserve_library_symlink_targets(
        self,
    ) -> None:
        self.environment.update(
            TRIM_OLD_APPVER="0.9.0", TRIM_APPVER="1.0.0", wizard_install_mode="fresh"
        )
        storage_inode = self.storage.stat().st_ino
        for script in ("install_callback", "upgrade_callback"):
            with self.subTest(script=script):
                self.database.write_bytes(b"existing database")
                (self.storage / ".settings").write_text("hidden settings")
                nested = self.storage / "old" / ".nested"
                nested.mkdir(parents=True)
                (nested / "library-link").symlink_to(
                    self.library, target_is_directory=True
                )
                (nested / "etc-link").symlink_to(self.etc, target_is_directory=True)
                self.assert_success(self.invoke(script))
                self.assertFalse(self.database.exists())
                self.assertFalse((self.storage / ".settings").exists())
                self.assertFalse((self.storage / "old").exists())
                self.assertEqual(self.storage.stat().st_ino, storage_inode)
                for name in ("database", "covers", "indexes", "logs", "secrets"):
                    self.assertTrue((self.storage / name).is_dir(), name)
                self.assert_originals_preserved()

    def test_v1_fresh_install_also_resets_storage(self) -> None:
        self.environment["wizard_install_mode"] = "fresh"
        self.assert_success(self.invoke("upgrade_callback"))
        self.assertFalse(self.database.exists())
        self.assert_originals_preserved()

    def test_first_fresh_install_prepares_empty_storage(self) -> None:
        self.environment.pop("TRIM_OLD_APPVER")
        self.environment.update(
            wizard_install_mode="fresh",
            TRIM_PKGVAR=str(self.root / "first-install"),
            TEST_CONTAINER_STATES="",
        )
        Path(self.environment["TRIM_PKGVAR"]).mkdir()
        self.assert_success(self.invoke("install_init"))
        self.assert_success(self.invoke("install_callback"))
        self.assertTrue((self.root / "first-install/storage/database").is_dir())
        self.assert_originals_preserved()

    def test_active_or_unqueryable_containers_prevent_erasure(self) -> None:
        self.environment["wizard_install_mode"] = "fresh"
        for states, exit_code in (
            ("running", "0"),
            ("restarting", "0"),
            ("paused", "0"),
            ("exited\nrunning", "0"),
            ("", "1"),
        ):
            for script in ("install_callback", "upgrade_callback"):
                with self.subTest(states=states, exit_code=exit_code, script=script):
                    self.environment.update(
                        TEST_CONTAINER_STATES=states, TEST_DOCKER_EXIT=exit_code
                    )
                    self.assertEqual(self.invoke(script).returncode, 1)
                    self.assertIn("without erasing settings", self.log.read_text())
                    self.assert_storage_preserved()

    def test_invalid_mode_and_port_cannot_erase_storage(self) -> None:
        for mode, port in (("invalid", "3000"), ("", "3000"), ("fresh", "80")):
            self.environment.update(wizard_install_mode=mode, wizard_port=port)
            for script in ("install_callback", "upgrade_callback"):
                with self.subTest(mode=mode, port=port, script=script):
                    self.assertEqual(self.invoke(script).returncode, 1)
                    self.assert_storage_preserved()
        self.assertFalse(self.docker_calls.exists())

    def test_unsafe_data_roots_cannot_erase_storage(self) -> None:
        self.environment["wizard_install_mode"] = "fresh"
        for root in ("", "/", "relative", str(self.root / "missing")):
            with self.subTest(root=root):
                self.environment["TRIM_PKGVAR"] = root
                self.assertEqual(self.invoke("install_callback").returncode, 1)
                self.assertIn("data directory is invalid", self.log.read_text())
                self.assert_storage_preserved()

    def test_storage_symlink_is_rejected_but_fnos_var_symlink_is_supported(
        self,
    ) -> None:
        self.environment["wizard_install_mode"] = "fresh"
        linked_var = self.root / "linked-var"
        linked_var.symlink_to(self.package_var, target_is_directory=True)
        self.environment["TRIM_PKGVAR"] = str(linked_var)
        self.assert_success(self.invoke("install_callback"))
        alternate_var = self.root / "alternate-var"
        alternate_var.mkdir()
        (alternate_var / "storage").symlink_to(self.library, target_is_directory=True)
        self.environment["TRIM_PKGVAR"] = str(alternate_var)
        self.assertEqual(self.invoke("install_callback").returncode, 1)
        self.assert_originals_preserved()

    def test_removal_failure_stops_before_preparing_directories(self) -> None:
        self.environment["wizard_install_mode"] = "fresh"
        self.write_executable("find", "#!/bin/bash\nexit 1\n")
        self.assertEqual(self.invoke("install_callback").returncode, 1)
        self.assertIn("Could not erase", self.log.read_text())
        self.assertFalse((self.storage / "covers").exists())
        self.assert_storage_preserved()

    def test_settings_and_restarts_never_apply_saved_fresh_choice(self) -> None:
        self.environment.update(wizard_install_mode="fresh", TRIM_OLD_APPVER="0.9.0")
        for script, arguments in (
            ("config_init", ()),
            ("config_callback", ()),
            ("main", ("stop",)),
            ("main", ("start",)),
            ("main", ("stop",)),
            ("main", ("start",)),
        ):
            self.assert_success(self.invoke(script, *arguments))
            self.assert_storage_preserved()
        self.assertFalse(self.docker_calls.exists())

    def test_status_uses_shared_discovery_and_distinguishes_query_failure(self) -> None:
        for states, docker_exit, expected in (
            ("running", "0", 0),
            ("exited\nrunning", "0", 0),
            ("exited", "0", 3),
            ("", "0", 3),
            ("", "1", 1),
        ):
            with self.subTest(states=states, docker_exit=docker_exit):
                self.environment.update(
                    TEST_CONTAINER_STATES=states, TEST_DOCKER_EXIT=docker_exit
                )
                self.assertEqual(self.invoke("main", "status").returncode, expected)
                self.assert_storage_preserved()


if __name__ == "__main__":
    unittest.main()
