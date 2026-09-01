#!/usr/bin/env python3
"""Validate the authoritative Reader safety policy and generate typed bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = ROOT / "packages/reader-contracts"
SOURCE = CONTRACT_ROOT / "reader-safety-policy.json"
SCHEMA = CONTRACT_ROOT / "schemas/reader-safety-policy-v1.schema.json"
FIXTURES = CONTRACT_ROOT / "fixtures/reader-safety-v1/manifest.json"
FIXTURE_SCHEMA = CONTRACT_ROOT / "schemas/reader-safety-fixture-manifest-v1.schema.json"
NORMALIZATION_V3_ROOT = CONTRACT_ROOT / "fixtures/normalization-v3"
TS_TARGET = ROOT / "packages/reader-core/src/reader-safety-policy.generated.ts"
KT_TARGET = ROOT / (
    "apps/mobile/shared/src/commonMain/kotlin/com/ermao/library/shared/"
    "modules/reader/domain/ReaderSafetyPolicy.generated.kt"
)
PY_TARGET = ROOT / "apps/api-python/app/contracts/reader_safety_policy_generated.py"
C_TARGET = ROOT / (
    "apps/mobile/native/archive-core/include/reader_safety_policy.generated.h"
)

TOP_LEVEL_KEYS = {
    "$schema",
    "schemaVersion",
    "policyId",
    "policyVersion",
    "policyDigest",
    "consumers",
    "implementationFailureCodes",
    "formats",
    "budgets",
    "profiles",
    "rules",
    "platformDefenses",
}
ACTIONS = {"ALLOW", "SANITIZE", "BLOCK_RESOURCE", "REJECT_PUBLICATION"}
MORPHOLOGIES = {"REFLOWABLE", "PDF", "COMIC", "AUDIO"}
DELIVERY_MODES = {"DOWNLOAD_ORIGINAL", "STREAM", "PLAYER"}
LIFECYCLES = {"ACTIVE", "RECEIVE_ONLY"}
STAGES = {
    "ADMISSION",
    "PARSE",
    "SANITIZE",
    "RESOURCE",
    "RENDER",
    "DELIVERY",
    "PLAYBACK",
}
CONSUMERS = {"BACKEND", "WEB", "ANDROID", "IOS"}
FORMAT_ID = re.compile(r"[A-Z][A-Z0-9_]{1,31}\Z")
DEFENSE_ID = re.compile(r"[A-Z][A-Z0-9_]{2,95}\Z")
SYMBOL_ID = re.compile(r"[A-Z][A-Z0-9_.]{2,95}\Z")
ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,95}\Z")
MIME_TYPE = re.compile(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+\Z")


def canonical_json(value: object) -> str:
    """Return the one canonical representation used for the policy digest."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def policy_digest(value: object) -> str:
    """Hash canonical source semantics, excluding the self-referential digest."""

    digest_input = (
        {key: item for key, item in value.items() if key != "policyDigest"}
        if isinstance(value, Mapping)
        else value
    )
    return hashlib.sha256(canonical_json(digest_input).encode("utf-8")).hexdigest()


def require_string_list(
    value: object, *, field: str, allowed: set[str] | None = None
) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) for item in value)
    ):
        raise ValueError(f"{field} must be a nonempty string array")
    result = list(value)
    if len(set(result)) != len(result):
        raise ValueError(f"{field} contains duplicate values")
    if allowed is not None and not set(result) <= allowed:
        raise ValueError(f"{field} contains unsupported values")
    return result


def resolve_reference(policy: Mapping[str, object], reference: str) -> object:
    current: object = policy
    for segment in reference.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            raise ValueError(f"unknown policy parameter reference: {reference}")
        current = current[segment]
    return current


