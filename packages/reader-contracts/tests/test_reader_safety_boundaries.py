from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest.mock import patch

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
        source = "throw new Error(`PLATFORM_POLICY_ALGORITHM_UNSUPPORTED:${algorithm}`)"

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

    def test_copied_detection_facts_are_owned_by_generated_rules(self) -> None:
        trigger = "EPUB_RESOURCE_INTEGRITY_DETECTED"
        self.assertIsNotNone(
            self.checker.find_source_literal_containing(
                f'facts: ["{trigger}"]',
                (trigger,),
            )
        )
        self.assertIsNone(
            self.checker.find_source_literal_containing(
                "facts: [readerSafetyRule(ruleId).trigger]",
                (trigger,),
            )
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "adapter.swift"
            source.write_text(f'facts: ["{trigger}"]', encoding="utf-8")
            policy = {
                "rules": [
                    {
                        "id": "EPUB.RESOURCE_INTEGRITY",
                        "trigger": trigger,
                        "errorCode": None,
                    }
                ],
                "implementationFailureCodes": [],
            }
            with patch.multiple(
                self.checker, ROOT=root, source_files=lambda: (source,)
            ):
                issues = self.checker.check_source_ownership(policy)
            self.assertEqual(len(issues), 1)
            self.assertIn("raw Reader safety trigger", issues[0])

    def test_comment_apostrophes_cannot_turn_generated_code_into_a_literal(
        self,
    ) -> None:
        code = "PLATFORM_POLICY_ALGORITHM_UNSUPPORTED"
        source = (
            "/** The parser's role is preserved. */\n"
            'val name = "full-path"\n'
            f"val code = ReaderSafetyErrorCode.{code}\n"
            "// Another parser's declaration.\n"
        )
        self.assertIsNone(self.checker.find_source_literal_containing(source, (code,)))
        self.assertIsNotNone(
            self.checker.find_source_literal_containing(
                source + f'val forbidden = "{code}"', (code,)
            )
        )
        self.assertIsNotNone(
            self.checker.find_source_literal_containing(
                f'val forbidden = "http://example.invalid/{code}"', (code,)
            )
        )

    def test_private_policy_catalogs_cannot_hide_in_regex_set_or_branch(self) -> None:
        sources = (
            '_SAFE_NCX_DOCTYPE = re.compile(r"<!DOCTYPE ncx PUBLIC")',
            'const blockedSchemes = new Set(["custom"]);',
            'val SANITIZED_ELEMENTS = setOf("unfamiliar")',
            'if (doctypeName !== "html") reject();',
            'if systemId not in ["known-dtd"]: reject()',
            "private const val MAX_REFERENCE_LENGTH = 256",
            "return ['http:', 'https:', 'mailto:'].includes(new URL(href).protocol)",
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertTrue(
                    any(
                        pattern.search(source)
                        for pattern in self.checker.PRIVATE_CATALOG_PATTERNS
                    )
                )

    def test_generated_catalog_adapters_and_xml_token_scanners_remain_allowed(
        self,
    ) -> None:
        sources = (
            "const blockedSchemes = new Set(profile.blockedAuthorSchemes);",
            "const declaration = /<!DOCTYPE\\b/i.exec(markup);",
            "SANITIZED_ELEMENTS = set(profile.sanitized_elements)",
            "return profile.blockedAuthorSchemes.includes(scheme)",
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertFalse(
                    any(
                        pattern.search(source)
                        for pattern in self.checker.PRIVATE_CATALOG_PATTERNS
                    )
                )


if __name__ == "__main__":
    unittest.main()
