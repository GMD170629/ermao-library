"""Isolated startup/process tests; fixtures do not stand in for container acceptance."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts/container-entry.py"
spec = importlib.util.spec_from_file_location("container_entry", ENTRY)
assert spec and spec.loader
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class ContainerEntryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="shuku-entry-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.seed = self.root / "image"
        self.storage = self.root / "storage"
        self.runtime = self.storage / "runtime"
        self.seed.mkdir()
        self.storage.mkdir()
        for name in (
            "scripts/start-unified-app.sh",
            "scripts/unified-http-gateway.mjs",
            "apps/web/server.js",
            "apps/api-python/app/bootstrap/prestart.py",
        ):
            file = self.seed / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("# fixture\n")
        shutil.copy2(
            ROOT / "scripts/start-unified-app.sh",
            self.seed / "scripts/start-unified-app.sh",
        )
        (self.seed / "application.json").write_text(
            json.dumps({"version": "1.0.5", "protocol": 2})
        )
        dependencies = self.storage / "dependencies"
        (dependencies / "python/bin").mkdir(parents=True)
        (dependencies / "installed.json").write_text('{"protocol":2}')
        self.bin = self.root / "bin"
        self.bin.mkdir()
        # Exercise the real shell's roles, cwd, prestart barrier and signal traps.
        executable = self.bin / "fixture"
        executable.write_text(
            f"#!{sys.executable}\n"
            "import json, os, signal, sys, time\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            'if args and args[0] == "-c": sys.exit(0)\n'
            'role = " ".join(args)\n'
            'log = Path(os.environ["STORAGE_ROOT"]) / "events"\n'
            "def record(kind):\n"
            '    with log.open("a") as f: f.write(json.dumps([kind, role, os.getpid(), os.getcwd(), os.environ["ROOT_DIR"]]) + "\\n")\n'
            "def stop(*args):\n"
            '    record("stop")\n'
            "    sys.exit(0)\n"
            "signal.signal(signal.SIGTERM, stop)\n"
            'record("start")\n'
            'if "prestart" in role and os.environ.get("FAIL_PRESTART"): sys.exit(37)\n'
            'if "prestart" in role and not os.environ.get("HOLD_PRESTART"): sys.exit(0)\n'
            'if "app.worker.main" in role and os.environ.get("ORPHAN_TOOL"):\n'
            '    storage = Path(os.environ["STORAGE_ROOT"])\n'
            "    intermediate = os.fork()\n"
            "    if intermediate == 0:\n"
            "        if os.fork() == 0:\n"
            '            (storage / "tool-pid.tmp").write_text(str(os.getpid()))\n'
            '            (storage / "tool-pid.tmp").rename(storage / "tool-pid")\n'
            '            while not (storage / "release-tool").exists(): time.sleep(.02)\n'
            '            (storage / "tool-exited").touch()\n'
            "            os._exit(0)\n"
            "        os._exit(0)\n"
            "    assert os.waitpid(intermediate, 0) == (intermediate, 0)\n"
            '    (storage / "intermediate-reaped").touch()\n'
            "while True: time.sleep(.02)\n"
        )
        executable.chmod(0o755)
        for name in ("python", "uvicorn", "node"):
            (self.bin / name).symlink_to(executable.name)

        (dependencies / "python/bin/python").symlink_to(self.bin / "fixture")

    def launch(self, **extra: str) -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [sys.executable, str(ENTRY)],
            env={
                **os.environ,
                "SHUKU_IMAGE_ROOT": str(self.seed),
                "STORAGE_ROOT": str(self.storage),
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "SESSION_SECRET": "fixture-secret",
                **extra,
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        def cleanup() -> None:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=10)

        self.addCleanup(cleanup)
        return process

    def events(self) -> list[list]:
        import json

        log = self.storage / "events"
        return (
            [json.loads(line) for line in log.read_text().splitlines()]
            if log.exists()
            else []
        )

    def await_starts(self, process: subprocess.Popen[str], count: int) -> None:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if len([event for event in self.events() if event[0] == "start"]) >= count:
                return
            if process.poll() is not None:
                self.fail(str(process.communicate()))
            time.sleep(0.03)
        self.fail("services did not start")

    def test_real_shell_runs_runtime_and_stops_all_services_without_restart(
        self,
    ) -> None:
        process = self.launch(
            ROOT_DIR="/invalid", PYTHON_API_DIR="/invalid", NEXT_SERVER="/invalid"
        )
        self.await_starts(process, 5)
        starts = self.events()
        self.assertIn("prestart", starts[0][1])
        for _, role, _, cwd, root in starts:
            self.assertEqual(root, str(self.runtime))
            self.assertTrue(Path(cwd).is_relative_to(self.runtime))
            if "server" in role or "gateway" in role:
                self.assertIn(str(self.runtime), role)
        duplicate = self.launch()
        self.assertNotEqual(duplicate.wait(timeout=5), 0)
        self.assertIn("already running", duplicate.communicate()[1])
        process.terminate()
        self.assertEqual(process.wait(timeout=10), 143)
        self.assertEqual(
            len([event for event in self.events() if event[0] == "start"]), 5
        )
        self.assertEqual(
            len([event for event in self.events() if event[0] == "stop"]), 4
        )
        for event in starts:
            with self.assertRaises(ProcessLookupError):
                os.kill(event[2], 0)

    def test_stop_during_prestart_never_starts_business(self) -> None:
        process = self.launch(HOLD_PRESTART="1")
        self.await_starts(process, 1)
        process.terminate()
        self.assertEqual(process.wait(timeout=10), 143)
        self.assertEqual([event[0] for event in self.events()], ["start", "stop"])

    @unittest.skipUnless(
        sys.platform == "linux", "requires Linux child subreaper and /proc"
    )
    def test_orphan_tool_is_reaped_while_business_keeps_running(self) -> None:
        process = self.launch(ORPHAN_TOOL="1")
        self.await_starts(process, 5)
        starts = self.events()
        pid_file = self.storage / "tool-pid"
        deadline = time.monotonic() + 5
        while not (
            pid_file.exists() and (self.storage / "intermediate-reaped").exists()
        ):
            self.assertLess(time.monotonic(), deadline, "tool fixture did not start")
            time.sleep(0.02)
        tool_pid = int(pid_file.read_text())
        status_file = Path(f"/proc/{tool_pid}/status")
        while f"PPid:\t{process.pid}\n" not in status_file.read_text():
            self.assertLess(time.monotonic(), deadline, "tool was not adopted by entry")
            time.sleep(0.02)
        self.assertNotIn("State:\tZ", status_file.read_text())
        (self.storage / "release-tool").touch()
        deadline = time.monotonic() + 5
        while status_file.exists():
            self.assertLess(time.monotonic(), deadline, "exited orphan was not reaped")
            time.sleep(0.02)
        self.assertTrue((self.storage / "tool-exited").exists())
        self.assertIsNone(process.poll())
        self.assertEqual(self.events(), starts)
        for _, role, pid, *_ in starts:
            if "prestart" not in role:
                os.kill(pid, 0)

    def test_main_script_failure_status_is_preserved(self) -> None:
        process = self.launch(FAIL_PRESTART="1")
        self.assertEqual(process.wait(timeout=10), 37)
        self.assertEqual(len(self.events()), 1)
        self.assertIn("prestart", self.events()[0][1])

    def test_reuse_without_seed_preserves_runtime_and_user_data(self) -> None:
        for name in (
            "database/shuku.sqlite3",
            "secrets/session-secret",
            "covers/cover",
            "config",
        ):
            file = self.storage / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"unchanged-user-data")
        entry.initialize_runtime(self.seed, self.runtime)
        marker = self.runtime / "keep"
        marker.write_text("newer-program")
        (self.runtime / "apps/web/server.js").write_text("newer-server")
        shutil.rmtree(self.seed)
        process = self.launch()
        self.await_starts(process, 5)
        process.terminate()
        self.assertEqual(process.wait(timeout=10), 143)
        self.assertEqual(marker.read_text(), "newer-program")
        self.assertEqual(
            (self.runtime / "apps/web/server.js").read_text(), "newer-server"
        )
        for name in (
            "database/shuku.sqlite3",
            "secrets/session-secret",
            "covers/cover",
            "config",
        ):
            self.assertEqual((self.storage / name).read_bytes(), b"unchanged-user-data")

    def test_copy_failure_leaves_incomplete_directory_and_refuses_retry(self) -> None:
        original = shutil.copyfile

        def fail_copy(source: str, destination: str, **kwargs: object) -> str:
            if os.fspath(source).endswith("server.js"):
                raise OSError("injected copy failure")
            return original(source, destination, **kwargs)

        with (
            patch.object(entry.shutil, "copyfile", side_effect=fail_copy),
            self.assertRaises(shutil.Error),
        ):
            entry.initialize_runtime(self.seed, self.runtime)
        self.assertFalse((self.runtime / ".initialized").exists())
        with self.assertRaisesRegex(entry.StartupError, "incomplete"):
            entry.initialize_runtime(self.seed, self.runtime)

    def test_unwritable_runtime_and_invalid_storage_fail_before_business(self) -> None:
        entry.initialize_runtime(self.seed, self.runtime)
        with (
            patch.object(entry.tempfile, "TemporaryFile", side_effect=PermissionError),
            self.assertRaises(PermissionError),
        ):
            entry.initialize_runtime(self.seed, self.runtime)
        process = self.launch(STORAGE_ROOT=str(self.seed / "apps"))
        self.assertNotEqual(process.wait(timeout=5), 0)
        self.assertIn("must be separate", process.communicate()[1])
        self.assertEqual(self.events(), [])

    def test_missing_files_never_marks_initialization_complete(self) -> None:
        (self.seed / "apps/web/server.js").unlink()
        with self.assertRaisesRegex(entry.StartupError, "missing"):
            entry.initialize_runtime(self.seed, self.runtime)
        self.assertFalse((self.runtime / ".initialized").exists())

    def test_unfinished_installation_blocks_startup(self) -> None:
        state = self.storage / "update-tmp"
        state.mkdir()
        (state / "installation-incomplete").write_text("{}")
        process = self.launch()
        _output, error = process.communicate(timeout=5)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("installation unfinished", error)
        self.assertEqual(self.events(), [])

    def test_runtime_link_cannot_redirect_initialization(self) -> None:
        self.runtime.symlink_to(self.seed, target_is_directory=True)
        with self.assertRaisesRegex(entry.StartupError, "link"):
            entry.initialize_runtime(self.seed, self.runtime)


if __name__ == "__main__":
    unittest.main()
