from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
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


class ReaderSafetyPolicyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generator = load_module(
            CONTRACT_ROOT / "generate-reader-safety-policy.py",
            "reader_safety_policy_generator_test",
        )
        cls.source = json.loads(
            (CONTRACT_ROOT / "reader-safety-policy.json").read_text(encoding="utf-8")
        )
        cls.policy = cls.generator.validate_policy(cls.source)
        cls.digest = cls.generator.policy_digest(cls.policy)

    def test_canonical_digest_is_order_independent(self) -> None:
        reordered = dict(reversed(tuple(self.source.items())))
        self.assertEqual(self.digest, self.generator.policy_digest(reordered))
        self.assertEqual(self.digest, self.source["policyDigest"])
        self.assertEqual(64, len(self.digest))

    def test_stale_source_digest_is_rejected(self) -> None:
        stale = copy.deepcopy(self.source)
        stale["policyDigest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "digest is stale"):
            self.generator.validate_policy(stale)

    def test_future_policy_version_validates_and_generates_bindings(self) -> None:
        future = copy.deepcopy(self.source)
        future["policyVersion"] = 2
        future["policyDigest"] = self.generator.policy_digest(future)

        validated = self.generator.validate_policy(future)

        self.assertEqual(2, validated["policyVersion"])
        self.assertIn(
            "READER_SAFETY_POLICY_VERSION = 2 as const",
            self.generator.render_typescript(validated, future["policyDigest"]),
        )
        self.assertIn(
            "const val policyVersion: Int = 2",
            self.generator.render_kotlin(validated, future["policyDigest"]),
        )
        self.assertIn(
            "READER_SAFETY_POLICY_VERSION: Final = 2",
            self.generator.render_python(validated, future["policyDigest"]),
        )

    def test_required_formats_and_mime_are_exact(self) -> None:
        formats = {entry["id"]: entry for entry in self.policy["formats"]}
        self.assertNotIn("KINDLE", formats)
        self.assertEqual("application/epub+zip", formats["EPUB"]["canonicalMimeType"])
        self.assertEqual(
            "application/x-mobipocket-ebook", formats["MOBI"]["canonicalMimeType"]
        )
        self.assertEqual(
            "application/vnd.amazon.ebook", formats["AZW3"]["canonicalMimeType"]
        )
        self.assertEqual([], formats["IMAGE_DIR"]["acceptedMimeTypes"])
        self.assertEqual(["BACKEND", "WEB"], formats["AUDIO"]["requiredConsumers"])
        comic = self.policy["profiles"]["comic"]
        self.assertEqual(
            {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
            },
            comic["pageMimeTypesByExtension"],
        )
        self.assertEqual(
            set(comic["allowedPageMimeTypes"]),
            set(comic["pageMimeTypesByExtension"].values()),
        )
        self.assertEqual(
            {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "image/webp": ".webp",
            },
            self.policy["profiles"]["reflowable"]["embeddedImageExtensionsByMimeType"],
        )

    def test_platform_and_engine_failures_are_generated_separately(self) -> None:
        self.assertEqual(
            {
                "ENGINE_POLICY_ALGORITHM_UNSUPPORTED",
                "PLATFORM_POLICY_ALGORITHM_UNSUPPORTED",
            },
            set(self.policy["implementationFailureCodes"]),
        )

    def test_budget_boundaries_and_rule_ownership(self) -> None:
        budgets = self.policy["budgets"]
        self.assertEqual(2 * 1024**3, budgets["originalMaxBytes"])
        self.assertEqual(10_000, budgets["archiveEntryMaxCount"])
        self.assertEqual(20_000, budgets["pdfPageMaxCount"])
        self.assertEqual(10_000, budgets["comicPageMaxCount"])
        references = {
            reference.removeprefix("budgets.")
            for rule in self.policy["rules"]
            for reference in rule["parameterRefs"]
            if reference.startswith("budgets.")
        }
        self.assertEqual(set(budgets), references)

    def test_standard_doctype_is_allowed_without_external_resolution(self) -> None:
        profile = self.policy["profiles"]["reflowable"]
        system_ids = {entry["systemId"] for entry in profile["safeDoctypes"]}
        self.assertIn("http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd", system_ids)
        self.assertIn("https://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd", system_ids)
        self.assertFalse(profile["externalDtdResolution"])
        self.assertTrue(profile["rejectInternalSubset"])
        self.assertTrue(profile["rejectCustomEntities"])
        self.assertEqual(["style"], profile["cssTextElements"])
        descriptors = {
            (
                tuple(descriptor["elements"]),
                descriptor["attribute"],
                descriptor["syntax"],
                descriptor["purpose"],
            )
            for descriptor in profile["uriAttributePolicies"]
        }
        self.assertIn((("*",), "style", "CSS", "SUBRESOURCE"), descriptors)
        self.assertIn((("*",), "srcset", "SRCSET", "SUBRESOURCE"), descriptors)
        self.assertIn((("a", "area"), "href", "SCALAR", "USER_NAVIGATION"), descriptors)
        self.assertIn(
            (("a", "area"), "ping", "SPACE_SEPARATED", "ALWAYS_REMOVE"),
            descriptors,
        )

    def test_normalization_v3_projection_uses_canonical_semantic_hash(self) -> None:
        fixture_root = CONTRACT_ROOT / "fixtures/normalization-v3"
        projection = json.loads(
            (fixture_root / "projection.json").read_text(encoding="utf-8")
        )
        expected = (
            "sha256:"
            + hashlib.sha256(
                self.generator.canonical_json(projection).encode("utf-8")
            ).hexdigest()
        )
        self.assertEqual(
            expected,
            (fixture_root / "projection.sha256").read_text(encoding="utf-8").strip(),
        )
        self.generator.validate_normalization_v3_fixture(
            policy=self.policy, digest=self.digest
        )

    def test_fixture_manifest_is_bound_to_policy_and_content(self) -> None:
        manifest = json.loads(
            (CONTRACT_ROOT / "fixtures/reader-safety-v1/manifest.json").read_text(
                encoding="utf-8"
            )
        )
        validated = self.generator.validate_fixture_manifest(
            manifest, policy=self.policy, digest=self.digest
        )
        self.assertEqual(self.digest, validated["policyDigest"])
        self.assertEqual(48, len(validated["cases"]))
        self.assertEqual(
            {rule["id"] for rule in self.policy["rules"]},
            {case["expected"]["terminalRuleId"] for case in validated["cases"]},
        )
        case_ids = {case["id"] for case in validated["cases"]}
        self.assertIn("safe-xhtml-11-http", case_ids)
        self.assertIn("xml-external-entity", case_ids)
        self.assertIn("comic-page-count-over-limit", case_ids)

        incomplete_consumers = copy.deepcopy(manifest)
        incomplete_consumers["cases"][0]["requiredConsumers"].pop()
        with self.assertRaisesRegex(ValueError, "exact consumer obligations"):
            self.generator.validate_fixture_manifest(
                incomplete_consumers,
                policy=self.policy,
                digest=self.digest,
            )

    def test_semantically_invalid_variants_are_rejected(self) -> None:
        kindle = copy.deepcopy(self.source)
        kindle["formats"][0]["id"] = "KINDLE"
        with self.assertRaisesRegex(ValueError, "invalid"):
            self.generator.validate_policy(kindle)

        missing_budget_owner = copy.deepcopy(self.source)
        missing_budget_owner["budgets"]["orphanBudget"] = 1
        with self.assertRaisesRegex(ValueError, "unreferenced"):
            self.generator.validate_policy(missing_budget_owner)

        missing_error = copy.deepcopy(self.source)
        target = next(
            rule
            for rule in missing_error["rules"]
            if rule["id"] == "REFLOWABLE.REJECT_XML_ENTITY"
        )
        target["errorCode"] = None
        with self.assertRaisesRegex(ValueError, "requires an error code"):
            self.generator.validate_policy(missing_error)

    def test_generated_bindings_match_source(self) -> None:
        expected = {
            self.generator.TS_TARGET: self.generator.render_typescript(
                self.policy, self.digest
            ),
            self.generator.KT_TARGET: self.generator.render_kotlin(
                self.policy, self.digest
            ),
            self.generator.PY_TARGET: self.generator.render_python(
                self.policy, self.digest
            ),
            self.generator.C_TARGET: self.generator.render_c(self.policy, self.digest),
        }
        for path, content in expected.items():
            with self.subTest(path=path):
                self.assertEqual(content, path.read_text(encoding="utf-8"))

    def test_generated_python_api_is_typed_and_immutable(self) -> None:
        generated = load_module(
            self.generator.PY_TARGET, "reader_safety_policy_generated_test"
        )
        azw3 = generated.require_reader_safety_format_policy("azw3")
        self.assertEqual(generated.ReaderSafetyFormat.AZW3, azw3.id)
        self.assertIn("application/vnd.amazon.ebook", azw3.accepted_mime_types)
        self.assertEqual(
            2 * 1024**3,
            generated.reader_safety_budget(
                generated.ReaderSafetyBudgetName.ORIGINAL_MAX_BYTES
            ),
        )
        rule = generated.reader_safety_rule(
            generated.ReaderSafetyRuleId.REFLOWABLE_REJECT_XML_ENTITY
        )
        self.assertEqual(generated.ReaderSafetyAction.REJECT_PUBLICATION, rule.action)
        self.assertTrue(generated.READER_SAFETY_REFLOWABLE_PROFILE.safe_doctypes)
        self.assertEqual(
            160,
            generated.READER_SAFETY_REFLOWABLE_PROFILE.named_entity_codepoints["nbsp"],
        )
        self.assertEqual(
            "audio/mpeg",
            generated.READER_SAFETY_AUDIO_PROFILE.container_mime_types[".mp3"],
        )
        self.assertEqual(
            "image/jpeg", generated.reader_safety_comic_page_mime_type(".JPG")
        )
        self.assertEqual(
            ".jpg", generated.reader_safety_fb2_embedded_image_extension("IMAGE/JPEG")
        )
        self.assertIn(
            generated.ReaderSafetyErrorCode.PLATFORM_POLICY_ALGORITHM_UNSUPPORTED,
            generated.READER_SAFETY_IMPLEMENTATION_FAILURE_CODES,
        )
        self.assertEqual(
            generated.ReaderSafetyUriPurpose.SUBRESOURCE,
            next(
                descriptor.purpose
                for descriptor in generated.READER_SAFETY_REFLOWABLE_PROFILE.uri_attribute_policies
                if descriptor.attribute == "style"
            ),
        )
        with self.assertRaises(TypeError):
            generated.READER_SAFETY_AUDIO_PROFILE.container_mime_types[".new"] = (
                "audio/new"
            )
        with self.assertRaises(TypeError):
            generated.READER_SAFETY_REFLOWABLE_PROFILE.named_entity_codepoints[
                "custom"
            ] = 1


if __name__ == "__main__":
    unittest.main()
