from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT_PATH = Path(__file__).with_name("compare_android_warm_page.py")
SPEC = importlib.util.spec_from_file_location("android_warm_page_comparator", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load comparator module from {SCRIPT_PATH}")
COMPARATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = COMPARATOR
SPEC.loader.exec_module(COMPARATOR)


class AndroidWarmPageComparatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        (self.root / ".git").mkdir()
        (self.root / "docs" / "assets" / "mobile-app-hifi-v1").mkdir(parents=True)
        self.actual_directory = self.root / "actual"
        self.actual_directory.mkdir()
        self.reference_path = (
            self.root / "docs" / "assets" / "mobile-app-hifi-v1" / "reference.png"
        )
        Image.new("RGB", (4, 4), (250, 249, 247)).save(self.reference_path)
        self.manifest_path = self.root / "reference-manifest.json"
        self._write_manifest(self.reference_path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write_manifest(self, reference_path: Path) -> None:
        reference_sha256 = (
            hashlib.sha256(reference_path.read_bytes()).hexdigest()
            if reference_path.is_file()
            else "0" * 64
        )
        payload = {
            "schemaVersion": 1,
            "canonicalViewport": {"width": 4, "height": 4},
            "comparison": {
                "maximumChannelDifference": 0,
                "maximumAppOwnedDifferenceRatio": 0.0,
            },
            "ownershipProfiles": {
                "test": {
                    "defaultOwnership": "C",
                    "regions": [
                        {
                            "ownership": "A",
                            "name": "system row",
                            "bounds": [0, 0, 4, 1],
                        }
                    ],
                }
            },
            "scenes": [
                {
                    "id": "scene",
                    "actualFile": "scene.png",
                    "reference": str(reference_path.relative_to(self.root)).replace("\\", "/"),
                    "referenceSha256": reference_sha256,
                    "ownershipProfile": "test",
                    "anchors": [
                        {"id": "content", "ownership": "C", "role": "testContent"}
                    ],
                }
            ],
        }
        self.manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    def _load_manifest(self):
        return COMPARATOR.load_manifest(self.manifest_path, self.root)

    def _write_actual(self, changed_pixel: tuple[int, int] | None = None) -> None:
        with Image.open(self.reference_path) as reference:
            actual = reference.convert("RGB")
        if changed_pixel is not None:
            actual.putpixel(changed_pixel, (0, 0, 0))
        actual.save(self.actual_directory / "scene.png")
        actual.close()

    def test_identical_candidate_writes_evidence_without_baseline(self) -> None:
        self._write_actual()
        manifest = self._load_manifest()
        output = self.root / "evidence"

        results = COMPARATOR.run_comparison(
            manifest,
            manifest.scenes,
            self.actual_directory,
            output,
        )

        self.assertEqual("pass", results[0]["verdict"])
        self.assertTrue((output / "reference" / "scene.png").is_file())
        self.assertTrue((output / "actual" / "scene.png").is_file())
        self.assertTrue((output / "overlay" / "scene.png").is_file())
        self.assertTrue((output / "heatmap" / "scene.png").is_file())
        summary = json.loads((output / "metrics" / "summary.json").read_text())
        self.assertFalse(summary["baselineWritten"])
        self.assertFalse((self.root / "expected").exists())

    def test_app_owned_difference_fails_blocking_gate(self) -> None:
        self._write_actual(changed_pixel=(1, 1))
        manifest = self._load_manifest()

        results = COMPARATOR.run_comparison(
            manifest,
            manifest.scenes,
            self.actual_directory,
            self.root / "evidence",
        )

        self.assertEqual("fail", results[0]["verdict"])
        self.assertFalse(results[0]["appOwnedGate"]["passes"])
        self.assertGreater(
            results[0]["ownershipMetrics"]["C"]["differentPixelRatio"],
            0,
        )

    def test_system_owned_difference_is_reported_but_not_cross_reference_blocking(self) -> None:
        self._write_actual(changed_pixel=(1, 0))
        manifest = self._load_manifest()

        results = COMPARATOR.run_comparison(
            manifest,
            manifest.scenes,
            self.actual_directory,
            self.root / "evidence",
        )

        self.assertEqual("pass", results[0]["verdict"])
        self.assertGreater(
            results[0]["ownershipMetrics"]["A"]["differentPixelRatio"],
            0,
        )
        self.assertEqual(
            0,
            results[0]["ownershipMetrics"]["C"]["differentPixelRatio"],
        )

    def test_missing_reference_fails_explicitly(self) -> None:
        missing = self.reference_path.with_name("missing.png")
        self._write_manifest(missing)
        manifest = self._load_manifest()

        with self.assertRaisesRegex(
            COMPARATOR.ConfigurationError,
            "Missing authoritative reference for 'scene'",
        ):
            COMPARATOR.validate_manifest_references(manifest, manifest.scenes)

    def test_refuses_to_write_under_reference_or_actual_inputs(self) -> None:
        self._write_actual()
        manifest = self._load_manifest()
        protected_output = self.reference_path.parent / "evidence"

        with self.assertRaisesRegex(COMPARATOR.ConfigurationError, "protected"):
            COMPARATOR.run_comparison(
                manifest,
                manifest.scenes,
                self.actual_directory,
                protected_output,
            )
        with self.assertRaisesRegex(COMPARATOR.ConfigurationError, "protected"):
            COMPARATOR.run_comparison(
                manifest,
                manifest.scenes,
                self.actual_directory,
                self.actual_directory / "evidence",
            )


if __name__ == "__main__":
    unittest.main()
