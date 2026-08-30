from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_ROOT = ROOT / "packages/reader-contracts"


def load_module(path: Path, name: str) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


class ReaderSafetyConformanceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verifier = load_module(
            CONTRACT_ROOT / "verify-reader-safety-conformance.py",
            "reader_safety_conformance_verifier_test",
        )
        cls.suite, cls.suite_cases, cls.expected = (
            cls.verifier.load_suite_and_expected()
        )

    def report(self, consumer: str = "BACKEND") -> dict[str, object]:
        results = []
        for suite_case in self.suite_cases:
            if consumer not in suite_case.consumers:
                continue
            expected = self.expected[suite_case.case_id]
            results.append(
                {
                    "caseId": expected.case_id,
                    "inputSha256": expected.input_sha256,
                    "terminalRuleId": expected.terminal_rule_id,
                    "action": expected.action,
                    "errorCode": expected.error_code,
                    "orderedRuleEvents": list(expected.ordered_rule_events),
                    "semanticProjectionSha256": expected.semantic_projection_sha256,
                }
            )
        return {
            "schemaVersion": 1,
            "policyId": self.suite["policyId"],
            "policyVersion": self.suite["policyVersion"],
            "policyDigest": self.suite["policyDigest"],
            "consumer": consumer,
            "engine": "contract-verifier-test",
            "results": results,
            "omissions": [],
        }

    def test_suite_is_policy_bound_and_uses_real_cross_platform_consumers(self) -> None:
        self.assertEqual(48, len(self.suite_cases))
        self.assertEqual(41, len({case.rule_id for case in self.suite_cases}))
        self.assertEqual(
            set(self.expected), {case.case_id for case in self.suite_cases}
        )
        self.assertEqual(
            {"BACKEND", "WEB", "KMP", "ANDROID"},
            set(
                next(
                    case
                    for case in self.suite_cases
                    if case.case_id == "original-at-limit"
                ).consumers
            ),
        )
        self.assertEqual(
            {"WEB"},
            set(
                next(
                    case
                    for case in self.suite_cases
                    if case.case_id == "audio-codec-unsupported"
                ).consumers
            ),
        )
        self.assertEqual(
            42,
            sum("ANDROID" in case.consumers for case in self.suite_cases),
        )

    def test_suite_cannot_replace_android_obligation_with_kmp(self) -> None:
        suite = copy.deepcopy(self.suite)
        original = next(
            case for case in suite["cases"] if case["id"] == "original-at-limit"
        )
        original["consumers"].remove("ANDROID")
        with tempfile.TemporaryDirectory() as directory:
            suite_path = Path(directory) / "suite.json"
            suite_path.write_text(json.dumps(suite), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "suite platform execution owners differ",
            ):
                self.verifier.load_suite_and_expected(suite_path=suite_path)

    def test_valid_report_is_accepted_and_wrong_actual_result_is_rejected(self) -> None:
        report = self.report()
        self.verifier.validate_report(
            report,
            suite=self.suite,
            suite_cases=self.suite_cases,
            expected_cases=self.expected,
        )

        corrupted = copy.deepcopy(report)
        corrupted["results"][0]["semanticProjectionSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "actual conformance result differs"):
            self.verifier.validate_report(
                corrupted,
                suite=self.suite,
                suite_cases=self.suite_cases,
                expected_cases=self.expected,
            )

    def test_cross_report_verifier_requires_requested_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "backend.json"
            report_path.write_text(
                json.dumps(self.report(), ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "missing required"):
                self.verifier.verify_report_paths(
                    [report_path], required_consumers=frozenset({"BACKEND", "WEB"})
                )

    def test_report_cannot_omit_one_required_manifest_case(self) -> None:
        report = self.report()
        report["results"].pop()

        with self.assertRaisesRegex(ValueError, "coverage/order differs"):
            self.verifier.validate_report(
                report,
                suite=self.suite,
                suite_cases=self.suite_cases,
                expected_cases=self.expected,
            )

    def test_declared_execution_owner_cannot_omit_a_case(self) -> None:
        report = self.report("ANDROID")
        omitted = report["results"].pop()
        report["omissions"] = [
            {
                "caseId": omitted["caseId"],
                "reasonCode": "ANDROID_PRODUCTION_ADAPTER_UNAVAILABLE",
                "requiredGate": "ANDROID_INSTRUMENTED_OR_PHYSICAL_DEVICE",
            }
        ]
        with self.assertRaisesRegex(ValueError, "cannot omit"):
            self.verifier.validate_report(
                report,
                suite=self.suite,
                suite_cases=self.suite_cases,
                expected_cases=self.expected,
            )


if __name__ == "__main__":
    unittest.main()
