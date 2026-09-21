"""Isolated installation behavior; real Docker acceptance is separate."""

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from container_install import Installation, InstallError, retire_previous_installation


class InstallationTests(unittest.TestCase):
    def test_restart_retires_every_previous_installation_stage(self):
        for phase in (
            "requested",
            "checking",
            "stopping",
            "backup",
            "copying",
            "starting",
            "failed",
        ):
            with self.subTest(phase=phase):
                root = self.installer.root
                state = {
                    "phase": phase,
                    "error": "PREFLIGHT_FAILED" if phase == "failed" else None,
                }
                (root / "preparation.json").write_text(json.dumps(state))
                (root / "install-request.json").write_text("old request")
                (root / "installation-incomplete").write_text("old marker")
                (root / "database-before-update.sqlite3").write_bytes(b"backup")
                retire_previous_installation(self.storage)
                result = json.loads((root / "preparation.json").read_text())
                self.assertEqual(result["phase"], "failed")
                self.assertEqual(
                    result["error"],
                    "PREFLIGHT_FAILED" if phase == "failed" else "CONTAINER_RESTARTED",
                )
                self.assertFalse((root / "install-request.json").exists())
                self.assertTrue((root / "installation-incomplete").exists())
                self.assertEqual(
                    (root / "database-before-update.sqlite3").read_bytes(), b"backup"
                )

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

    def test_claim_mutex_and_sync_preserves_database(self):
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
        self.installer.verify_dependencies()
        self.installer.reserve()
        self.installer.synchronize()
        self.assertFalse((self.runtime / "old").exists())
        self.assertEqual((self.runtime / ".initialized").read_text(), "1\n")
        self.assertEqual((self.runtime / "link").read_text(), "B")
        self.assertEqual((self.storage / "secret").read_text(), "keep")
        with sqlite3.connect(self.storage / "database/shuku.sqlite3") as db:
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
            self.installer.reserve()
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
        self.installer.reserve()
        self.installer.synchronize()
        self.assertEqual((outside / "keep").read_text(), "safe")

    def test_runtime_link_rejected(self):
        shutil.rmtree(self.runtime)
        self.runtime.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(InstallError):
            self.installer.reserve()
            self.installer.synchronize()

    def test_locked_database_does_not_block_installation(self):
        with sqlite3.connect(self.storage / "database/shuku.sqlite3") as locked:
            locked.execute("BEGIN EXCLUSIVE")
            with patch.object(
                sqlite3,
                "connect",
                side_effect=AssertionError("updater opened database"),
            ):
                _, processes, _, state = self.run_entry("success")
        self.assertEqual(len(processes), 2)
        self.assertEqual(state["phase"], "applied")
        self.assertEqual((self.runtime / "new").read_text(), "B")
        self.assertFalse(list(self.installer.root.glob("database-before-*.sqlite3")))
        self.assertNotIn(
            "phase=backup", (self.installer.root / "installation.log").read_text()
        )

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
        latest_state = [None]
        original_phase = Installation.phase

        def observe_phase(installer, *args, **kwargs):
            original_phase(installer, *args, **kwargs)
            latest_state[0] = dict(installer.state)

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
            state = latest_state[0] or json.loads(
                (self.installer.root / "preparation.json").read_text()
            )
            if state["phase"] == "checking" and outcome == "cancel-preflight":
                handlers[signal.SIGTERM](signal.SIGTERM, None)
            if helpers and helpers[0].pid in exiting and helpers[0].pid not in reaped:
                reaped.add(helpers[0].pid)
                return helpers[0].pid, 0
            if (
                state["phase"] == "applied"
                and outcome != "migration"
                and (outcome != "slow" or clock[0] >= 500)
            ):
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
            stack.enter_context(patch.object(Installation, "phase", observe_phase))
            if outcome in {"state", "reserve"}:
                from container_install import write_json

                def fail_write(path, value):
                    if path.name == (
                        "preparation.json"
                        if outcome == "state"
                        else "installation-incomplete"
                    ):
                        raise PermissionError("injected")
                    return write_json(path, value)

                stack.enter_context(
                    patch("container_install.write_json", side_effect=fail_write)
                )
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
            if outcome == "copy":
                stack.enter_context(
                    patch.object(shutil, "copytree", side_effect=OSError("copy failed"))
                )
            result = entry.run_application(self.runtime, self.storage)
        return (
            result,
            processes,
            events,
            latest_state[0]
            or json.loads((self.installer.root / "preparation.json").read_text()),
        )

    def test_entry_stops_before_copy_and_restarts(self):
        _result, processes, events, state = self.run_entry("success")
        self.assertEqual(len(processes), 2)
        self.assertEqual(state["phase"], "applied")
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

    def test_application_exit_is_propagated_without_health_verdict(self):
        result, _, _, state = self.run_entry("migration")
        self.assertEqual(result, 37)
        self.assertEqual(state["phase"], "applied")

    def test_slow_start_does_not_trigger_health_timeout(self):
        _, processes, events, state = self.run_entry("slow")
        self.assertEqual(len(processes), 2)
        self.assertEqual(state["phase"], "applied")
        self.assertEqual(sum(event == "launch" for event in events), 2)

    def test_unwritable_phase_record_still_launches_replaced_program(self):
        _, processes, _, state = self.run_entry("state")
        self.assertEqual(len(processes), 2)
        self.assertEqual(state["phase"], "applied")

    def test_control_record_failure_keeps_old_service(self):
        _, processes, events, state = self.run_entry("reserve")
        self.assertEqual(len(processes), 1)
        self.assertEqual(state["phase"], "failed")
        self.assertNotIn(("signal", 100, __import__("signal").SIGUSR1), events)
        self.assertTrue((self.runtime / "old").exists())

    def test_state_and_log_failure_do_not_block_copy_or_applied(self):
        from container_install import write_json

        original_open = __import__("os").open

        def fail_state(path, value):
            if path.name == "preparation.json":
                raise PermissionError("injected")
            return write_json(path, value)

        def fail_log(path, *args, **kwargs):
            if str(path).endswith("installation.log"):
                raise PermissionError("injected")
            return original_open(path, *args, **kwargs)

        self.installer.reserve()
        with (
            patch("container_install.write_json", side_effect=fail_state),
            patch("os.open", side_effect=fail_log),
        ):
            self.installer.phase("copying")
            self.installer.synchronize()
            self.installer.success()
        self.assertEqual(self.installer.state["phase"], "applied")
        self.assertEqual((self.runtime / "new").read_text(), "B")

    def test_dependency_record_failure_preserves_blocker_for_next_update(self):
        from types import SimpleNamespace

        from container_install import write_json

        self.installer.reserve()
        self.installer.dependencies = SimpleNamespace(result={"protocol": 2})

        def fail_record(path, value):
            if path.name == "installed.json":
                raise PermissionError("injected")
            return write_json(path, value)

        with patch("container_install.write_json", side_effect=fail_record):
            self.installer.success()
        self.assertEqual(self.installer.state["phase"], "applied")
        self.assertTrue((self.installer.root / "installation-incomplete").exists())
        (self.installer.root / "install-request.json").write_text(
            json.dumps({"target": self.installer.state["target"]})
        )
        self.installer.state["phase"] = "requested"
        write_json(self.installer.root / "preparation.json", self.installer.state)
        with self.assertRaisesRegex(InstallError, "INSTALLATION_RECORD_UNAVAILABLE"):
            self.installer.claim()

    def test_cleanup_failure_does_not_undo_applied(self):
        self.installer.reserve()
        with patch.object(Path, "unlink", side_effect=PermissionError("injected")):
            self.installer.success()
        self.assertEqual(self.installer.state["phase"], "applied")
        self.assertIsNone(self.installer.lock)

    def test_malformed_historical_phase_is_only_a_warning(self):
        (self.installer.root / "preparation.json").write_text('{"phase": []}')
        self.assertTrue(retire_previous_installation(self.storage))

    def test_old_request_archive_failure_disables_consumption(self):
        with patch.object(Path, "replace", side_effect=PermissionError("injected")):
            self.assertFalse(retire_previous_installation(self.storage))
        self.assertTrue((self.installer.root / "install-request.json").exists())

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
