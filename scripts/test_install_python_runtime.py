"""Fast command-boundary checks; actual locked installation is verified separately."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/install-python-runtime.sh"


class RuntimeInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory(prefix="ermao-locked-install-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.project = self.root / "project with spaces"
        self.project.mkdir()
        for name in ("pyproject.toml", "uv.lock"):
            (self.project / name).write_text("fixture", encoding="utf-8")
        self.calls = self.root / "calls.jsonl"
        uv = self.root / "uv"
        uv.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "with open(os.environ['CALLS'], 'a') as log:\n"
            "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "stage = ' '.join(sys.argv[1:3]) if sys.argv[1] == 'pip' else sys.argv[1]\n"
            "if stage == os.environ.get('FAIL_STAGE'): sys.exit(73)\n",
            encoding="utf-8",
        )
        uv.chmod(0o755)

    def run_helper(self, fail_stage: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", str(HELPER), str(self.project), str(self.root / "isolated venv")],
            env={
                **os.environ,
                "PATH": f"{self.root}{os.pathsep}{os.environ['PATH']}",
                "CALLS": str(self.calls),
                "FAIL_STAGE": fail_stage,
            },
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def recorded(self) -> list[list[str]]:
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def test_installs_hashed_runtime_dependencies_into_explicit_venv(self) -> None:
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        export, venv, sync, check = self.recorded()
        for option in ("--locked", "--no-dev", "--no-emit-project"):
            self.assertIn(option, export)
        self.assertEqual(export[export.index("--project") + 1], str(self.project))
        self.assertEqual(venv[-1], str(self.root / "isolated venv"))
        self.assertEqual(sync[:2], ["pip", "sync"])
        self.assertIn("--require-hashes", sync)
        self.assertEqual(sync[sync.index("--only-binary") + 1], ":all:")
        self.assertEqual(check[:2], ["pip", "check"])
        self.assertFalse(Path(export[export.index("--output-file") + 1]).exists())

    def test_lock_error_prevents_environment_mutation(self) -> None:
        self.assertEqual(self.run_helper("export").returncode, 73)
        self.assertEqual(len(self.recorded()), 1)

    def test_install_error_propagates_without_unlocked_fallback(self) -> None:
        self.assertEqual(self.run_helper("pip sync").returncode, 73)
        self.assertEqual(len(self.recorded()), 3)

    def test_missing_lock_fails_before_calling_uv(self) -> None:
        (self.project / "uv.lock").unlink()
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_both_images_use_helper_lock_and_audio_probe(self) -> None:
        for relative in ("apps/web/Dockerfile.prod", "apps/api-python/Dockerfile"):
            with self.subTest(dockerfile=relative):
                dockerfile = (ROOT / relative).read_text()
                self.assertIn(
                    "install-python-runtime.sh /app/apps/api-python /opt/shuku-python",
                    dockerfile,
                )
                self.assertIn("apps/api-python/uv.lock", dockerfile)
                self.assertIn("ghcr.io/astral-sh/uv:0.11.29", dockerfile)
                self.assertIn("ffprobe -version", dockerfile)
                self.assertRegex(dockerfile, r"apt-get install[^\n]*\bffmpeg\b")
                self.assertNotIn("pip install", dockerfile)


if __name__ == "__main__":
    unittest.main()
