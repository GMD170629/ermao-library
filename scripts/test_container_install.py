"""Isolated installation behavior; real Docker acceptance is separate."""

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from container_install import Installation, InstallError


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.storage = Path(self.tmp.name).resolve()
        self.runtime = self.storage / "runtime"
        self.runtime.mkdir()
        (self.runtime / ".initialized").write_text("1\n")
        (self.runtime / "old").write_text("remove")
        self.installer = Installation(self.storage)
        self.installer.root.mkdir()
        self.source = self.installer.root / "prepared/app"
        self.source.mkdir(parents=True)
        (self.source / "new").write_text("B")
        (self.source / "link").symlink_to("new")
        self.installer.state = {"phase": "requested", "target": {"version": "1.0.5"}}
        (self.installer.root / "preparation.json").write_text(
            json.dumps(self.installer.state)
        )
        (self.installer.root / "install-request.json").write_text(
            json.dumps({"target": {"version": "1.0.5"}})
        )
        self.addCleanup(self.installer.close)
        (self.storage / "database").mkdir()
        with sqlite3.connect(self.storage / "database/shuku.sqlite3") as db:
            db.execute("create table records(value text)")
            db.execute("insert into records values ('reading-progress')")
        (self.storage / "secret").write_text("keep")

    def test_claim_ignores_extension_metadata_but_binds_digest(self):
        target = {"version": "1.0.5", "sha256": "a" * 64}
        (self.installer.root / "preparation.json").write_text(
            json.dumps({"phase": "requested", "target": target})
        )
        request = self.installer.root / "install-request.json"
        request.write_text(
            json.dumps({"target": {**target, "future_field": True, "size": 1}})
        )
        self.assertTrue(self.installer.claim())

    def test_claim_rejects_changed_digest(self):
        (self.installer.root / "preparation.json").write_text(
            json.dumps(
                {
                    "phase": "requested",
                    "target": {"version": "1.0.5", "sha256": "a" * 64},
                }
            )
        )
        (self.installer.root / "install-request.json").write_text(
            json.dumps({"target": {"version": "1.0.5", "sha256": "b" * 64}})
        )
        with self.assertRaisesRegex(InstallError, "INVALID_INSTALL_REQUEST"):
            self.installer.claim()

    def test_claim_mutex_and_snapshot_sync(self):
        import fcntl

        (self.installer.root / "installation.log").write_text("previous update log")
        self.assertTrue(self.installer.claim())
        self.assertNotIn(
            "previous update", (self.installer.root / "installation.log").read_text()
        )
        with (
            (self.installer.root / "prepare.lock").open("w") as lock,
            self.assertRaises(BlockingIOError),
        ):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.installer.backup()
        self.installer.synchronize()
        self.assertFalse((self.runtime / "old").exists())
        self.assertEqual((self.runtime / ".initialized").read_text(), "1\n")
        self.assertEqual((self.runtime / "link").read_text(), "B")
        self.assertEqual((self.storage / "secret").read_text(), "keep")
        with sqlite3.connect(
            self.installer.root / "database-before-update.sqlite3"
        ) as db:
            self.assertEqual(
                db.execute("select value from records").fetchone()[0],
                "reading-progress",
            )
        self.installer.success()
        self.assertFalse((self.installer.root / "installation-incomplete").exists())

    def test_copy_failure_preserves_marker(self):
        with (
            patch.object(shutil, "copytree", side_effect=OSError("fixture failure")),
            self.assertRaises(OSError),
        ):
            self.installer.synchronize()
        self.installer.fail("COPY_FAILED")
        self.assertTrue((self.installer.root / "installation-incomplete").is_file())
        self.assertEqual(
            json.loads((self.installer.root / "preparation.json").read_text())["phase"],
            "failed",
        )

    def test_destination_links_never_escape(self):
        outside = self.storage / "outside"
        outside.mkdir()
        (outside / "keep").write_text("safe")
        (self.runtime / "escape").symlink_to(outside, target_is_directory=True)
        self.installer.synchronize()
        self.assertEqual((outside / "keep").read_text(), "safe")

    def test_runtime_link_rejected(self):
        shutil.rmtree(self.runtime)
        self.runtime.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(InstallError):
            self.installer.synchronize()

    def test_backup_failure_does_not_copy(self):
        (self.storage / "database/shuku.sqlite3").unlink()
        with self.assertRaises(sqlite3.OperationalError):
            self.installer.backup()
        self.assertEqual((self.runtime / "old").read_text(), "remove")
        self.assertFalse((self.installer.root / "installation-incomplete").exists())

    def run_entry(self, outcome):
        import signal
        from contextlib import ExitStack
        from types import SimpleNamespace

        from test_container_entry import entry

        clock = [0]
        processes = []
        helpers = []
        handlers = {}
        events = []
        exiting = set()
        reaped = set()

        def launch(*args, **kwargs):
            if "app.bootstrap.update_install" in args[0]:
                helper = SimpleNamespace(
                    pid=200, returncode=None if outcome == "cancel-preflight" else 0
                )
                helpers.append(helper)
                return helper
            process = SimpleNamespace(pid=100 + len(processes), returncode=None)
            processes.append(process)
            events.append("launch")
            if len(processes) == 2 and outcome == "migration":
                (self.installer.root / "startup-stage").write_text("migration")
                exiting.add(process.pid)
            return process

        def kill(pid, signum):
            events.append(("signal", pid, signum))
            if outcome != "timeout" or signum != signal.SIGUSR1:
                exiting.add(pid)

        def waitpid(*args):
            process = processes[-1]
            state = json.loads((self.installer.root / "preparation.json").read_text())
            if state["phase"] == "checking" and outcome == "cancel-preflight":
                handlers[signal.SIGTERM](signal.SIGTERM, None)
            if helpers and helpers[0].pid in exiting and helpers[0].pid not in reaped:
                reaped.add(helpers[0].pid)
                return helpers[0].pid, 0
            if state["phase"] == "success":
                handlers[signal.SIGTERM](signal.SIGTERM, None)
            if state["phase"] == "failed":
                exiting.add(process.pid)
            if process.pid in reaped:
                if outcome == "tool-timeout" and state["phase"] != "failed":
                    return 0, 0
                raise ChildProcessError
            if process.pid in exiting:
                reaped.add(process.pid)
                return process.pid, (
                    37 << 8 if outcome == "migration" and len(processes) == 2 else 0
                )
            return 0, 0

        def sleep(seconds):
            clock[0] += 50
            if clock[0] > 1000:
                self.fail("entry loop did not finish")

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    entry.signal,
                    "signal",
                    side_effect=lambda sig, fn: handlers.update({sig: fn}),
                )
            )
            stack.enter_context(patch.object(entry.sys, "platform", "darwin"))
            stack.enter_context(
                patch.object(entry.subprocess, "Popen", side_effect=launch)
            )
            stack.enter_context(
                patch.object(
                    entry.subprocess, "run", return_value=SimpleNamespace(returncode=0)
                )
            )
            stack.enter_context(patch.object(entry.os, "waitpid", side_effect=waitpid))
            stack.enter_context(patch.object(entry.os, "kill", side_effect=kill))
            stack.enter_context(
                patch.object(
                    entry.os,
                    "killpg",
                    side_effect=lambda *a: self.fail(
                        "must not kill tools during installation"
                    ),
                )
            )
            stack.enter_context(
                patch.object(entry.time, "monotonic", side_effect=lambda: clock[0])
            )
            stack.enter_context(patch.object(entry.time, "sleep", side_effect=sleep))
            stack.enter_context(
                patch.object(
                    entry, "application_ready", return_value=outcome == "success"
                )
            )
            stack.enter_context(
                patch.object(
                    entry, "core_application_ready", return_value=outcome == "worker"
                )
            )
            if outcome == "copy":
                stack.enter_context(
                    patch.object(shutil, "copytree", side_effect=OSError("copy failed"))
                )
            result = entry.run_application(self.runtime, self.storage)
        return (
            result,
            processes,
            events,
            json.loads((self.installer.root / "preparation.json").read_text()),
        )

    def test_entry_stops_before_copy_and_restarts(self):
        _result, processes, events, state = self.run_entry("success")
        self.assertEqual(len(processes), 2)
        self.assertEqual(state["phase"], "success")
        self.assertLess(
            events.index(("signal", 100, __import__("signal").SIGUSR1)), len(events) - 1
        )
        self.assertEqual((self.runtime / "new").read_text(), "B")

    def test_entry_stop_timeout_never_copies_or_restarts(self):
        _, processes, _, state = self.run_entry("timeout")
        self.assertEqual(len(processes), 1)
        self.assertEqual(state["error"], "STOP_TIMEOUT")
        self.assertTrue((self.runtime / "old").exists())
        self.assertFalse((self.installer.root / "installation-incomplete").exists())

    def test_entry_copy_failure_never_launches_new_code(self):
        _, processes, _, state = self.run_entry("copy")
        self.assertEqual(len(processes), 1)
        self.assertEqual(state["phase"], "failed")
        self.assertTrue((self.installer.root / "installation-incomplete").exists())

    def test_entry_migration_failure_keeps_blocker(self):
        _, _, _, state = self.run_entry("migration")
        self.assertEqual(state["error"], "MIGRATION_FAILED")
        self.assertTrue((self.installer.root / "installation-incomplete").exists())

    def test_entry_readiness_failure_keeps_blocker(self):
        _, _, _, state = self.run_entry("health")
        self.assertEqual(state["error"], "STARTUP_TIMEOUT")
        self.assertTrue((self.installer.root / "installation-incomplete").exists())

    def test_worker_load_failure_is_not_success_and_does_not_stop_core(self):
        _, _, events, state = self.run_entry("worker")
        self.assertEqual(state["error"], "WORKER_STARTUP_FAILED")
        self.assertNotIn(("signal", 101, __import__("signal").SIGTERM), events)
        self.assertTrue((self.installer.root / "installation-incomplete").exists())

    def test_stop_during_preflight_does_not_install_or_restart(self):
        import signal

        _, processes, events, state = self.run_entry("cancel-preflight")
        self.assertEqual(len(processes), 1)
        self.assertEqual(state["error"], "CONTAINER_STOPPED")
        self.assertIn(("signal", 200, signal.SIGTERM), events)
        self.assertTrue((self.runtime / "old").exists())

    def test_adopted_tool_prevents_copy_after_main_exits(self):
        _, processes, _, state = self.run_entry("tool-timeout")
        self.assertEqual(len(processes), 1)
        self.assertEqual(state["error"], "STOP_TIMEOUT")
        self.assertTrue((self.runtime / "old").exists())


if __name__ == "__main__":
    unittest.main()
