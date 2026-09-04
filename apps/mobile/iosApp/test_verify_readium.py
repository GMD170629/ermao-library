"""Prove accidental dependency and Reader v5 Locator regressions fail the build gate."""

import shutil
import tempfile
import unittest
from pathlib import Path

import verify_readium as gate


class ReadiumPinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for relative in [
            gate.PROJECT / "project.pbxproj",
            gate.LOCK,
            gate.MAPPER,
            gate.POLICY,
        ]:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(gate.ROOT / relative, destination)

    def test_approved_baseline_passes(self) -> None:
        gate.verify(self.root)

    def test_each_stale_consumer_fails(self) -> None:
        changes = [
            (
                gate.PROJECT / "project.pbxproj",
                gate.REVISION,
                "f7d10d2bf5876408feae14d634416f69d1473fd8",
            ),
            (gate.LOCK, gate.REVISION, "f7d10d2bf5876408feae14d634416f69d1473fd8"),
            (gate.MAPPER, "locator.jsonString()", "wrappedLocatorJSON()"),
            (gate.POLICY, gate.REVISION, "unapproved"),
            (
                gate.PROJECT / "project.pbxproj",
                gate.REPOSITORY,
                "https://example.com/swift-toolkit.git",
            ),
            (gate.PROJECT / "project.pbxproj", "kind = revision;", "kind = branch;"),
        ]
        for relative, before, after in changes:
            with self.subTest(consumer=str(relative), change=after):
                path = self.root / relative
                original = path.read_text(encoding="utf-8")
                self.assertIn(before, original)
                path.write_text(original.replace(before, after), encoding="utf-8")
                try:
                    with self.assertRaises(ValueError):
                        gate.verify(self.root)
                finally:
                    path.write_text(original, encoding="utf-8")

    def test_engine_metadata_wrapper_fails(self) -> None:
        path = self.root / gate.MAPPER
        original = path.read_text(encoding="utf-8")
        path.write_text(
            original + '\nlet diagnostic = "readium-swift:3.9.0"\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "must not wrap or reconcile"):
            gate.verify(self.root)


if __name__ == "__main__":
    unittest.main()
