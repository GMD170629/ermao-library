"""Image changes versus online-update restarts, without business dependencies."""

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import container_image
from container_image import ImageSynchronization
from container_install import REQUIRED_RUNTIME_FILES, InstallError, write_json
from dependency_packages import canonical_digest
from test_container_entry import entry


class ImageSynchronizationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.storage = root / "storage"
        self.seed = root / "image"
        self.dependencies = root / "seed"
        self.state = self.storage / "update-tmp"
        self.state.mkdir(parents=True)
        self.dependencies.mkdir()
        (self.dependencies / "requirements.txt").write_text("")
        self.target = {
            "version": "1.2.0",
            "protocol": 2,
            "environment": {
                "format": 1,
                "platform": "linux-amd64",
                "compatibility": "fixture",
            },
        }
        for name in REQUIRED_RUNTIME_FILES:
            path = self.seed / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("new code")
        write_json(self.seed / "application.json", self.target)
        manifest = {"protocol": 2, "packages": [], "node_links": [], "node_scopes": []}
        write_json(
            self.dependencies / "manifest.json",
            {**manifest, "identity": canonical_digest(manifest)},
        )
        self.runtime = self.storage / "runtime"
        entry.initialize_runtime(self.seed, self.runtime)
        write_json(
            self.runtime / "application.json", {**self.target, "version": "1.1.0"}
        )
        (self.runtime / "obsolete").write_text("old code")
        (self.storage / "dependencies").mkdir()
        (self.storage / "dependencies/obsolete").write_text("old dependency")
        (self.storage / "database").mkdir()
        with sqlite3.connect(self.storage / "database/shuku.sqlite3") as db:
            db.execute("CREATE TABLE preserved(value TEXT)")
            db.execute("INSERT INTO preserved VALUES ('reading progress')")
        (self.storage / "configuration").write_text("keep")
        self.installer = ImageSynchronization(
            self.storage, self.seed, self.dependencies
        )
        self.addCleanup(self.installer.close)

    def install_dependencies(self, storage, seed):
        self.assertEqual(seed, self.dependencies)
        path = storage / "dependencies"
        self.assertFalse(path.exists())
        (path / "python/bin").mkdir(parents=True)
        (path / "python/bin/python").write_text("new interpreter")
        write_json(path / "installed.json", {"protocol": 2})
        return True

    def prepare(self):
        with patch.object(
            container_image,
            "initialize_dependencies",
            side_effect=self.install_dependencies,
        ):
            return self.installer.prepare()

    def test_image_switch_replaces_code_dependencies_and_preserves_data(self):
        from container_install import retire_previous_installation

        marker_stat = (self.runtime / ".initialized").stat()
        write_json(self.state / "image.json", {**self.target, "version": "1.0.0"})
        write_json(self.state / "preparation.json", {"phase": "ready"})
        (self.state / "prepared").mkdir()
        (self.state / "installation-incomplete").write_text("previous failure")
        (self.state / "install-request.json").write_text("previous request")
        retire_previous_installation(self.storage)
        self.assertTrue(self.prepare())
        self.assertFalse((self.runtime / "obsolete").exists())
        self.assertEqual((self.runtime / ".initialized").stat(), marker_stat)
        self.assertFalse((self.storage / "dependencies/obsolete").exists())
        self.assertEqual(
            json.loads((self.runtime / "application.json").read_text()), self.target
        )
        self.assertEqual((self.storage / "configuration").read_text(), "keep")
        self.assertTrue((self.state / "installation-incomplete").exists())
        self.assertTrue((self.state / "preparation.json").exists())
        self.assertEqual(
            json.loads((self.state / "image.json").read_text())["version"], "1.0.0"
        )
        self.assertFalse(list(self.state.glob("database-before-*.sqlite3")))
        with sqlite3.connect(self.storage / "database/shuku.sqlite3") as db:
            self.assertEqual(
                db.execute("SELECT value FROM preserved").fetchone()[0],
                "reading progress",
            )
        self.installer.success()
        self.assertEqual(
            (self.state / "install-request.json.previous").read_text(),
            "previous request",
        )
        self.assertFalse((self.state / "installation-incomplete").exists())
        self.assertFalse((self.state / "preparation.json").exists())
        self.assertFalse((self.state / "prepared").exists())
        self.assertEqual(
            json.loads((self.state / "image.json").read_text()), self.target
        )

    def test_locked_database_does_not_block_image_switch(self):
        with sqlite3.connect(self.storage / "database/shuku.sqlite3") as locked:
            locked.execute("BEGIN EXCLUSIVE")
            with patch.object(
                sqlite3,
                "connect",
                side_effect=AssertionError("updater opened database"),
            ):
                self.assertTrue(self.prepare())
        self.assertFalse(list(self.state.glob("database-before-*.sqlite3")))
        self.assertFalse((self.runtime / "obsolete").exists())

    def test_database_layout_is_left_to_application_startup(self):
        database = self.storage / "database/shuku.sqlite3"
        database.unlink()
        database.symlink_to(self.storage / "missing-database")
        self.assertTrue(self.prepare())
        self.assertTrue(database.is_symlink())

    def test_same_image_preserves_newer_online_version_without_reading_dependencies(
        self,
    ):
        write_json(self.state / "image.json", self.target)
        write_json(
            self.runtime / "application.json", {**self.target, "version": "9.0.0"}
        )
        shutil.rmtree(self.dependencies)
        self.assertFalse(self.prepare())
        self.assertEqual(
            json.loads((self.runtime / "application.json").read_text())["version"],
            "9.0.0",
        )
        self.assertTrue((self.runtime / "obsolete").exists())

    def test_no_record_accepts_legacy_and_aligns_even_newer_runtime(self):
        write_json(
            self.runtime / "application.json",
            {**self.target, "version": "9.0.0", "protocol": 1},
        )
        shutil.rmtree(self.storage / "dependencies")
        self.assertTrue(self.prepare())
        self.assertEqual(
            json.loads((self.runtime / "application.json").read_text()), self.target
        )

    def test_same_version_changed_environment_synchronizes(self):
        write_json(
            self.state / "image.json",
            {
                **self.target,
                "environment": {
                    **self.target["environment"],
                    "compatibility": "previous",
                },
            },
        )
        self.assertTrue(self.prepare())

    def test_fresh_install_has_no_database_backup(self):
        for name in ("runtime", "dependencies", "database"):
            shutil.rmtree(self.storage / name)
        self.assertTrue(self.prepare())
        self.assertFalse((self.state / "database-before-image.sqlite3").exists())
        self.assertFalse((self.state / "image.json").exists())
        self.assertTrue((self.runtime / ".initialized").exists())

    def test_preflight_errors_leave_old_program_untouched(self):
        with (
            patch.object(
                container_image,
                "validate_dependency_seed",
                side_effect=ValueError("bad seed"),
            ),
            self.assertRaises(ValueError),
        ):
            self.prepare()
        self.assertTrue((self.runtime / "obsolete").exists())
        self.assertFalse((self.state / "installation-incomplete").exists())

    def test_interruption_or_copy_failure_keeps_blocker_and_old_record(self):
        for failure in (OSError("copy failed"), SystemExit(143)):
            with self.subTest(failure=failure):
                with (
                    patch.object(
                        container_image, "replace_runtime", side_effect=failure
                    ),
                    self.assertRaises(type(failure)),
                ):
                    self.prepare()
                self.installer.close()
                self.assertTrue((self.state / "installation-incomplete").exists())
                self.assertFalse((self.state / "image.json").exists())
                (self.state / "installation-incomplete").unlink()

    def test_links_cannot_redirect_replacement(self):
        outside = self.storage.parent / "outside"
        outside.mkdir()
        (outside / "keep").write_text("safe")
        (self.runtime / "escape").symlink_to(outside)
        self.assertTrue(self.prepare())
        self.assertEqual((outside / "keep").read_text(), "safe")
        self.installer.close()
        (self.seed / "escape").symlink_to(outside)
        with self.assertRaisesRegex(InstallError, "UNSAFE_IMAGE_SOURCE"):
            self.installer.preflight()

    def test_root_link_and_incomplete_layout_rejected(self):
        (self.runtime / ".initialized").unlink()
        self.installer.preflight()
        shutil.rmtree(self.runtime)
        self.runtime.symlink_to(self.seed)
        with self.assertRaisesRegex(InstallError, "UNSAFE_STORAGE"):
            self.installer.preflight()

    def test_preparation_mutex_blocks_switch(self):
        import fcntl

        with (self.state / "prepare.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.prepare()
        self.assertTrue((self.runtime / "obsolete").exists())

    def test_dependency_failure_blocks_subsequent_start(self):
        with (
            patch.object(
                container_image,
                "initialize_dependencies",
                side_effect=OSError("injected"),
            ),
            self.assertRaises(OSError),
        ):
            self.installer.prepare()
        with (
            patch.object(entry.sys, "argv", ["container-entry.py"]),
            patch.dict(
                entry.os.environ,
                {"STORAGE_ROOT": str(self.storage), "SHUKU_IMAGE_ROOT": str(self.seed)},
            ),
            patch.object(entry.signal, "signal"),
            patch.object(entry, "run_application") as launch,
        ):
            self.assertEqual(entry.main(), 1)
        launch.assert_not_called()
        self.assertTrue((self.state / "installation-incomplete").exists())
        self.assertFalse((self.state / "image.json").exists())

    def test_corrupt_image_record_and_incomplete_runtime_are_replaced(self):
        (self.state / "image.json").write_text("broken")
        (self.runtime / ".initialized").unlink()
        (self.runtime / "application.json").write_text("broken")
        (self.runtime / REQUIRED_RUNTIME_FILES[0]).unlink()
        self.assertTrue(self.prepare())
        self.installer.success()
        self.assertEqual(
            json.loads((self.state / "image.json").read_text()), self.target
        )

    def test_cleanup_and_image_record_errors_do_not_block_completed_sync(self):
        self.assertTrue(self.prepare())
        original = container_image.write_json

        def fail_image(path, value):
            if path.name == "image.json":
                raise PermissionError("injected")
            return original(path, value)

        with (
            patch.object(Path, "unlink", side_effect=PermissionError("injected")),
            patch.object(container_image, "write_json", side_effect=fail_image),
        ):
            self.installer.success()
        self.assertIsNone(self.installer.lock)
        self.assertEqual(
            json.loads((self.runtime / "application.json").read_text()), self.target
        )

    def test_estimated_space_and_permissions_are_not_gates(self):
        with (
            patch.object(container_image.os, "access", return_value=False),
            patch.object(
                container_image.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=0),
            ),
        ):
            self.assertTrue(self.prepare())


if __name__ == "__main__":
    unittest.main()