def validate_policy(value: object) -> dict[str, object]:
    """Apply semantic checks that JSON Schema alone cannot express."""

    if not isinstance(value, dict) or set(value) != TOP_LEVEL_KEYS:
        raise ValueError("Reader safety policy has unexpected top-level fields")
    if value["$schema"] != "./schemas/reader-safety-policy-v1.schema.json":
        raise ValueError("Reader safety policy must reference the v1 schema")
    if value["schemaVersion"] != 1:
        raise ValueError("Reader safety policy schema version must be 1")
    if type(value["policyVersion"]) is not int or value["policyVersion"] < 1:
        raise ValueError("Reader safety policy version must be a positive integer")
    if value["policyId"] != "shuku.reader-safety":
        raise ValueError("Reader safety policy id is invalid")
    consumers = require_string_list(
        value["consumers"], field="consumers", allowed=CONSUMERS
    )
    if set(consumers) != CONSUMERS:
        raise ValueError("Every first-party policy consumer must be declared")
    implementation_failure_codes = require_string_list(
        value["implementationFailureCodes"],
        field="implementationFailureCodes",
    )
    if set(implementation_failure_codes) != {
        "ENGINE_POLICY_ALGORITHM_UNSUPPORTED",
        "PLATFORM_POLICY_ALGORITHM_UNSUPPORTED",
    } or any(not ERROR_CODE.fullmatch(code) for code in implementation_failure_codes):
        raise ValueError("Reader safety implementation failure codes are incomplete")

    formats_value = value["formats"]
    if not isinstance(formats_value, list) or not formats_value:
        raise ValueError("formats must be a nonempty array")
    formats: set[str] = set()
    for index, entry in enumerate(formats_value):
        if not isinstance(entry, dict) or set(entry) != {
            "id",
            "morphology",
            "deliveryMode",
            "lifecycle",
            "extension",
            "canonicalMimeType",
            "acceptedMimeTypes",
            "requiredConsumers",
        }:
            raise ValueError(f"formats[{index}] has unexpected fields")
        format_id = entry["id"]
        if (
            not isinstance(format_id, str)
            or not FORMAT_ID.fullmatch(format_id)
            or format_id == "KINDLE"
        ):
            raise ValueError(f"formats[{index}].id is invalid")
        if format_id in formats:
            raise ValueError(f"duplicate format: {format_id}")
        formats.add(format_id)
        if entry["morphology"] not in MORPHOLOGIES:
            raise ValueError(f"invalid morphology for {format_id}")
        if (
            entry["deliveryMode"] not in DELIVERY_MODES
            or entry["lifecycle"] not in LIFECYCLES
        ):
            raise ValueError(f"invalid delivery/lifecycle for {format_id}")
        extension = entry["extension"]
        if extension is not None and (
            not isinstance(extension, str)
            or not re.fullmatch(r"\.[a-z0-9][a-z0-9._+-]{0,15}", extension)
        ):
            raise ValueError(f"invalid extension for {format_id}")
        accepted = entry["acceptedMimeTypes"]
        if (
            not isinstance(accepted, list)
            or any(
                not isinstance(mime, str) or not MIME_TYPE.fullmatch(mime)
                for mime in accepted
            )
            or len(set(accepted)) != len(accepted)
        ):
            raise ValueError(f"invalid MIME list for {format_id}")
        canonical = entry["canonicalMimeType"]
        if canonical is not None and (
            canonical not in accepted or not MIME_TYPE.fullmatch(canonical)
        ):
            raise ValueError(f"canonical MIME must be accepted for {format_id}")
        required = require_string_list(
            entry["requiredConsumers"],
            field=f"formats[{index}].requiredConsumers",
            allowed=CONSUMERS,
        )
        if entry["morphology"] != "AUDIO" and set(required) != CONSUMERS:
            raise ValueError(f"non-audio format {format_id} must cover all consumers")

    required_formats = {
        "EPUB",
        "FB2",
        "TXT",
        "MOBI",
        "AZW",
        "AZW3",
        "PRC",
        "PDF",
        "CBZ",
        "ZIP",
        "CBR",
        "RAR",
        "IMAGE_DIR",
        "AUDIO",
        "AUDIOBOOK_DIR",
    }
    if not required_formats <= formats or "KINDLE" in formats:
        raise ValueError("Reader safety format inventory is incomplete")

    budgets = value["budgets"]
    if not isinstance(budgets, dict) or not budgets:
        raise ValueError("budgets must be a nonempty object")
    for name, budget in budgets.items():
        if not isinstance(name, str) or not re.fullmatch(
            r"[a-z][A-Za-z0-9]{2,63}", name
        ):
            raise ValueError(f"invalid budget name: {name}")
        if type(budget) is not int or budget <= 0 or budget > 2**53 - 1:
            raise ValueError(f"invalid cross-language budget: {name}")
    if budgets.get("originalMaxBytes") != 2 * 1024**3:
        raise ValueError("the original admission boundary must be inclusive 2 GiB")
    if budgets.get("pdfRangeRequestMaxBytes", 0) % budgets.get("pdfRangeChunkBytes", 1):
        raise ValueError("PDF request budget must be an exact number of chunks")

    profiles = value["profiles"]
    if not isinstance(profiles, dict) or set(profiles) != {
        "reflowable",
        "pdf",
        "comic",
        "audio",
    }:
        raise ValueError("profiles must contain the four morphology profiles")
    pdf = profiles["pdf"]
    if not isinstance(pdf, dict) or set(pdf) != {
        "blockedActions",
        "requireFinitePageGeometry",
        "requireIdentityContentEncoding",
        "requireStrongRevision",
        "engineRequestLimit",
        "largeRequestAction",
        "allowWholeResponseFallback",
    }:
        raise ValueError("pdf profile has unexpected fields")
    if pdf["engineRequestLimit"] != "SOURCE_LENGTH":
        raise ValueError("PDF engine requests must be bounded by the source length")
    if pdf["largeRequestAction"] != "MATERIALIZE_VERIFIED_ORIGINAL":
        raise ValueError("large PDFium requests must materialize the verified original")

    audio = profiles["audio"]
    if not isinstance(audio, dict) or not isinstance(
        audio.get("containerMimeTypes"), dict
    ):
        raise TypeError("audio container MIME policy is missing")
    for extension, mime in audio["containerMimeTypes"].items():
        if (
            not isinstance(extension, str)
            or not extension.startswith(".")
            or not isinstance(mime, str)
            or not MIME_TYPE.fullmatch(mime)
        ):
            raise ValueError("invalid audio extension/MIME mapping")

    comic = profiles["comic"]
    if not isinstance(comic, dict):
        raise TypeError("comic profile is missing")
    allowed_page_mime_types = require_string_list(
        comic.get("allowedPageMimeTypes"),
        field="profiles.comic.allowedPageMimeTypes",
    )
    page_mime_types_by_extension = comic.get("pageMimeTypesByExtension")
    if (
        not isinstance(page_mime_types_by_extension, dict)
        or not page_mime_types_by_extension
    ):
        raise TypeError("comic extension/MIME policy is missing")
    for extension, mime in page_mime_types_by_extension.items():
        if (
            not isinstance(extension, str)
            or not re.fullmatch(r"\.[a-z0-9]+", extension)
            or not isinstance(mime, str)
            or not MIME_TYPE.fullmatch(mime)
        ):
            raise ValueError("invalid comic extension/MIME mapping")
    if set(page_mime_types_by_extension.values()) != set(allowed_page_mime_types):
        raise ValueError(
            "comic extension/MIME mappings must cover exactly the allowed page MIME types"
        )

    reflowable = profiles["reflowable"]
    if not isinstance(reflowable, dict):
        raise TypeError("reflowable profile is missing")
    named_entity_codepoints = reflowable.get("namedEntityCodepoints")
    if (
        not isinstance(named_entity_codepoints, dict)
        or len(named_entity_codepoints) != 253
        or named_entity_codepoints.get("nbsp") != 160
        or named_entity_codepoints.get("copy") != 169
        or named_entity_codepoints.get("apos") != 39
    ):
        raise ValueError("the complete XHTML named-entity table is required")
    for name, codepoint in named_entity_codepoints.items():
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]+", name)
            or type(codepoint) is not int
            or codepoint <= 0
            or codepoint > 0x10FFFF
        ):
            raise ValueError("invalid XHTML named-entity mapping")
    reading_order_markup_mime_types = require_string_list(
        reflowable.get("readingOrderMarkupMimeTypes"),
        field="profiles.reflowable.readingOrderMarkupMimeTypes",
    )
    if set(reading_order_markup_mime_types) != {
        "application/xhtml+xml",
        "text/html",
    } or any(not MIME_TYPE.fullmatch(mime) for mime in reading_order_markup_mime_types):
        raise ValueError("reading-order markup MIME policy is incomplete")
    embedded_image_extensions = reflowable.get("embeddedImageExtensionsByMimeType")
    if (
        not isinstance(embedded_image_extensions, dict)
        or set(embedded_image_extensions) != set(allowed_page_mime_types)
        or len(set(embedded_image_extensions.values()))
        != len(embedded_image_extensions)
    ):
        raise ValueError(
            "FB2 embedded-image MIME mappings must cover the generated image types"
        )
    for mime, extension in embedded_image_extensions.items():
        if (
            not isinstance(mime, str)
            or not MIME_TYPE.fullmatch(mime)
            or not isinstance(extension, str)
            or not re.fullmatch(r"\.[a-z0-9]+", extension)
        ):
            raise ValueError("invalid FB2 embedded-image MIME mapping")
    uri_attribute_policies = reflowable.get("uriAttributePolicies")
    if not isinstance(uri_attribute_policies, list) or not uri_attribute_policies:
        raise TypeError("reflowable URI attribute policy is missing")
    uri_attribute_policy_keys: set[tuple[tuple[str, ...], str, str, str]] = set()
    for index, uri_policy in enumerate(uri_attribute_policies):
        if not isinstance(uri_policy, dict) or set(uri_policy) != {
            "elements",
            "attribute",
            "syntax",
            "purpose",
        }:
            raise ValueError(
                f"profiles.reflowable.uriAttributePolicies[{index}] has unexpected fields"
            )
        elements = require_string_list(
            uri_policy["elements"],
            field=f"profiles.reflowable.uriAttributePolicies[{index}].elements",
        )
        attribute = uri_policy["attribute"]
        syntax = uri_policy["syntax"]
        purpose = uri_policy["purpose"]
        if not isinstance(attribute, str) or not re.fullmatch(
            r"[a-z][a-z0-9:-]*", attribute
        ):
            raise ValueError("invalid reflowable URI attribute name")
        if syntax not in {"SCALAR", "SRCSET", "SPACE_SEPARATED", "CSS"}:
            raise ValueError("invalid reflowable URI attribute syntax")
        if purpose not in {"SUBRESOURCE", "USER_NAVIGATION", "ALWAYS_REMOVE"}:
            raise ValueError("invalid reflowable URI attribute purpose")
        key = (tuple(elements), attribute, syntax, purpose)
        if key in uri_attribute_policy_keys:
            raise ValueError("duplicate reflowable URI attribute policy")
        uri_attribute_policy_keys.add(key)
    require_string_list(
        reflowable.get("cssTextElements"),
        field="profiles.reflowable.cssTextElements",
    )

    rules_value = value["rules"]
    if not isinstance(rules_value, list) or not rules_value:
        raise ValueError("rules must be a nonempty array")
    rules: set[str] = set()
    algorithms: set[str] = set()
    referenced_budgets: set[str] = set()
    for index, rule in enumerate(rules_value):
        if not isinstance(rule, dict) or set(rule) != {
            "id",
            "formats",
            "stage",
            "algorithm",
            "parameterRefs",
            "action",
            "errorCode",
            "requiredConsumers",
        }:
            raise ValueError(f"rules[{index}] has unexpected fields")
        rule_id = rule["id"]
        algorithm = rule["algorithm"]
        if (
            not isinstance(rule_id, str)
            or not SYMBOL_ID.fullmatch(rule_id)
            or rule_id in rules
        ):
            raise ValueError(f"invalid or duplicate rule id: {rule_id}")
        if not isinstance(algorithm, str) or not FORMAT_ID.fullmatch(algorithm):
            raise ValueError(f"invalid algorithm id for {rule_id}")
        rules.add(rule_id)
        algorithms.add(algorithm)
        require_string_list(
            rule["formats"], field=f"{rule_id}.formats", allowed=formats
        )
        require_string_list(
            rule["requiredConsumers"],
            field=f"{rule_id}.requiredConsumers",
            allowed=CONSUMERS,
        )
        if rule["stage"] not in STAGES or rule["action"] not in ACTIONS:
            raise ValueError(f"invalid stage/action for {rule_id}")
        error_code = rule["errorCode"]
        if error_code is not None and (
            not isinstance(error_code, str) or not ERROR_CODE.fullmatch(error_code)
        ):
            raise ValueError(f"invalid error code for {rule_id}")
        if (
            rule["action"] in {"REJECT_PUBLICATION", "BLOCK_RESOURCE"}
            and error_code is None
        ):
            raise ValueError(f"blocking rule {rule_id} requires an error code")
        if rule["action"] in {"ALLOW", "SANITIZE"} and error_code is not None:
            raise ValueError(f"nonblocking rule {rule_id} cannot expose an error code")
        parameter_refs = rule["parameterRefs"]
        if not isinstance(parameter_refs, list) or any(
            not isinstance(ref, str) for ref in parameter_refs
        ):
            raise ValueError(f"invalid parameter references for {rule_id}")
        for reference in parameter_refs:
            resolve_reference(value, reference)
            if reference.startswith("budgets."):
                referenced_budgets.add(reference.removeprefix("budgets."))
    if referenced_budgets != set(budgets):
        missing = sorted(set(budgets) - referenced_budgets)
        raise ValueError(
            f"every budget must be owned by a rule; unreferenced: {missing}"
        )

    defenses_value = value["platformDefenses"]
    if not isinstance(defenses_value, list) or not defenses_value:
        raise ValueError("platformDefenses must be a nonempty array")
    defenses: set[str] = set()
    for index, defense in enumerate(defenses_value):
        if not isinstance(defense, dict) or set(defense) != {
            "id",
            "formats",
            "stage",
            "requiredConsumers",
        }:
            raise ValueError(f"platformDefenses[{index}] has unexpected fields")
        defense_id = defense["id"]
        if (
            not isinstance(defense_id, str)
            or not DEFENSE_ID.fullmatch(defense_id)
            or defense_id in defenses
        ):
            raise ValueError(f"invalid or duplicate defense id: {defense_id}")
        defenses.add(defense_id)
        require_string_list(
            defense["formats"], field=f"{defense_id}.formats", allowed=formats
        )
        require_string_list(
            defense["requiredConsumers"],
            field=f"{defense_id}.requiredConsumers",
            allowed=CONSUMERS,
        )
        if defense["stage"] not in STAGES:
            raise ValueError(f"invalid defense stage for {defense_id}")

    required_rule_ids = {
        "REFLOWABLE.SAFE_STANDARD_DOCTYPE",
        "REFLOWABLE.REJECT_XML_ENTITY",
        "REFLOWABLE.SANITIZE_MARKUP",
        "REFLOWABLE.SANITIZE_URI",
        "REFLOWABLE.SANITIZE_CSS",
        "EPUB.ARCHIVE_STRUCTURE",
        "PDF.RANGE_PROTOCOL",
        "PDF.RENDER_BUDGET",
        "COMIC.MANIFEST_REVISION",
        "COMIC.PAGE_MIME",
        "AUDIO.CONTAINER_MIME",
        "AUDIO.TRACK_AND_CHAPTER_BOUNDS",
    }
    if not required_rule_ids <= rules:
        raise ValueError("required safety rules are missing")
    if value["policyDigest"] != policy_digest(value):
        raise ValueError("Reader safety policy digest is stale")
    return value


