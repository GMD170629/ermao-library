from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

CONFORMANCE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def _load_module(path: Path, name: str) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def test_backend_report_executes_parser_and_matches_contract() -> None:
    runner = _load_module(
        CONFORMANCE_ROOT / "reader_safety_conformance.py",
        "backend_reader_safety_conformance_test",
    )
    verifier = _load_module(
        REPOSITORY_ROOT
        / "packages/reader-contracts/verify-reader-safety-conformance.py",
        "reader_safety_conformance_verifier_backend_test",
    )
    suite, suite_cases, expected = verifier.load_suite_and_expected()

    report = runner.generate_backend_report()

    validated = verifier.validate_report(
        report,
        suite=suite,
        suite_cases=suite_cases,
        expected_cases=expected,
    )
    assert validated.consumer == "BACKEND"
    assert len(validated.results) == 43
