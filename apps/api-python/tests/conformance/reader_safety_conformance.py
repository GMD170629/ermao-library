"""Executable backend Reader safety conformance report adapter."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import re
import sys
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
API_ROOT = REPOSITORY_ROOT / "apps/api-python"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.contracts.reader_safety_policy_generated import (
    READER_SAFETY_AUDIO_PROFILE,
    READER_SAFETY_COMIC_PROFILE,
    READER_SAFETY_PDF_PROFILE,
    READER_SAFETY_POLICY_DIGEST,
    READER_SAFETY_POLICY_ID,
    READER_SAFETY_POLICY_VERSION,
    READER_SAFETY_REFLOWABLE_PROFILE,
    ReaderSafetyAction,
    ReaderSafetyBudgetName,
    ReaderSafetyRuleId,
    reader_safety_budget,
    reader_safety_format_policy,
    reader_safety_rule,
)
from app.modules.publications.domain.model import PublicationSecurityError
from app.modules.publications.infrastructure.epub_adapter import _verify_entry_contents
from app.modules.publications.infrastructure.locator_dom import parse_safe_markup_root

FIXTURE_ROOT = REPOSITORY_ROOT / "packages/reader-contracts/fixtures/reader-safety-v1"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"
SUITE_PATH = FIXTURE_ROOT / "conformance-suite.json"
_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_MARKUP_EVALUATORS = frozenset(
    {
        "REFLOWABLE_MARKUP",
        "REFLOWABLE_NAMED_ENTITIES",
        "REFLOWABLE_MARKUP_SANITIZE",
        "REFLOWABLE_URI",
        "REFLOWABLE_CSS",
        "REFLOWABLE_SVG",
    }
)


@dataclass(frozen=True, slots=True)
class ActualDecision:
    rule_id: ReaderSafetyRuleId
    action: str
    error_code: str | None
    event: str
    semantic_projection: str | None


def _load_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Reader safety fixture must be an object: {path}")
    return value


def _case_map(manifest: Mapping[str, object]) -> Mapping[str, Mapping[str, object]]:
    raw_cases = manifest.get("cases")
    if not isinstance(raw_cases, list):
        raise TypeError("Reader safety manifest cases must be an array")
    cases: dict[str, Mapping[str, object]] = {}
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise TypeError("Reader safety manifest case must be an object")
        case_id = raw_case.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("Reader safety manifest case id is invalid")
        cases[case_id] = raw_case
    return cases


def _backend_suite_cases(suite: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
    raw_cases = suite.get("cases")
    if not isinstance(raw_cases, list):
        raise TypeError("Reader safety conformance suite cases must be an array")
    cases: list[Mapping[str, object]] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise TypeError("Reader safety conformance case must be an object")
        consumers = raw_case.get("consumers")
        if not isinstance(consumers, list):
            raise TypeError("Reader safety conformance consumers must be an array")
        if "BACKEND" in consumers:
            cases.append(raw_case)
    return cases


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _facts(source: str) -> Mapping[str, str]:
    facts: dict[str, str] = {}
    for component in source.split(";"):
        key, separator, value = component.partition("=")
        if not separator or not key:
            raise ValueError(f"invalid conformance fact: {component}")
        facts[key] = value
    return facts


def _integer_fact(facts: Mapping[str, str], name: str) -> int:
    return int(facts[name])


def _generated_decision(
    rule_id: ReaderSafetyRuleId,
    *,
    semantic_projection: str | None = None,
) -> ActualDecision:
    rule = reader_safety_rule(rule_id)
    return ActualDecision(
        rule_id=rule_id,
        action=rule.action.value,
        error_code=rule.error_code.value if rule.error_code is not None else None,
        event=f"{rule_id.value}:{rule.action.value}",
        semantic_projection=semantic_projection,
    )


def _allowed_decision(
    rule_id: ReaderSafetyRuleId,
    *,
    event: str,
    semantic_projection: str,
) -> ActualDecision:
    return ActualDecision(
        rule_id, "ALLOW", None, f"{rule_id.value}:{event}", semantic_projection
    )


def _canonical_markup(root: ElementTree.Element) -> str:
    markup = ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)
    markup = re.sub(r"\s+/>", "/>", markup)
    for element in _VOID_ELEMENTS:
        markup = re.sub(rf"<{element}([^>]*)/>", rf"<{element}\1>", markup)
    return markup


def _evaluate_markup(
    evaluator: str,
    rule_id: ReaderSafetyRuleId,
    source: str,
) -> ActualDecision:
    if evaluator == "REFLOWABLE_CSS":
        parser_source = f"<style>{source}</style>"
    elif evaluator in {
        "REFLOWABLE_MARKUP_SANITIZE",
        "REFLOWABLE_URI",
        "REFLOWABLE_SVG",
    }:
        xml_fragment = source
        for element in _VOID_ELEMENTS:
            xml_fragment = re.sub(
                rf"<{element}(?P<attributes>[^>]*?)(?<!/)>",
                rf"<{element}\g<attributes>/>",
                xml_fragment,
                flags=re.IGNORECASE,
            )
        parser_source = f"<conformance-root>{xml_fragment}</conformance-root>"
    else:
        parser_source = source
    try:
        _original, root = parse_safe_markup_root(parser_source.encode("utf-8"))
    except PublicationSecurityError as error:
        actual_rule = ReaderSafetyRuleId(error.rule_id)
        if actual_rule is not rule_id:
            raise AssertionError(
                f"markup rejected with {actual_rule.value}, expected {rule_id.value}"
            ) from error
        return _generated_decision(actual_rule)

    if evaluator in {"REFLOWABLE_MARKUP", "REFLOWABLE_NAMED_ENTITIES"}:
        if (
            evaluator == "REFLOWABLE_NAMED_ENTITIES"
            and "".join(root.itertext()) != "\u00a0©"
        ):
            raise AssertionError("generated XHTML entities were not decoded")
        projection = root.tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower()
    elif evaluator == "REFLOWABLE_CSS":
        projection = root.text or ""
    else:
        projection = "".join(_canonical_markup(child) for child in root)
        if projection == source:
            raise AssertionError(f"{evaluator} did not detect authored active content")
    return _generated_decision(rule_id, semantic_projection=projection)


def _archive_is_unsafe(source: str, fatal_findings: Sequence[str]) -> bool:
    canonical: set[str] = set()
    findings: set[str] = set()
    for entry in source.split("|"):
        if "\\" in entry:
            findings.add("BACKSLASH_PATH")
        if "\x00" in entry:
            findings.add("NUL_PATH")
        path = PurePosixPath(entry)
        if path.is_absolute():
            findings.add("ABSOLUTE_PATH")
        if any(part in {".", ".."} for part in entry.split("/")):
            findings.add("DOT_SEGMENT")
        normalized_parts: list[str] = []
        escaped = False
        for part in entry.split("/"):
            if part in {"", "."}:
                continue
            if part == "..":
                if not normalized_parts:
                    escaped = True
                else:
                    normalized_parts.pop()
            else:
                normalized_parts.append(part)
        if escaped:
            findings.add("PATH_ESCAPE")
        normalized = "/".join(normalized_parts).casefold()
        if normalized in canonical:
            findings.add("DUPLICATE_CANONICAL_ENTRY")
        canonical.add(normalized)
    return bool(findings & set(fatal_findings))


def _evaluate_fact(
    evaluator: str,
    rule_id: ReaderSafetyRuleId,
    source: str,
) -> ActualDecision:
    facts = _facts(source) if "=" in source else {}
    if evaluator == "ARCHIVE_STRUCTURE":
        detected = _archive_is_unsafe(
            source,
            READER_SAFETY_REFLOWABLE_PROFILE.archive_fatal_findings,
        )
    elif evaluator == "EPUB_ARCHIVE_CRC":
        prefix, separator, encoded = source.partition(":")
        if prefix != "base64" or not separator:
            raise ValueError("EPUB CRC fixture must contain a base64 archive")
        try:
            with zipfile.ZipFile(
                io.BytesIO(base64.b64decode(encoded, validate=True))
            ) as archive:
                _verify_entry_contents(
                    archive,
                    {info.filename: info for info in archive.infolist()},
                )
        except PublicationSecurityError as error:
            actual_rule = ReaderSafetyRuleId(error.rule_id)
            if actual_rule is not rule_id:
                raise AssertionError(
                    "backend CRC preflight emitted the wrong rule"
                ) from error
            return _generated_decision(actual_rule)
        raise AssertionError("backend EPUB preflight accepted a corrupted unused entry")
    elif evaluator == "ORIGINAL_BYTES":
        detected = _integer_fact(facts, "sizeBytes") > reader_safety_budget(
            ReaderSafetyBudgetName.ORIGINAL_MAX_BYTES
        )
        if not detected:
            return _allowed_decision(
                rule_id,
                event="BOUNDARY_ALLOW",
                semantic_projection=source,
            )
    elif evaluator == "FB2_STRUCTURE":
        detected = (
            _integer_fact(facts, "depth")
            > reader_safety_budget(ReaderSafetyBudgetName.FB2_MAX_DEPTH)
            or _integer_fact(facts, "nodes")
            > reader_safety_budget(ReaderSafetyBudgetName.FB2_MAX_NODES)
            or _integer_fact(facts, "textChars")
            > reader_safety_budget(ReaderSafetyBudgetName.FB2_TEXT_MAX_CHARACTERS)
        )
    elif evaluator == "PDF_ACTIVE_ACTIONS":
        source_actions = {value for value in facts["actions"].split(",") if value}
        blocked = source_actions & set(READER_SAFETY_PDF_PROFILE.blocked_actions)
        detected = bool(blocked)
        if detected:
            remaining = ",".join(sorted(source_actions - blocked))
            return _generated_decision(rule_id, semantic_projection=remaining)
    elif evaluator == "PDF_PAGE_GEOMETRY":
        page_count = _integer_fact(facts, "pageCount")
        width = float(facts["width"])
        height = float(facts["height"])
        detected = page_count > reader_safety_budget(
            ReaderSafetyBudgetName.PDF_PAGE_MAX_COUNT
        )
        if READER_SAFETY_PDF_PROFILE.require_finite_page_geometry:
            detected = detected or not all(
                math.isfinite(value) and value > 0 for value in (width, height)
            )
    elif evaluator == "PDF_RANGE_PROTOCOL":
        detected = (
            (
                facts["status"] != "206"
                and not READER_SAFETY_PDF_PROFILE.allow_whole_response_fallback
            )
            or (
                facts["encoding"].casefold() != "identity"
                and READER_SAFETY_PDF_PROFILE.require_identity_content_encoding
            )
            or (
                facts["revision"].casefold() == "weak"
                and READER_SAFETY_PDF_PROFILE.require_strong_revision
            )
        )
    elif evaluator == "COMIC_PAGE_MIME":
        manifest_mime = facts["manifest"].casefold()
        response_mime = facts["response"].casefold()
        detected = (
            manifest_mime in READER_SAFETY_COMIC_PROFILE.allowed_page_mime_types
            and response_mime != manifest_mime
        )
    elif evaluator == "COMIC_PAGE_COUNT":
        detected = _integer_fact(facts, "pageCount") > reader_safety_budget(
            ReaderSafetyBudgetName.COMIC_PAGE_MAX_COUNT
        )
    elif evaluator == "COMIC_PAGE_DECODE":
        detected = (
            facts["decoder"] == "failed"
            and READER_SAFETY_COMIC_PROFILE.single_page_decode_failure_action
            is ReaderSafetyAction.BLOCK_RESOURCE
        )
    elif evaluator == "COMIC_REVISION":
        detected = (
            READER_SAFETY_COMIC_PROFILE.manifest_revision_required
            and facts["manifestRevision"] != facts["requestRevision"]
        )
    elif evaluator == "AUDIO_CONTAINER_MIME":
        expected_mime = READER_SAFETY_AUDIO_PROFILE.container_mime_types.get(
            facts["extension"].casefold()
        )
        detected = (
            expected_mime is not None and expected_mime != facts["mime"].casefold()
        )
    elif evaluator == "AUDIO_CODEC":
        detected = (
            READER_SAFETY_AUDIO_PROFILE.codec_decision == "ENGINE_CAPABILITY"
            and facts["codec"] == "unsupported"
        )
    elif evaluator == "AUDIO_CHAPTER_BOUNDS":
        duration = float(facts["durationMs"])
        start = float(facts["chapterStartMs"])
        end = float(facts["chapterEndMs"])
        detected = not (0 <= start <= end <= duration)
        if READER_SAFETY_AUDIO_PROFILE.require_finite_non_negative_duration:
            detected = detected or not all(
                math.isfinite(value) and value >= 0 for value in (duration, start, end)
            )
    elif evaluator == "DRM_ALGORITHM":
        algorithm = facts["algorithm"]
        detected = (
            algorithm
            not in READER_SAFETY_REFLOWABLE_PROFILE.allowed_font_obfuscation_algorithms
        )
        if not detected:
            return _allowed_decision(
                rule_id,
                event="ALLOW_FONT_OBFUSCATION",
                semantic_projection="font-obfuscation-allowed",
            )
    elif evaluator == "EXACT_FORMAT_MIME":
        format_policy = reader_safety_format_policy(facts["format"])
        normalized_mime = facts["mime"].partition(";")[0].strip().casefold()
        detected = (
            format_policy is None
            or normalized_mime not in format_policy.accepted_mime_types
        )
    elif evaluator == "BINARY_RESOURCE_BYTES":
        detected = _integer_fact(facts, "resourceBytes") > reader_safety_budget(
            ReaderSafetyBudgetName.BINARY_RESOURCE_MAX_BYTES
        )
    elif evaluator == "OPTIONAL_RESOURCE":
        detected = facts["required"] == "false" and facts["available"] == "false"
    elif evaluator == "REQUIRED_READING_ORDER_MARKUP":
        detected = _integer_fact(facts, "readingOrderCount") > 0 and (
            _integer_fact(facts, "markupCount")
            < _integer_fact(facts, "readingOrderCount")
            or facts["mime"].casefold()
            not in READER_SAFETY_REFLOWABLE_PROFILE.reading_order_markup_mime_types
        )
    elif evaluator == "XML_CONTROL_DOCUMENT_BYTES":
        detected = _integer_fact(facts, "controlDocumentBytes") > reader_safety_budget(
            ReaderSafetyBudgetName.XML_CONTROL_DOCUMENT_MAX_BYTES
        )
    elif evaluator == "REFLOWABLE_MARKUP_BYTES":
        detected = _integer_fact(facts, "markupBytes") > reader_safety_budget(
            ReaderSafetyBudgetName.REFLOWABLE_MARKUP_MAX_BYTES
        )
    elif evaluator == "EPUB_ARCHIVE_ENTRY_COUNT":
        detected = _integer_fact(facts, "entryCount") > reader_safety_budget(
            ReaderSafetyBudgetName.ARCHIVE_ENTRY_MAX_COUNT
        )
    elif evaluator == "EPUB_ARCHIVE_EXPANDED_BYTES":
        detected = _integer_fact(facts, "expandedBytes") > reader_safety_budget(
            ReaderSafetyBudgetName.ARCHIVE_EXPANDED_MAX_BYTES
        )
    elif evaluator == "EPUB_ARCHIVE_ENTRY_BYTES":
        detected = _integer_fact(facts, "entryBytes") > reader_safety_budget(
            ReaderSafetyBudgetName.ARCHIVE_ENTRY_MAX_BYTES
        )
    elif evaluator == "EPUB_ARCHIVE_COMPRESSION_RATIO":
        compressed_bytes = _integer_fact(facts, "compressedBytes")
        detected = compressed_bytes <= 0 or _integer_fact(
            facts, "expandedBytes"
        ) > compressed_bytes * reader_safety_budget(
            ReaderSafetyBudgetName.ARCHIVE_COMPRESSION_RATIO_MAX
        )
    elif evaluator == "FB2_IMAGE_BUDGET":
        detected = (
            facts["mime"].casefold()
            not in READER_SAFETY_REFLOWABLE_PROFILE.embedded_image_extensions_by_mime_type
            or _integer_fact(facts, "encodedBytes")
            > reader_safety_budget(ReaderSafetyBudgetName.FB2_ENCODED_IMAGE_MAX_BYTES)
            or _integer_fact(facts, "decodedBytes")
            > reader_safety_budget(ReaderSafetyBudgetName.FB2_DECODED_IMAGE_MAX_BYTES)
            or _integer_fact(facts, "decodedTotalBytes")
            > reader_safety_budget(
                ReaderSafetyBudgetName.FB2_DECODED_IMAGES_TOTAL_MAX_BYTES
            )
        )
    elif evaluator == "TXT_MEMORY_BYTES":
        detected = _integer_fact(facts, "textBytes") > reader_safety_budget(
            ReaderSafetyBudgetName.TXT_MEMORY_MAX_BYTES
        )
    elif evaluator == "TXT_CHUNK_CHARACTERS":
        detected = _integer_fact(facts, "chunkCharacters") <= reader_safety_budget(
            ReaderSafetyBudgetName.TXT_CHUNK_MAX_CHARACTERS
        )
        if detected:
            return _generated_decision(rule_id, semantic_projection=source)
    elif evaluator == "PDF_RENDER_BUDGET":
        detected = (
            _integer_fact(facts, "width")
            > reader_safety_budget(ReaderSafetyBudgetName.PDF_CANVAS_MAX_DIMENSION)
            or _integer_fact(facts, "height")
            > reader_safety_budget(ReaderSafetyBudgetName.PDF_CANVAS_MAX_DIMENSION)
            or _integer_fact(facts, "pixels")
            > reader_safety_budget(ReaderSafetyBudgetName.PDF_RENDER_MAX_PIXELS)
        )
    elif evaluator == "COMIC_ARCHIVE_STRUCTURE":
        detected = _archive_is_unsafe(
            source,
            READER_SAFETY_COMIC_PROFILE.archive_fatal_findings,
        )
    elif evaluator == "COMIC_ARCHIVE_BUDGET":
        compressed_bytes = _integer_fact(facts, "compressedBytes")
        expanded_bytes = _integer_fact(facts, "expandedBytes")
        detected = (
            expanded_bytes
            > reader_safety_budget(ReaderSafetyBudgetName.COMIC_EXPANDED_MAX_BYTES)
            or compressed_bytes <= 0
            or expanded_bytes
            > compressed_bytes
            * reader_safety_budget(ReaderSafetyBudgetName.COMIC_COMPRESSION_RATIO_MAX)
        )
    elif evaluator == "COMIC_PAGE_BYTES":
        detected = _integer_fact(facts, "pageBytes") > reader_safety_budget(
            ReaderSafetyBudgetName.COMIC_PAGE_MAX_BYTES
        )
    elif evaluator == "COMIC_MANIFEST_BYTES":
        detected = _integer_fact(facts, "manifestBytes") > reader_safety_budget(
            ReaderSafetyBudgetName.COMIC_MANIFEST_MAX_BYTES
        )
    elif evaluator == "AUDIO_ORIGINAL_BYTES":
        detected = _integer_fact(facts, "sizeBytes") > reader_safety_budget(
            ReaderSafetyBudgetName.ORIGINAL_MAX_BYTES
        )
    elif evaluator == "AUDIO_METADATA_BUDGET":
        detected = _integer_fact(facts, "metadataBytes") > reader_safety_budget(
            ReaderSafetyBudgetName.AUDIO_METADATA_MAX_BYTES
        ) or _integer_fact(facts, "artworkBytes") > reader_safety_budget(
            ReaderSafetyBudgetName.AUDIO_ARTWORK_MAX_BYTES
        )
    elif evaluator == "AUDIO_REDIRECT_POLICY":
        detected = (
            facts["scheme"].casefold()
            in READER_SAFETY_AUDIO_PROFILE.blocked_redirect_schemes
        )
    else:
        raise ValueError(f"unsupported backend conformance evaluator: {evaluator}")
    if not detected:
        raise AssertionError(
            f"{evaluator} fixture did not trigger its production policy fact"
        )
    return _generated_decision(rule_id)


def _evaluate_case(
    suite_case: Mapping[str, object],
    fixture_case: Mapping[str, object],
) -> dict[str, object]:
    case_id = suite_case.get("id")
    rule_value = suite_case.get("ruleId")
    evaluator = suite_case.get("evaluator")
    source = fixture_case.get("input")
    input_sha256 = fixture_case.get("inputSha256")
    if not all(
        isinstance(value, str)
        for value in (case_id, rule_value, source, input_sha256, evaluator)
    ):
        raise ValueError("Reader safety conformance case fields are invalid")
    assert isinstance(case_id, str)
    assert isinstance(rule_value, str)
    assert isinstance(source, str)
    assert isinstance(input_sha256, str)
    assert isinstance(evaluator, str)
    if _sha256(source) != input_sha256:
        raise ValueError(f"Reader safety fixture input hash differs for {case_id}")

    rule_id = ReaderSafetyRuleId(rule_value)
    decision = (
        _evaluate_markup(evaluator, rule_id, source)
        if evaluator in _MARKUP_EVALUATORS
        else _evaluate_fact(evaluator, rule_id, source)
    )
    return {
        "caseId": case_id,
        "inputSha256": input_sha256,
        "terminalRuleId": decision.rule_id.value,
        "action": decision.action,
        "errorCode": decision.error_code,
        "orderedRuleEvents": [decision.event],
        "semanticProjectionSha256": (
            _sha256(decision.semantic_projection)
            if decision.semantic_projection is not None
            else None
        ),
    }


def generate_backend_report() -> dict[str, object]:
    """Run backend production boundaries and generated pure-policy decisions."""

    suite = _load_mapping(SUITE_PATH)
    manifest = _load_mapping(MANIFEST_PATH)
    if (
        suite.get("policyId") != READER_SAFETY_POLICY_ID
        or suite.get("policyVersion") != READER_SAFETY_POLICY_VERSION
        or suite.get("policyDigest") != READER_SAFETY_POLICY_DIGEST
    ):
        raise ValueError(
            "Reader safety conformance suite targets a stale backend policy"
        )
    fixtures = _case_map(manifest)
    results = []
    for suite_case in _backend_suite_cases(suite):
        case_id = suite_case.get("id")
        if not isinstance(case_id, str) or case_id not in fixtures:
            raise ValueError(
                "Reader safety conformance suite references a missing fixture"
            )
        results.append(_evaluate_case(suite_case, fixtures[case_id]))
    return {
        "schemaVersion": 1,
        "policyId": READER_SAFETY_POLICY_ID,
        "policyVersion": READER_SAFETY_POLICY_VERSION,
        "policyDigest": READER_SAFETY_POLICY_DIGEST,
        "consumer": "BACKEND",
        "engine": f"python-{sys.version_info.major}.{sys.version_info.minor}/production+generated-policy",
        "results": results,
        "omissions": [],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = generate_backend_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