def validate_fixture_manifest(
    value: object, *, policy: Mapping[str, object], digest: str
) -> dict[str, object]:
    """Validate fixture identity and its binding to the exact policy revision."""

    if not isinstance(value, dict) or set(value) != {
        "$schema",
        "schemaVersion",
        "policyId",
        "policyVersion",
        "policyDigest",
        "cases",
    }:
        raise ValueError("Reader safety fixture manifest has unexpected fields")
    if (
        value["$schema"]
        != "../../schemas/reader-safety-fixture-manifest-v1.schema.json"
    ):
        raise ValueError("Reader safety fixture manifest must reference the v1 schema")
    if value["schemaVersion"] != 1:
        raise ValueError("Reader safety fixture manifest schema version is invalid")
    if (
        value["policyId"] != policy["policyId"]
        or value["policyVersion"] != policy["policyVersion"]
    ):
        raise ValueError("Reader safety fixtures target a different policy")
    if value["policyDigest"] != digest:
        raise ValueError("Reader safety fixture policy digest is stale")
    formats = {entry["id"] for entry in policy["formats"]}  # type: ignore[index]
    rules = {entry["id"]: entry for entry in policy["rules"]}  # type: ignore[index]
    cases = value["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("Reader safety fixture cases must be a nonempty array")
    case_ids: set[str] = set()
    covered_rules: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or set(case) != {
            "id",
            "format",
            "input",
            "inputSha256",
            "requiredConsumers",
            "expected",
        }:
            raise ValueError(f"fixture cases[{index}] has unexpected fields")
        case_id = case["id"]
        if (
            not isinstance(case_id, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,95}", case_id)
            or case_id in case_ids
        ):
            raise ValueError(f"invalid or duplicate fixture id: {case_id}")
        case_ids.add(case_id)
        if case["format"] not in formats or not isinstance(case["input"], str):
            raise ValueError(f"fixture {case_id} has an invalid format/input")
        input_digest = hashlib.sha256(case["input"].encode("utf-8")).hexdigest()
        if case["inputSha256"] != input_digest:
            raise ValueError(f"fixture {case_id} input hash is stale")
        consumers = require_string_list(
            case["requiredConsumers"],
            field=f"fixture {case_id}.requiredConsumers",
            allowed=CONSUMERS,
        )
        expected = case["expected"]
        if not isinstance(expected, dict) or set(expected) != {
            "triggered",
            "action",
            "terminalRuleId",
            "errorCode",
            "orderedRuleEvents",
            "semanticProjection",
            "semanticProjectionSha256",
        }:
            raise ValueError(f"fixture {case_id} expected result has unexpected fields")
        rule = rules.get(expected["terminalRuleId"])
        if rule is None or case["format"] not in rule["formats"]:
            raise ValueError(f"fixture {case_id} targets an inapplicable rule")
        covered_rules.add(rule["id"])
        if consumers != rule["requiredConsumers"]:
            raise ValueError(
                f"fixture {case_id} must preserve the exact consumer obligations "
                f"of {rule['id']}"
            )
        if type(expected["triggered"]) is not bool or expected["action"] not in ACTIONS:
            raise ValueError(f"fixture {case_id} has an invalid verdict")
        if expected["triggered"]:
            if (
                expected["action"] != rule["action"]
                or expected["errorCode"] != rule["errorCode"]
            ):
                raise ValueError(f"fixture {case_id} disagrees with its triggered rule")
        elif expected["action"] != "ALLOW" or expected["errorCode"] is not None:
            raise ValueError(f"fixture {case_id} non-triggered boundary must allow")
        events = expected["orderedRuleEvents"]
        if (
            not isinstance(events, list)
            or not events
            or any(
                not isinstance(event, str) or not event.startswith(f"{rule['id']}:")
                for event in events
            )
        ):
            raise ValueError(f"fixture {case_id} has invalid ordered rule events")
        projection = expected["semanticProjection"]
        projection_digest = expected["semanticProjectionSha256"]
        if projection is None:
            if projection_digest is not None:
                raise ValueError(f"fixture {case_id} has a digest without a projection")
        elif (
            not isinstance(projection, str)
            or projection_digest
            != hashlib.sha256(projection.encode("utf-8")).hexdigest()
        ):
            raise ValueError(f"fixture {case_id} semantic projection hash is stale")
    required_fixture_rules = set(rules)
    if covered_rules != required_fixture_rules:
        missing = sorted(required_fixture_rules - covered_rules)
        extra = sorted(covered_rules - required_fixture_rules)
        raise ValueError(
            "Reader safety fixtures must cover every policy rule; "
            f"missing={missing}, extra={extra}"
        )
    return value


def validate_normalization_v3_fixture(
    *, policy: Mapping[str, object], digest: str
) -> None:
    """Protect the first policy-sanitized exact-location projection golden."""

    projection_path = NORMALIZATION_V3_ROOT / "projection.json"
    digest_path = NORMALIZATION_V3_ROOT / "projection.sha256"
    chapter_path = NORMALIZATION_V3_ROOT / "chapter.xhtml"
    if (
        not projection_path.exists()
        or not digest_path.exists()
        or not chapter_path.exists()
    ):
        raise ValueError("Reader safety normalization-v3 fixture is incomplete")
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    projection_digest = (
        "sha256:"
        + hashlib.sha256(canonical_json(projection).encode("utf-8")).hexdigest()
    )
    if projection_digest != digest_path.read_text(encoding="utf-8").strip():
        raise ValueError("Reader safety normalization-v3 projection hash is stale")
    if (
        projection.get("schemaVersion") != 3
        or projection.get("normalization") != "shuku-epub-locator-dom-v3"
        or projection.get("policyId") != policy["policyId"]
        or projection.get("policyVersion") != policy["policyVersion"]
        or projection.get("policyDigest") != digest
    ):
        raise ValueError(
            "Reader safety normalization-v3 projection targets stale policy"
        )
    elements = [
        element
        for resource in projection.get("readingOrder", [])
        for element in resource.get("elements", [])
    ]
    forbidden = set(policy["profiles"]["reflowable"]["sanitizedElements"])  # type: ignore[index]
    forbidden.update(policy["profiles"]["reflowable"]["svgSanitizedElements"])  # type: ignore[index]
    if any(element.get("localName") in forbidden for element in elements):
        raise ValueError(
            "Reader safety normalization-v3 projection retains active content"
        )
    chapter = chapter_path.read_text(encoding="utf-8")
    if "<!DOCTYPE html PUBLIC" not in chapter or not any(
        f'PUBLIC "{doctype["publicId"]}" "{doctype["systemId"]}"' in chapter
        for doctype in policy["profiles"]["reflowable"]["safeDoctypes"]  # type: ignore[index]
    ):
        raise ValueError("Reader safety normalization-v3 source lacks a safe DOCTYPE")


def enum_symbol(value: str) -> str:
    with_word_boundaries = (
        re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
        if value != value.upper()
        else value
    )
    return re.sub(r"[^A-Z0-9]+", "_", with_word_boundaries.upper()).strip("_")


def ts_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def render_typescript(policy: Mapping[str, object], digest: str) -> str:
    formats = {entry["id"]: entry for entry in policy["formats"]}  # type: ignore[index]
    rules = {entry["id"]: entry for entry in policy["rules"]}  # type: ignore[index]
    defenses = {entry["id"]: entry for entry in policy["platformDefenses"]}  # type: ignore[index]
    rule_ids = {enum_symbol(rule_id): rule_id for rule_id in rules}
    algorithms = sorted({entry["algorithm"] for entry in rules.values()})
    implementation_failure_codes = list(policy["implementationFailureCodes"])
    error_codes = sorted(
        {entry["errorCode"] for entry in rules.values() if entry["errorCode"]}
        | set(implementation_failure_codes)
    )
    return f"""// Generated by packages/reader-contracts/generate-reader-safety-policy.py. Do not edit.
export const READER_SAFETY_POLICY_SCHEMA_VERSION = {policy["schemaVersion"]} as const;
export const READER_SAFETY_POLICY_VERSION = {policy["policyVersion"]} as const;
export const READER_SAFETY_POLICY_ID = {json.dumps(policy["policyId"])} as const;
export const READER_SAFETY_POLICY_DIGEST = {json.dumps(digest)} as const;

export const READER_SAFETY_ACTIONS = {ts_json(sorted(ACTIONS))} as const;
export type ReaderSafetyAction = typeof READER_SAFETY_ACTIONS[number];
export const READER_SAFETY_ALGORITHM_IDS = {ts_json(algorithms)} as const;
export type ReaderSafetyAlgorithmId = typeof READER_SAFETY_ALGORITHM_IDS[number];
export const READER_SAFETY_ERROR_CODES = {ts_json(error_codes)} as const;
export type ReaderSafetyErrorCode = typeof READER_SAFETY_ERROR_CODES[number];
export const READER_SAFETY_IMPLEMENTATION_FAILURE_CODES = {ts_json(implementation_failure_codes)} as const;
export type ReaderSafetyImplementationFailureCode = typeof READER_SAFETY_IMPLEMENTATION_FAILURE_CODES[number];
export type ReaderSafetyConsumer = 'BACKEND' | 'WEB' | 'ANDROID' | 'IOS';
export type ReaderSafetyStage = 'ADMISSION' | 'PARSE' | 'SANITIZE' | 'RESOURCE' | 'RENDER' | 'DELIVERY' | 'PLAYBACK';
export type ReaderSafetyMorphology = 'REFLOWABLE' | 'PDF' | 'COMIC' | 'AUDIO';
export type ReaderSafetyDeliveryMode = 'DOWNLOAD_ORIGINAL' | 'STREAM' | 'PLAYER';
export type ReaderSafetyFormatLifecycle = 'ACTIVE' | 'RECEIVE_ONLY';

export const READER_SAFETY_FORMATS = {ts_json(formats)} as const;
export type ReaderSafetyFormat = keyof typeof READER_SAFETY_FORMATS;
export type ReaderSafetyFormatDefinition = typeof READER_SAFETY_FORMATS[ReaderSafetyFormat];

export const READER_SAFETY_BUDGETS = {ts_json(policy["budgets"])} as const;
export type ReaderSafetyBudgetName = keyof typeof READER_SAFETY_BUDGETS;
export const READER_SAFETY_PROFILES = {ts_json(policy["profiles"])} as const;

export const READER_SAFETY_RULE_IDS = {ts_json(rule_ids)} as const;
export type ReaderSafetyRuleId = typeof READER_SAFETY_RULE_IDS[keyof typeof READER_SAFETY_RULE_IDS];
export const READER_SAFETY_RULES = {ts_json(rules)} as const;
export type ReaderSafetyRule = typeof READER_SAFETY_RULES[ReaderSafetyRuleId];

export const READER_SAFETY_PLATFORM_DEFENSES = {ts_json(defenses)} as const;
export type ReaderSafetyPlatformDefenseId = keyof typeof READER_SAFETY_PLATFORM_DEFENSES;
export type ReaderSafetyPlatformDefense = typeof READER_SAFETY_PLATFORM_DEFENSES[ReaderSafetyPlatformDefenseId];

export function readerSafetyFormatPolicy(value: string): ReaderSafetyFormatDefinition | null {{
  const normalized = value.trim().toUpperCase();
  return Object.prototype.hasOwnProperty.call(READER_SAFETY_FORMATS, normalized)
    ? READER_SAFETY_FORMATS[normalized as ReaderSafetyFormat]
    : null;
}}

export function requireReaderSafetyFormatPolicy(value: string): ReaderSafetyFormatDefinition {{
  const policy = readerSafetyFormatPolicy(value);
  if (!policy) throw new Error(`Unsupported Reader safety format: ${{value}}`);
  return policy;
}}

export function readerSafetyAcceptsMimeType(format: ReaderSafetyFormatDefinition, value: string): boolean {{
  const normalized = value.trim().toLowerCase().split(';', 1)[0] ?? '';
  return (format.acceptedMimeTypes as readonly string[]).includes(normalized);
}}

export function readerSafetyBudget(name: ReaderSafetyBudgetName): number {{
  return READER_SAFETY_BUDGETS[name];
}}

export function readerSafetyRule(ruleId: ReaderSafetyRuleId): ReaderSafetyRule {{
  return READER_SAFETY_RULES[ruleId];
}}

export function readerSafetyComicPageMimeType(extension: string): string | null {{
  const normalized = extension.trim().toLowerCase();
  const mapping = READER_SAFETY_PROFILES.comic.pageMimeTypesByExtension;
  return Object.prototype.hasOwnProperty.call(mapping, normalized)
    ? mapping[normalized as keyof typeof mapping]
    : null;
}}
"""


def kotlin_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def kotlin_list(values: Sequence[str], *, transform: str | None = None) -> str:
    rendered = []
    for value in values:
        rendered.append(
            f"{transform}.{enum_symbol(value)}" if transform else kotlin_string(value)
        )
    return f"listOf({', '.join(rendered)})"


def kotlin_nullable_string(value: object) -> str:
    return "null" if value is None else kotlin_string(str(value))


def render_kotlin(policy: Mapping[str, object], digest: str) -> str:
    formats = list(policy["formats"])  # type: ignore[arg-type]
    rules = list(policy["rules"])  # type: ignore[arg-type]
    defenses = list(policy["platformDefenses"])  # type: ignore[arg-type]
    budgets = policy["budgets"]  # type: ignore[assignment]
    profiles = policy["profiles"]  # type: ignore[assignment]
    algorithms = sorted({entry["algorithm"] for entry in rules})
    implementation_failure_codes = list(policy["implementationFailureCodes"])
    error_codes = sorted(
        {entry["errorCode"] for entry in rules if entry["errorCode"]}
        | set(implementation_failure_codes)
    )
    lines = [
        "// Generated by packages/reader-contracts/generate-reader-safety-policy.py. Do not edit.",
        "package com.ermao.library.shared.modules.reader.domain",
        "",
        "enum class ReaderSafetyAction { " + ", ".join(sorted(ACTIONS)) + " }",
        "enum class ReaderSafetyAlgorithmId { " + ", ".join(algorithms) + " }",
        "enum class ReaderSafetyErrorCode { " + ", ".join(error_codes) + " }",
        "enum class ReaderSafetyConsumer { BACKEND, WEB, ANDROID, IOS }",
        "enum class ReaderSafetyStage { ADMISSION, PARSE, SANITIZE, RESOURCE, RENDER, DELIVERY, PLAYBACK }",
        "enum class ReaderSafetyMorphology { REFLOWABLE, PDF, COMIC, AUDIO }",
        "enum class ReaderSafetyDeliveryMode { DOWNLOAD_ORIGINAL, STREAM, PLAYER }",
        "enum class ReaderSafetyFormatLifecycle { ACTIVE, RECEIVE_ONLY }",
        "enum class ReaderSafetyUriSyntax { SCALAR, SRCSET, SPACE_SEPARATED, CSS }",
        "enum class ReaderSafetyUriPurpose { SUBRESOURCE, USER_NAVIGATION, ALWAYS_REMOVE }",
        "enum class ReaderSafetyFormat { "
        + ", ".join(enum_symbol(entry["id"]) for entry in formats)
        + " }",
        "enum class ReaderSafetyBudgetName(val wireValue: String) {",
    ]
    for name in budgets:
        lines.append(f"    {enum_symbol(name)}({kotlin_string(name)}),")
    lines += ["}", "enum class ReaderSafetyRuleId(val wireValue: String) {"]
    for rule in rules:
        lines.append(f"    {enum_symbol(rule['id'])}({kotlin_string(rule['id'])}),")
    lines += [
        "}",
        "enum class ReaderSafetyPlatformDefenseId { "
        + ", ".join(entry["id"] for entry in defenses)
        + " }",
        "",
    ]
    lines += [
        "data class ReaderSafetyFormatDefinition(",
        "    val id: ReaderSafetyFormat, val morphology: ReaderSafetyMorphology,",
        "    val deliveryMode: ReaderSafetyDeliveryMode, val lifecycle: ReaderSafetyFormatLifecycle,",
        "    val extension: String?, val canonicalMimeType: String?, val acceptedMimeTypes: List<String>,",
        "    val requiredConsumers: List<ReaderSafetyConsumer>,",
        ")",
        "data class ReaderSafetyRule(",
        "    val id: ReaderSafetyRuleId, val formats: List<ReaderSafetyFormat>, val stage: ReaderSafetyStage,",
        "    val algorithm: ReaderSafetyAlgorithmId, val parameterRefs: List<String>,",
        "    val action: ReaderSafetyAction, val errorCode: ReaderSafetyErrorCode?,",
        "    val requiredConsumers: List<ReaderSafetyConsumer>,",
        ")",
        "data class ReaderSafetyPlatformDefense(",
        "    val id: ReaderSafetyPlatformDefenseId, val formats: List<ReaderSafetyFormat>,",
        "    val stage: ReaderSafetyStage, val requiredConsumers: List<ReaderSafetyConsumer>,",
        ")",
        "data class ReaderSafetyDoctype(val name: String, val publicId: String, val systemId: String)",
        "data class ReaderSafetyUriAttributePolicy(",
        "    val elements: List<String>, val attribute: String, val syntax: ReaderSafetyUriSyntax,",
        "    val purpose: ReaderSafetyUriPurpose,",
        ")",
        "data class ReaderSafetyReflowableProfile(",
        "    val safeDoctypes: List<ReaderSafetyDoctype>, val externalDtdResolution: Boolean,",
        "    val rejectInternalSubset: Boolean, val rejectCustomEntities: Boolean,",
        "    val namedEntityCodepoints: Map<String, Int>,",
        "    val readingOrderMarkupMimeTypes: List<String>,",
        "    val embeddedImageExtensionsByMimeType: Map<String, String>,",
        "    val sanitizedElements: List<String>, val sanitizedAttributes: List<String>,",
        "    val sanitizedAttributePrefixes: List<String>, val sanitizedMetaHttpEquivValues: List<String>,",
        "    val blockedAuthorSchemes: List<String>, val remoteSubresourceSchemes: List<String>,",
        "    val userNavigationSchemes: List<String>, val trustedRuntimeSchemes: List<String>,",
        "    val uriAttributePolicies: List<ReaderSafetyUriAttributePolicy>,",
        "    val allowedFontObfuscationAlgorithms: List<String>,",
        "    val svgSanitizedElements: List<String>, val cssTextElements: List<String>,",
        "    val cssSanitizedConstructs: List<String>,",
        "    val archiveFatalFindings: List<String>,",
        ")",
        "data class ReaderSafetyPdfProfile(",
        "    val blockedActions: List<String>, val requireFinitePageGeometry: Boolean,",
        "    val requireIdentityContentEncoding: Boolean, val requireStrongRevision: Boolean,",
        "    val engineRequestLimit: String, val largeRequestAction: String,",
        "    val allowWholeResponseFallback: Boolean,",
        ")",
        "data class ReaderSafetyComicProfile(",
        "    val allowedPageMimeTypes: List<String>, val pageMimeTypesByExtension: Map<String, String>,",
        "    val archiveFatalFindings: List<String>,",
        "    val singlePageDecodeFailureAction: ReaderSafetyAction, val manifestRevisionRequired: Boolean,",
        ")",
        "data class ReaderSafetyAudioProfile(",
        "    val containerMimeTypes: Map<String, String>, val codecDecision: String,",
        "    val blockedRedirectSchemes: List<String>, val requireFiniteNonNegativeDuration: Boolean,",
        "    val requireOrderedTrackIdentity: Boolean,",
        ")",
        "",
        "object ReaderSafetyPolicy {",
        f"    const val schemaVersion: Int = {policy['schemaVersion']}",
        f"    const val policyVersion: Int = {policy['policyVersion']}",
        f"    const val policyId: String = {kotlin_string(str(policy['policyId']))}",
        f"    const val policyDigest: String = {kotlin_string(digest)}",
        "",
        "    val implementationFailureCodes: List<ReaderSafetyErrorCode> = "
        + kotlin_list(implementation_failure_codes, transform="ReaderSafetyErrorCode"),
        "",
        "    val formats: Map<ReaderSafetyFormat, ReaderSafetyFormatDefinition> = listOf(",
    ]
    for entry in formats:
        lines.append(
            "        ReaderSafetyFormatDefinition(ReaderSafetyFormat."
            + enum_symbol(entry["id"])
            + ", ReaderSafetyMorphology."
            + entry["morphology"]
            + ", ReaderSafetyDeliveryMode."
            + entry["deliveryMode"]
            + ", ReaderSafetyFormatLifecycle."
            + entry["lifecycle"]
            + ", "
            + kotlin_nullable_string(entry["extension"])
            + ", "
            + kotlin_nullable_string(entry["canonicalMimeType"])
            + ", "
            + kotlin_list(entry["acceptedMimeTypes"])
            + ", "
            + kotlin_list(entry["requiredConsumers"], transform="ReaderSafetyConsumer")
            + "),"
        )
    lines += [
        "    ).associateBy(ReaderSafetyFormatDefinition::id)",
        "",
        "    val budgets: Map<ReaderSafetyBudgetName, Long> = mapOf(",
    ]
    for name, amount in budgets.items():
        lines.append(
            f"        ReaderSafetyBudgetName.{enum_symbol(name)} to {amount}L,"
        )
    lines += [
        "    )",
        "",
        "    val rules: Map<ReaderSafetyRuleId, ReaderSafetyRule> = listOf(",
    ]
    for rule in rules:
        error = (
            "null"
            if rule["errorCode"] is None
            else f"ReaderSafetyErrorCode.{rule['errorCode']}"
        )
        lines.append(
            f"        ReaderSafetyRule(ReaderSafetyRuleId.{enum_symbol(rule['id'])}, "
            + kotlin_list(rule["formats"], transform="ReaderSafetyFormat")
            + f", ReaderSafetyStage.{rule['stage']}, ReaderSafetyAlgorithmId.{rule['algorithm']}, "
            + kotlin_list(rule["parameterRefs"])
            + f", ReaderSafetyAction.{rule['action']}, {error}, "
            + kotlin_list(rule["requiredConsumers"], transform="ReaderSafetyConsumer")
            + "),"
        )
    lines += [
        "    ).associateBy(ReaderSafetyRule::id)",
        "",
        "    val platformDefenses: Map<ReaderSafetyPlatformDefenseId, ReaderSafetyPlatformDefense> = listOf(",
    ]
    for defense in defenses:
        lines.append(
            f"        ReaderSafetyPlatformDefense(ReaderSafetyPlatformDefenseId.{defense['id']}, "
            + kotlin_list(defense["formats"], transform="ReaderSafetyFormat")
            + f", ReaderSafetyStage.{defense['stage']}, "
            + kotlin_list(
                defense["requiredConsumers"], transform="ReaderSafetyConsumer"
            )
            + "),"
        )
    reflow = profiles["reflowable"]
    pdf = profiles["pdf"]
    comic = profiles["comic"]
    audio = profiles["audio"]
    lines += [
        "    ).associateBy(ReaderSafetyPlatformDefense::id)",
        "",
        "    val reflowableProfile = ReaderSafetyReflowableProfile(",
        "        safeDoctypes = listOf(",
    ]
    for item in reflow["safeDoctypes"]:
        lines.append(
            f"            ReaderSafetyDoctype({kotlin_string(item['name'])}, {kotlin_string(item['publicId'])}, {kotlin_string(item['systemId'])}),"
        )
    lines += [
        "        ),",
        f"        externalDtdResolution = {str(reflow['externalDtdResolution']).lower()},",
        f"        rejectInternalSubset = {str(reflow['rejectInternalSubset']).lower()},",
        f"        rejectCustomEntities = {str(reflow['rejectCustomEntities']).lower()},",
        "        namedEntityCodepoints = mapOf(",
    ]
    for name, codepoint in reflow["namedEntityCodepoints"].items():
        lines.append(f"            {kotlin_string(name)} to {codepoint},")
    lines += [
        "        ),",
        f"        readingOrderMarkupMimeTypes = {kotlin_list(reflow['readingOrderMarkupMimeTypes'])},",
        "        embeddedImageExtensionsByMimeType = mapOf(",
    ]
    for mime, extension in reflow["embeddedImageExtensionsByMimeType"].items():
        lines.append(
            f"            {kotlin_string(mime)} to {kotlin_string(extension)},"
        )
    lines += [
        "        ),",
    ]
    for field in [
        "sanitizedElements",
        "sanitizedAttributes",
        "sanitizedAttributePrefixes",
        "sanitizedMetaHttpEquivValues",
        "blockedAuthorSchemes",
        "remoteSubresourceSchemes",
        "userNavigationSchemes",
        "trustedRuntimeSchemes",
        "allowedFontObfuscationAlgorithms",
        "svgSanitizedElements",
        "cssTextElements",
        "cssSanitizedConstructs",
        "archiveFatalFindings",
    ]:
        lines.append(f"        {field} = {kotlin_list(reflow[field])},")
    lines += [
        "        uriAttributePolicies = listOf(",
    ]
    for uri_policy in reflow["uriAttributePolicies"]:
        lines.append(
            "            ReaderSafetyUriAttributePolicy("
            + kotlin_list(uri_policy["elements"])
            + f", {kotlin_string(uri_policy['attribute'])}, "
            + f"ReaderSafetyUriSyntax.{uri_policy['syntax']}, "
            + f"ReaderSafetyUriPurpose.{uri_policy['purpose']}),"
        )
    lines += [
        "        ),",
        "    )",
        "    val pdfProfile = ReaderSafetyPdfProfile(",
        f"        blockedActions = {kotlin_list(pdf['blockedActions'])},",
        f"        requireFinitePageGeometry = {str(pdf['requireFinitePageGeometry']).lower()},",
        f"        requireIdentityContentEncoding = {str(pdf['requireIdentityContentEncoding']).lower()},",
        f"        requireStrongRevision = {str(pdf['requireStrongRevision']).lower()},",
        f"        engineRequestLimit = {kotlin_string(pdf['engineRequestLimit'])},",
        f"        largeRequestAction = {kotlin_string(pdf['largeRequestAction'])},",
        f"        allowWholeResponseFallback = {str(pdf['allowWholeResponseFallback']).lower()},",
        "    )",
        "    val comicProfile = ReaderSafetyComicProfile(",
        f"        allowedPageMimeTypes = {kotlin_list(comic['allowedPageMimeTypes'])},",
        "        pageMimeTypesByExtension = mapOf(",
    ]
    for extension, mime in comic["pageMimeTypesByExtension"].items():
        lines.append(
            f"            {kotlin_string(extension)} to {kotlin_string(mime)},"
        )
    lines += [
        "        ),",
        f"        archiveFatalFindings = {kotlin_list(comic['archiveFatalFindings'])},",
        f"        singlePageDecodeFailureAction = ReaderSafetyAction.{comic['singlePageDecodeFailureAction']},",
        f"        manifestRevisionRequired = {str(comic['manifestRevisionRequired']).lower()},",
        "    )",
        "    val audioProfile = ReaderSafetyAudioProfile(",
        "        containerMimeTypes = mapOf(",
    ]
    for extension, mime in audio["containerMimeTypes"].items():
        lines.append(
            f"            {kotlin_string(extension)} to {kotlin_string(mime)},"
        )
    lines += [
        "        ),",
        f"        codecDecision = {kotlin_string(audio['codecDecision'])},",
        f"        blockedRedirectSchemes = {kotlin_list(audio['blockedRedirectSchemes'])},",
        f"        requireFiniteNonNegativeDuration = {str(audio['requireFiniteNonNegativeDuration']).lower()},",
        f"        requireOrderedTrackIdentity = {str(audio['requireOrderedTrackIdentity']).lower()},",
        "    )",
        "",
        "    fun formatPolicy(value: String): ReaderSafetyFormatDefinition? =",
        "        ReaderSafetyFormat.entries.firstOrNull { it.name == value.trim().uppercase() }?.let(formats::get)",
        "    fun requireFormatPolicy(value: String): ReaderSafetyFormatDefinition =",
        '        requireNotNull(formatPolicy(value)) { "Unsupported Reader safety format: $value" }',
        "    fun budget(name: ReaderSafetyBudgetName): Long = requireNotNull(budgets[name])",
        "    fun rule(id: ReaderSafetyRuleId): ReaderSafetyRule = requireNotNull(rules[id])",
        "    fun comicPageMimeType(extension: String): String? =",
        "        comicProfile.pageMimeTypesByExtension[extension.trim().lowercase()]",
        "    fun fb2EmbeddedImageExtension(mediaType: String): String? =",
        "        reflowableProfile.embeddedImageExtensionsByMimeType[mediaType.trim().lowercase()]",
        "}",
        "",
    ]
    return "\n".join(lines)


def py_string(value: str) -> str:
    return repr(value)


def py_tuple(values: Sequence[str], *, transform: str | None = None) -> str:
    rendered = [
        f"{transform}.{enum_symbol(value)}" if transform else py_string(value)
        for value in values
    ]
    if len(rendered) == 1:
        return f"({rendered[0]},)"
    return f"({', '.join(rendered)})"


def render_python(policy: Mapping[str, object], digest: str) -> str:
    formats = list(policy["formats"])  # type: ignore[arg-type]
    rules = list(policy["rules"])  # type: ignore[arg-type]
    defenses = list(policy["platformDefenses"])  # type: ignore[arg-type]
    budgets = policy["budgets"]  # type: ignore[assignment]
    profiles = policy["profiles"]  # type: ignore[assignment]
    algorithms = sorted({entry["algorithm"] for entry in rules})
    implementation_failure_codes = list(policy["implementationFailureCodes"])
    error_codes = sorted(
        {entry["errorCode"] for entry in rules if entry["errorCode"]}
        | set(implementation_failure_codes)
    )
    lines = [
        '"""Generated Reader safety policy. Do not edit by hand."""',
        "# fmt: off",
        "# Generated layout is contract-digest checked; do not reformat.",
        "",
        "from __future__ import annotations",
        "",
        "from collections.abc import Mapping",
        "from dataclasses import dataclass",
        "from enum import StrEnum",
        "from types import MappingProxyType",
        "from typing import Final",
        "",
        "",
    ]
    enum_groups = [
        ("ReaderSafetyAction", sorted(ACTIONS)),
        ("ReaderSafetyAlgorithmId", algorithms),
        ("ReaderSafetyErrorCode", error_codes),
        ("ReaderSafetyConsumer", ["BACKEND", "WEB", "ANDROID", "IOS"]),
        (
            "ReaderSafetyStage",
            [
                "ADMISSION",
                "PARSE",
                "SANITIZE",
                "RESOURCE",
                "RENDER",
                "DELIVERY",
                "PLAYBACK",
            ],
        ),
        ("ReaderSafetyMorphology", ["REFLOWABLE", "PDF", "COMIC", "AUDIO"]),
        ("ReaderSafetyDeliveryMode", ["DOWNLOAD_ORIGINAL", "STREAM", "PLAYER"]),
        ("ReaderSafetyFormatLifecycle", ["ACTIVE", "RECEIVE_ONLY"]),
        (
            "ReaderSafetyUriSyntax",
            ["SCALAR", "SRCSET", "SPACE_SEPARATED", "CSS"],
        ),
        (
            "ReaderSafetyUriPurpose",
            ["SUBRESOURCE", "USER_NAVIGATION", "ALWAYS_REMOVE"],
        ),
        ("ReaderSafetyFormat", [entry["id"] for entry in formats]),
    ]
    for name, values in enum_groups:
        lines.append(f"class {name}(StrEnum):")
        lines.extend(
            f"    {enum_symbol(value)} = {py_string(value)}" for value in values
        )
        lines.append("")
    lines.append("class ReaderSafetyBudgetName(StrEnum):")
    lines.extend(f"    {enum_symbol(name)} = {py_string(name)}" for name in budgets)
    lines += ["", "class ReaderSafetyRuleId(StrEnum):"]
    lines.extend(
        f"    {enum_symbol(rule['id'])} = {py_string(rule['id'])}" for rule in rules
    )
    lines += ["", "class ReaderSafetyPlatformDefenseId(StrEnum):"]
    lines.extend(
        f"    {defense['id']} = {py_string(defense['id'])}" for defense in defenses
    )
    lines += [
        "",
        "@dataclass(frozen=True, slots=True)",
        "class ReaderSafetyFormatDefinition:",
        "    id: ReaderSafetyFormat",
        "    morphology: ReaderSafetyMorphology",
        "    delivery_mode: ReaderSafetyDeliveryMode",
        "    lifecycle: ReaderSafetyFormatLifecycle",
        "    extension: str | None",
        "    canonical_mime_type: str | None",
        "    accepted_mime_types: tuple[str, ...]",
        "    required_consumers: tuple[ReaderSafetyConsumer, ...]",
        "",
        "@dataclass(frozen=True, slots=True)",
        "class ReaderSafetyRule:",
        "    id: ReaderSafetyRuleId",
        "    formats: tuple[ReaderSafetyFormat, ...]",
        "    stage: ReaderSafetyStage",
        "    algorithm: ReaderSafetyAlgorithmId",
        "    parameter_refs: tuple[str, ...]",
        "    action: ReaderSafetyAction",
        "    error_code: ReaderSafetyErrorCode | None",
        "    required_consumers: tuple[ReaderSafetyConsumer, ...]",
        "",
        "@dataclass(frozen=True, slots=True)",
        "class ReaderSafetyPlatformDefense:",
        "    id: ReaderSafetyPlatformDefenseId",
        "    formats: tuple[ReaderSafetyFormat, ...]",
        "    stage: ReaderSafetyStage",
        "    required_consumers: tuple[ReaderSafetyConsumer, ...]",
        "",
        "@dataclass(frozen=True, slots=True)",
        "class ReaderSafetyDoctype:",
        "    name: str",
        "    public_id: str",
        "    system_id: str",
        "",
        "@dataclass(frozen=True, slots=True)",
        "class ReaderSafetyUriAttributePolicy:",
        "    elements: tuple[str, ...]",
        "    attribute: str",
        "    syntax: ReaderSafetyUriSyntax",
        "    purpose: ReaderSafetyUriPurpose",
        "",
        "@dataclass(frozen=True, slots=True)",
        "class ReaderSafetyReflowableProfile:",
        "    safe_doctypes: tuple[ReaderSafetyDoctype, ...]",
        "    external_dtd_resolution: bool",
        "    reject_internal_subset: bool",
        "    reject_custom_entities: bool",
        "    named_entity_codepoints: Mapping[str, int]",
        "    reading_order_markup_mime_types: tuple[str, ...]",
        "    embedded_image_extensions_by_mime_type: Mapping[str, str]",
        "    sanitized_elements: tuple[str, ...]",
        "    sanitized_attributes: tuple[str, ...]",
        "    sanitized_attribute_prefixes: tuple[str, ...]",
        "    sanitized_meta_http_equiv_values: tuple[str, ...]",
        "    blocked_author_schemes: tuple[str, ...]",
        "    remote_subresource_schemes: tuple[str, ...]",
        "    user_navigation_schemes: tuple[str, ...]",
        "    trusted_runtime_schemes: tuple[str, ...]",
        "    uri_attribute_policies: tuple[ReaderSafetyUriAttributePolicy, ...]",
        "    allowed_font_obfuscation_algorithms: tuple[str, ...]",
        "    svg_sanitized_elements: tuple[str, ...]",
        "    css_text_elements: tuple[str, ...]",
        "    css_sanitized_constructs: tuple[str, ...]",
        "    archive_fatal_findings: tuple[str, ...]",
        "",
        "@dataclass(frozen=True, slots=True)",
        "class ReaderSafetyPdfProfile:",
        "    blocked_actions: tuple[str, ...]",
        "    require_finite_page_geometry: bool",
        "    require_identity_content_encoding: bool",
        "    require_strong_revision: bool",
        "    engine_request_limit: str",
        "    large_request_action: str",
        "    allow_whole_response_fallback: bool",
        "",
        "@dataclass(frozen=True, slots=True)",
        "class ReaderSafetyComicProfile:",
        "    allowed_page_mime_types: tuple[str, ...]",
        "    page_mime_types_by_extension: Mapping[str, str]",
        "    archive_fatal_findings: tuple[str, ...]",
        "    single_page_decode_failure_action: ReaderSafetyAction",
        "    manifest_revision_required: bool",
        "",
        "@dataclass(frozen=True, slots=True)",
        "class ReaderSafetyAudioProfile:",
        "    container_mime_types: Mapping[str, str]",
        "    codec_decision: str",
        "    blocked_redirect_schemes: tuple[str, ...]",
        "    require_finite_non_negative_duration: bool",
        "    require_ordered_track_identity: bool",
        "",
        f"READER_SAFETY_POLICY_SCHEMA_VERSION: Final = {policy['schemaVersion']}",
        f"READER_SAFETY_POLICY_VERSION: Final = {policy['policyVersion']}",
        f"READER_SAFETY_POLICY_ID: Final = {py_string(str(policy['policyId']))}",
        f"READER_SAFETY_POLICY_DIGEST: Final = {py_string(digest)}",
        "READER_SAFETY_IMPLEMENTATION_FAILURE_CODES: Final = "
        + py_tuple(implementation_failure_codes, transform="ReaderSafetyErrorCode"),
        "",
        "READER_SAFETY_FORMATS = MappingProxyType({",
    ]
    for entry in formats:
        lines.append(
            f"    ReaderSafetyFormat.{entry['id']}: ReaderSafetyFormatDefinition(ReaderSafetyFormat.{entry['id']}, "
            f"ReaderSafetyMorphology.{entry['morphology']}, ReaderSafetyDeliveryMode.{entry['deliveryMode']}, "
            f"ReaderSafetyFormatLifecycle.{entry['lifecycle']}, {entry['extension']!r}, {entry['canonicalMimeType']!r}, "
            f"{py_tuple(entry['acceptedMimeTypes'])}, {py_tuple(entry['requiredConsumers'], transform='ReaderSafetyConsumer')}),"
        )
    lines += ["})", "READER_SAFETY_BUDGETS = MappingProxyType({"]
    for name, amount in budgets.items():
        lines.append(f"    ReaderSafetyBudgetName.{enum_symbol(name)}: {amount},")
    lines += ["})", "READER_SAFETY_RULES = MappingProxyType({"]
    for rule in rules:
        error = (
            "None"
            if rule["errorCode"] is None
            else f"ReaderSafetyErrorCode.{rule['errorCode']}"
        )
        lines.append(
            f"    ReaderSafetyRuleId.{enum_symbol(rule['id'])}: ReaderSafetyRule(ReaderSafetyRuleId.{enum_symbol(rule['id'])}, "
            f"{py_tuple(rule['formats'], transform='ReaderSafetyFormat')}, ReaderSafetyStage.{rule['stage']}, "
            f"ReaderSafetyAlgorithmId.{rule['algorithm']}, {py_tuple(rule['parameterRefs'])}, ReaderSafetyAction.{rule['action']}, "
            f"{error}, {py_tuple(rule['requiredConsumers'], transform='ReaderSafetyConsumer')}),"
        )
    lines += ["})", "READER_SAFETY_PLATFORM_DEFENSES = MappingProxyType({"]
    for defense in defenses:
        lines.append(
            f"    ReaderSafetyPlatformDefenseId.{defense['id']}: ReaderSafetyPlatformDefense(ReaderSafetyPlatformDefenseId.{defense['id']}, "
            f"{py_tuple(defense['formats'], transform='ReaderSafetyFormat')}, ReaderSafetyStage.{defense['stage']}, "
            f"{py_tuple(defense['requiredConsumers'], transform='ReaderSafetyConsumer')}),"
        )
    reflow = profiles["reflowable"]
    pdf = profiles["pdf"]
    comic = profiles["comic"]
    audio = profiles["audio"]
    lines += [
        "})",
        "",
        "READER_SAFETY_REFLOWABLE_PROFILE: Final = ReaderSafetyReflowableProfile(",
        "    safe_doctypes=(",
    ]
    for item in reflow["safeDoctypes"]:
        lines.append(
            "        ReaderSafetyDoctype("
            f"{py_string(item['name'])}, {py_string(item['publicId'])}, {py_string(item['systemId'])}),"
        )
    lines += [
        "    ),",
        f"    external_dtd_resolution={reflow['externalDtdResolution']},",
        f"    reject_internal_subset={reflow['rejectInternalSubset']},",
        f"    reject_custom_entities={reflow['rejectCustomEntities']},",
        "    named_entity_codepoints=MappingProxyType({",
    ]
    for name, codepoint in reflow["namedEntityCodepoints"].items():
        lines.append(f"        {py_string(name)}: {codepoint},")
    lines += [
        "    }),",
        f"    reading_order_markup_mime_types={py_tuple(reflow['readingOrderMarkupMimeTypes'])},",
        "    embedded_image_extensions_by_mime_type=MappingProxyType({",
    ]
    for mime, extension in reflow["embeddedImageExtensionsByMimeType"].items():
        lines.append(f"        {py_string(mime)}: {py_string(extension)},")
    lines += [
        "    }),",
        f"    sanitized_elements={py_tuple(reflow['sanitizedElements'])},",
        f"    sanitized_attributes={py_tuple(reflow['sanitizedAttributes'])},",
        f"    sanitized_attribute_prefixes={py_tuple(reflow['sanitizedAttributePrefixes'])},",
        f"    sanitized_meta_http_equiv_values={py_tuple(reflow['sanitizedMetaHttpEquivValues'])},",
        f"    blocked_author_schemes={py_tuple(reflow['blockedAuthorSchemes'])},",
        f"    remote_subresource_schemes={py_tuple(reflow['remoteSubresourceSchemes'])},",
        f"    user_navigation_schemes={py_tuple(reflow['userNavigationSchemes'])},",
        f"    trusted_runtime_schemes={py_tuple(reflow['trustedRuntimeSchemes'])},",
        f"    allowed_font_obfuscation_algorithms={py_tuple(reflow['allowedFontObfuscationAlgorithms'])},",
        f"    svg_sanitized_elements={py_tuple(reflow['svgSanitizedElements'])},",
        f"    css_text_elements={py_tuple(reflow['cssTextElements'])},",
        f"    css_sanitized_constructs={py_tuple(reflow['cssSanitizedConstructs'])},",
        f"    archive_fatal_findings={py_tuple(reflow['archiveFatalFindings'])},",
        "    uri_attribute_policies=(",
    ]
    for uri_policy in reflow["uriAttributePolicies"]:
        lines.append(
            "        ReaderSafetyUriAttributePolicy("
            f"{py_tuple(uri_policy['elements'])}, {py_string(uri_policy['attribute'])}, "
            f"ReaderSafetyUriSyntax.{uri_policy['syntax']}, "
            f"ReaderSafetyUriPurpose.{uri_policy['purpose']}),"
        )
    lines += [
        "    ),",
        ")",
        "",
        "READER_SAFETY_PDF_PROFILE: Final = ReaderSafetyPdfProfile(",
        f"    blocked_actions={py_tuple(pdf['blockedActions'])},",
        f"    require_finite_page_geometry={pdf['requireFinitePageGeometry']},",
        f"    require_identity_content_encoding={pdf['requireIdentityContentEncoding']},",
        f"    require_strong_revision={pdf['requireStrongRevision']},",
        f"    engine_request_limit={py_string(pdf['engineRequestLimit'])},",
        f"    large_request_action={py_string(pdf['largeRequestAction'])},",
        f"    allow_whole_response_fallback={pdf['allowWholeResponseFallback']},",
        ")",
        "",
        "READER_SAFETY_COMIC_PROFILE: Final = ReaderSafetyComicProfile(",
        f"    allowed_page_mime_types={py_tuple(comic['allowedPageMimeTypes'])},",
        "    page_mime_types_by_extension=MappingProxyType({",
    ]
    for extension, mime in comic["pageMimeTypesByExtension"].items():
        lines.append(f"        {py_string(extension)}: {py_string(mime)},")
    lines += [
        "    }),",
        f"    archive_fatal_findings={py_tuple(comic['archiveFatalFindings'])},",
        f"    single_page_decode_failure_action=ReaderSafetyAction.{comic['singlePageDecodeFailureAction']},",
        f"    manifest_revision_required={comic['manifestRevisionRequired']},",
        ")",
        "",
        "READER_SAFETY_AUDIO_PROFILE: Final = ReaderSafetyAudioProfile(",
        "    container_mime_types=MappingProxyType({",
    ]
    for extension, mime in audio["containerMimeTypes"].items():
        lines.append(f"        {py_string(extension)}: {py_string(mime)},")
    lines += [
        "    }),",
        f"    codec_decision={py_string(audio['codecDecision'])},",
        f"    blocked_redirect_schemes={py_tuple(audio['blockedRedirectSchemes'])},",
        f"    require_finite_non_negative_duration={audio['requireFiniteNonNegativeDuration']},",
        f"    require_ordered_track_identity={audio['requireOrderedTrackIdentity']},",
        ")",
        "",
        "def reader_safety_format_policy(source_format: str) -> ReaderSafetyFormatDefinition | None:",
        "    try:",
        "        format_id = ReaderSafetyFormat(source_format.strip().upper())",
        "    except ValueError:",
        "        return None",
        "    return READER_SAFETY_FORMATS[format_id]",
        "",
        "def require_reader_safety_format_policy(source_format: str) -> ReaderSafetyFormatDefinition:",
        "    policy = reader_safety_format_policy(source_format)",
        "    if policy is None:",
        '        raise ValueError(f"unsupported Reader safety format: {source_format}")',
        "    return policy",
        "",
        "def reader_safety_budget(name: ReaderSafetyBudgetName) -> int:",
        "    return READER_SAFETY_BUDGETS[name]",
        "",
        "def reader_safety_rule(rule_id: ReaderSafetyRuleId) -> ReaderSafetyRule:",
        "    return READER_SAFETY_RULES[rule_id]",
        "",
        "def reader_safety_comic_page_mime_type(extension: str) -> str | None:",
        "    return READER_SAFETY_COMIC_PROFILE.page_mime_types_by_extension.get(",
        "        extension.strip().lower()",
        "    )",
        "",
        "def reader_safety_fb2_embedded_image_extension(media_type: str) -> str | None:",
        "    return READER_SAFETY_REFLOWABLE_PROFILE.embedded_image_extensions_by_mime_type.get(",
        "        media_type.strip().lower()",
        "    )",
        "",
        "# fmt: on",
        "",
    ]
    return "\n".join(lines)


def render_c(policy: Mapping[str, object], digest: str) -> str:
    """Generate native comic admission values from the authoritative policy."""

    comic = policy["profiles"]["comic"]  # type: ignore[index]
    budgets = policy["budgets"]  # type: ignore[index]
    extensions = sorted(
        extension.removeprefix(".") for extension in comic["pageMimeTypesByExtension"]
    )
    comparisons = " ||\n        ".join(
        f"strcmp(extension, {json.dumps(extension)}) == 0" for extension in extensions
    )
    return f"""/* Generated by packages/reader-contracts/generate-reader-safety-policy.py. Do not edit. */
#ifndef ERMAO_READER_SAFETY_POLICY_GENERATED_H
#define ERMAO_READER_SAFETY_POLICY_GENERATED_H

#include <string.h>

#define ERMAO_READER_SAFETY_POLICY_DIGEST {json.dumps(digest)}
#define ERMAO_READER_SAFETY_COMIC_PAGE_MAX_COUNT {budgets["comicPageMaxCount"]}LL
#define ERMAO_READER_SAFETY_COMIC_PAGE_MAX_BYTES {budgets["comicPageMaxBytes"]}LL
#define ERMAO_READER_SAFETY_COMIC_EXPANDED_MAX_BYTES {budgets["comicExpandedMaxBytes"]}LL
#define ERMAO_READER_SAFETY_COMIC_COMPRESSION_RATIO_MAX {budgets["comicCompressionRatioMax"]}LL

static inline int ermao_reader_safety_comic_extension_allowed(const char *extension) {{
    if (extension == NULL) return 0;
    return {comparisons};
}}

#endif
"""


def write_or_check(path: Path, expected: str, *, check: bool) -> None:
    if check:
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            raise SystemExit(
                f"stale generated Reader safety policy: {path.relative_to(ROOT)}"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(expected, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="fail when generated bindings drift"
    )
    args = parser.parse_args()
    if not SCHEMA.exists():
        raise SystemExit("Reader safety policy schema is missing")
    if not FIXTURE_SCHEMA.exists() or not FIXTURES.exists():
        raise SystemExit("Reader safety fixture schema or manifest is missing")
    policy = validate_policy(json.loads(SOURCE.read_text(encoding="utf-8")))
    digest = policy_digest(policy)
    validate_fixture_manifest(
        json.loads(FIXTURES.read_text(encoding="utf-8")), policy=policy, digest=digest
    )
    validate_normalization_v3_fixture(policy=policy, digest=digest)
    write_or_check(TS_TARGET, render_typescript(policy, digest), check=args.check)
    write_or_check(KT_TARGET, render_kotlin(policy, digest), check=args.check)
    write_or_check(PY_TARGET, render_python(policy, digest), check=args.check)
    write_or_check(C_TARGET, render_c(policy, digest), check=args.check)


if __name__ == "__main__":
    main()
