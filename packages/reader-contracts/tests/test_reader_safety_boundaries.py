from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[3]
CHECKER = ROOT / "packages/reader-contracts/check-reader-safety-boundaries.py"


def load_checker() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "reader_safety_boundary_checker", CHECKER
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot load Reader safety boundary checker")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class ReaderSafetyBoundaryCheckerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.checker = load_checker()

    def test_finds_error_code_embedded_in_template_literal(self) -> None:
        source = (
            "throw new Error(`"
            "PLATFORM_POLICY_ALGORITHM_UNSUPPORTED:${algorithm}`)"
        )

        match = self.checker.find_source_literal_containing(
            source, ("PLATFORM_POLICY_ALGORITHM_UNSUPPORTED",)
        )

        self.assertIsNotNone(match)

    def test_does_not_cross_python_triple_quoted_literal_boundaries(self) -> None:
        source = '''PATTERN = re.compile(r"""["']""")
failure = ReaderSafetyErrorCode.PLATFORM_POLICY_ALGORITHM_UNSUPPORTED.value
'''

        match = self.checker.find_source_literal_containing(
            source, ("PLATFORM_POLICY_ALGORITHM_UNSUPPORTED",)
        )

        self.assertIsNone(match)


if __name__ == "__main__":
    unittest.main()
