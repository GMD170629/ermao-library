"""Candidate harness selection: no Docker or publication in unit tests."""

import unittest

from accept_candidate_update import select_platforms


class CandidatePlatformTests(unittest.TestCase):
    def test_each_architecture_uses_immutable_child_not_attestation(self):
        index = {
            "manifests": [
                {
                    "platform": {"architecture": "amd64", "os": "linux"},
                    "digest": "sha256:" + "a" * 64,
                },
                {
                    "platform": {
                        "architecture": "arm64",
                        "os": "linux",
                        "variant": "v8",
                    },
                    "digest": "sha256:" + "b" * 64,
                },
                {
                    "platform": {"architecture": "unknown", "os": "unknown"},
                    "digest": "sha256:" + "c" * 64,
                    "annotations": {
                        "vnd.docker.reference.type": "attestation-manifest"
                    },
                },
            ]
        }
        result = select_platforms(index, "example/image@sha256:" + "d" * 64)
        self.assertEqual([p[0] for p in result], ["amd64", "arm64"])
        self.assertEqual(result[1][2], "example/image@sha256:" + "b" * 64)
        index["manifests"].append(index["manifests"][0])
        with self.assertRaises(ValueError):
            select_platforms(index, "example/image")

    def test_missing_or_invalid_platform_is_not_accepted(self):
        with self.assertRaises(ValueError):
            select_platforms({}, "example/image")
        with self.assertRaises(ValueError):
            select_platforms(
                {
                    "manifests": [
                        {
                            "platform": {"architecture": "amd64", "os": "linux"},
                            "digest": "latest",
                        }
                    ]
                },
                "example/image",
            )


if __name__ == "__main__":
    unittest.main()
