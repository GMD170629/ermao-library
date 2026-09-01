#!/usr/bin/env python3
"""Validate real platform Reader safety reports against the versioned fixtures."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

CONTRACT_ROOT = Path(__file__).resolve().parent
FIXTURE_ROOT = CONTRACT_ROOT / "fixtures/reader-safety-v1"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"
SUITE_PATH = FIXTURE_ROOT / "conformance-suite.json"
POLICY_PATH = CONTRACT_ROOT / "reader-safety-policy.json"

REPORT_CONSUMERS = frozenset({"BACKEND", "WEB", "KMP", "ANDROID", "IOS"})
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RULE_ID = re.compile(r"[A-Z][A-Z0-9_.]{2,95}\Z")
ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,95}\Z")
ACTIONS = frozenset({"ALLOW", "SANITIZE", "BLOCK_RESOURCE", "REJECT_PUBLICATION"})
EVALUATORS = frozenset(
    {
        "REFLOWABLE_MARKUP",
        "REFLOWABLE_NAMED_ENTITIES",
        "REFLOWABLE_MARKUP_SANITIZE",
        "REFLOWABLE_URI",
        "REFLOWABLE_CSS",
        "REFLOWABLE_SVG",
        "ARCHIVE_STRUCTURE",
        "EPUB_ARCHIVE_CRC",
        "ORIGINAL_BYTES",
        "FB2_STRUCTURE",
        "PDF_ACTIVE_ACTIONS",
        "PDF_PAGE_GEOMETRY",
        "PDF_RANGE_PROTOCOL",
        "COMIC_PAGE_MIME",
        "COMIC_PAGE_COUNT",
        "COMIC_PAGE_DECODE",
        "COMIC_REVISION",
        "AUDIO_CONTAINER_MIME",
        "AUDIO_CODEC",
        "AUDIO_CHAPTER_BOUNDS",
        "DRM_ALGORITHM",
        "EXACT_FORMAT_MIME",
        "BINARY_RESOURCE_BYTES",
        "OPTIONAL_RESOURCE",
        "REQUIRED_READING_ORDER_MARKUP",
        "XML_CONTROL_DOCUMENT_BYTES",
        "REFLOWABLE_MARKUP_BYTES",
        "EPUB_ARCHIVE_ENTRY_COUNT",
        "EPUB_ARCHIVE_EXPANDED_BYTES",
        "EPUB_ARCHIVE_ENTRY_BYTES",
        "EPUB_ARCHIVE_COMPRESSION_RATIO",
        "FB2_IMAGE_BUDGET",
        "TXT_MEMORY_BYTES",
        "TXT_CHUNK_CHARACTERS",
        "PDF_RENDER_BUDGET",
        "COMIC_ARCHIVE_STRUCTURE",
        "COMIC_ARCHIVE_BUDGET",
        "COMIC_PAGE_BYTES",
        "COMIC_MANIFEST_BYTES",
        "AUDIO_ORIGINAL_BYTES",
        "AUDIO_METADATA_BUDGET",
        "AUDIO_REDIRECT_POLICY",
    }
)
SEMANTIC_PROJECTIONS = frozenset(
    {
        "ROOT_LOCAL_NAME",
        "SANITIZED_TEXT",
        "SANITIZED_MARKUP",
        "INPUT",
        "FONT_OBFUSCATION",
        "NONE",
    }
)
MANIFEST_CONSUMERS = frozenset({"BACKEND", "WEB", "ANDROID", "IOS"})
KMP_EXECUTABLE_EVALUATORS = frozenset(
    {
        "REFLOWABLE_MARKUP",
        "REFLOWABLE_NAMED_ENTITIES",
        "REFLOWABLE_MARKUP_SANITIZE",
        "REFLOWABLE_URI",
        "REFLOWABLE_CSS",
        "REFLOWABLE_SVG",
        "ORIGINAL_BYTES",
        "FB2_STRUCTURE",
        "PDF_RANGE_PROTOCOL",
        "COMIC_PAGE_MIME",
        "COMIC_PAGE_COUNT",
        "COMIC_REVISION",
        "DRM_ALGORITHM",
        "EXACT_FORMAT_MIME",
        "BINARY_RESOURCE_BYTES",
        "OPTIONAL_RESOURCE",
        "REQUIRED_READING_ORDER_MARKUP",
        "XML_CONTROL_DOCUMENT_BYTES",
        "REFLOWABLE_MARKUP_BYTES",
        "FB2_IMAGE_BUDGET",
        "TXT_MEMORY_BYTES",
        "TXT_CHUNK_CHARACTERS",
        "COMIC_ARCHIVE_BUDGET",
        "COMIC_PAGE_BYTES",
        "COMIC_MANIFEST_BYTES",
    }
)
IOS_EXECUTABLE_EVALUATORS = frozenset(
    {
        "AUDIO_CONTAINER_MIME",
        "AUDIO_CODEC",
        "AUDIO_CHAPTER_BOUNDS",
        "AUDIO_ORIGINAL_BYTES",
        "AUDIO_METADATA_BUDGET",
        "AUDIO_REDIRECT_POLICY",
    }
)


@dataclass(frozen=True)
class SuiteCase:
    case_id: str
    rule_id: str
    evaluator: str
    semantic_projection: str
    consumers: tuple[str, ...]


@dataclass(frozen=True)
class ExpectedCase:
    case_id: str
    input_sha256: str
    terminal_rule_id: str
    action: str
    error_code: str | None
    ordered_rule_events: tuple[str, ...]
    semantic_projection_sha256: str | None


def _consumer_can_own_execution(
    consumer: str, required_consumers: tuple[str, ...]
) -> bool:
    """Return whether a report owner can execute one declared policy obligation.

    KMP owns only shared Android/iOS semantics; it is never inferred merely
    because both native platforms are required. Native-only implementations
    remain obligations in the manifest and are proven by their own release gate.
    """

    required = set(required_consumers)
    return {
        "BACKEND": "BACKEND" in required,
        "WEB": "WEB" in required,
        "KMP": bool(required & {"ANDROID", "IOS"}),
        "ANDROID": "ANDROID" in required,
        "IOS": "IOS" in required,
    }[consumer]


@dataclass(frozen=True)
class ReportResult:
    case_id: str
    input_sha256: str
    terminal_rule_id: str
    action: str
    error_code: str | None
    ordered_rule_events: tuple[str, ...]
    semantic_projection_sha256: str | None


@dataclass(frozen=True)
class ConformanceReport:
    consumer: str
    engine: str
    results: tuple[ReportResult, ...]
    omissions: tuple[str, ...]


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return value


def _sequence(value: object, *, field: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise TypeError(f"{field} must be an array")
    return value


def _string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _integer(value: object, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field} must be an integer")
    return value


def _nullable_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field=field)


def _string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    items = tuple(
        _string(item, field=f"{field}[]") for item in _sequence(value, field=field)
    )
    if not items or len(items) != len(set(items)):
        raise ValueError(f"{field} must be a nonempty unique string array")
    return items


def _exact_keys(value: Mapping[str, object], *, field: str, keys: set[str]) -> None:
    if set(value) != keys:
        raise ValueError(f"{field} keys differ: {sorted(set(value) ^ keys)}")


def load_suite_and_expected(
    *,
    suite_path: Path = SUITE_PATH,
    manifest_path: Path = MANIFEST_PATH,
) -> tuple[Mapping[str, object], tuple[SuiteCase, ...], Mapping[str, ExpectedCase]]:
    suite = _mapping(_load_json(suite_path), field="suite")
    manifest = _mapping(_load_json(manifest_path), field="manifest")
    policy = _mapping(_load_json(POLICY_PATH), field="policy")
    for field in ("policyId", "policyVersion", "policyDigest"):
        if suite.get(field) != manifest.get(field):
            raise ValueError(f"suite {field} does not match the fixture manifest")
        if suite.get(field) != policy.get(field):
            raise ValueError(f"suite {field} does not match the authoritative policy")

    policy_rules: dict[str, tuple[str, ...]] = {}
    for index, raw_rule in enumerate(
        _sequence(policy.get("rules"), field="policy.rules")
    ):
        rule = _mapping(raw_rule, field=f"policy.rules[{index}]")
        rule_id = _string(rule.get("id"), field=f"policy.rules[{index}].id")
        if rule_id in policy_rules:
            raise ValueError(f"duplicate policy rule: {rule_id}")
        policy_rules[rule_id] = _string_tuple(
            rule.get("requiredConsumers"),
            field=f"policy.rules[{index}].requiredConsumers",
        )

    suite_cases: list[SuiteCase] = []
    suite_ids: set[str] = set()
    for index, raw_case in enumerate(
        _sequence(suite.get("cases"), field="suite.cases")
    ):
        value = _mapping(raw_case, field=f"suite.cases[{index}]")
        _exact_keys(
            value,
            field=f"suite.cases[{index}]",
            keys={"id", "ruleId", "evaluator", "semanticProjection", "consumers"},
        )
        case_id = _string(value.get("id"), field=f"suite.cases[{index}].id")
        if case_id in suite_ids:
            raise ValueError(f"duplicate suite case: {case_id}")
        suite_ids.add(case_id)
        rule_id = _string(value.get("ruleId"), field=f"suite.cases[{index}].ruleId")
        if not RULE_ID.fullmatch(rule_id):
            raise ValueError(f"invalid suite rule id: {rule_id}")
        evaluator = _string(
            value.get("evaluator"), field=f"suite.cases[{index}].evaluator"
        )
        if evaluator not in EVALUATORS:
            raise ValueError(f"unsupported suite evaluator: {evaluator}")
        projection = _string(
            value.get("semanticProjection"),
            field=f"suite.cases[{index}].semanticProjection",
        )
        if projection not in SEMANTIC_PROJECTIONS:
            raise ValueError(f"unsupported semantic projection: {projection}")
        consumers = _string_tuple(
            value.get("consumers"), field=f"suite.cases[{index}].consumers"
        )
        if not set(consumers) <= REPORT_CONSUMERS:
            raise ValueError(f"unsupported suite consumer for {case_id}")
        if evaluator == "EPUB_ARCHIVE_CRC" and consumers != (
            "BACKEND",
            "WEB",
            "ANDROID",
        ):
            raise ValueError(
                "EPUB CRC must execute through the three production adapters"
            )
        if "KMP" in consumers and evaluator not in KMP_EXECUTABLE_EVALUATORS:
            raise ValueError(f"KMP cannot claim a native-only evaluator for {case_id}")
        if "IOS" in consumers and evaluator not in IOS_EXECUTABLE_EVALUATORS:
            raise ValueError(f"iOS cannot claim an unimplemented evaluator for {case_id}")
        suite_cases.append(
            SuiteCase(case_id, rule_id, evaluator, projection, consumers)
        )

    manifest_cases: dict[str, ExpectedCase] = {}
    manifest_consumers: dict[str, tuple[str, ...]] = {}
    for index, raw_case in enumerate(
        _sequence(manifest.get("cases"), field="manifest.cases")
    ):
        value = _mapping(raw_case, field=f"manifest.cases[{index}]")
        case_id = _string(value.get("id"), field=f"manifest.cases[{index}].id")
        if case_id in manifest_cases:
            raise ValueError(f"duplicate manifest case: {case_id}")
        required_consumers = _string_tuple(
            value.get("requiredConsumers"),
            field=f"manifest.cases[{index}].requiredConsumers",
        )
        if not set(required_consumers) <= MANIFEST_CONSUMERS:
            raise ValueError(f"unsupported manifest consumer for {case_id}")
        manifest_consumers[case_id] = required_consumers
        expected = _mapping(
            value.get("expected"), field=f"manifest.cases[{index}].expected"
        )
        manifest_cases[case_id] = ExpectedCase(
            case_id=case_id,
            input_sha256=_string(
                value.get("inputSha256"),
                field=f"manifest.cases[{index}].inputSha256",
            ),
            terminal_rule_id=_string(
                expected.get("terminalRuleId"),
                field=f"manifest.cases[{index}].expected.terminalRuleId",
            ),
            action=_string(
                expected.get("action"),
                field=f"manifest.cases[{index}].expected.action",
            ),
            error_code=_nullable_string(
                expected.get("errorCode"),
                field=f"manifest.cases[{index}].expected.errorCode",
            ),
            ordered_rule_events=_string_tuple(
                expected.get("orderedRuleEvents"),
                field=f"manifest.cases[{index}].expected.orderedRuleEvents",
            ),
            semantic_projection_sha256=_nullable_string(
                expected.get("semanticProjectionSha256"),
                field=(f"manifest.cases[{index}].expected.semanticProjectionSha256"),
            ),
        )

    if suite_ids != set(manifest_cases):
        missing = sorted(set(manifest_cases) - suite_ids)
        extra = sorted(suite_ids - set(manifest_cases))
        raise ValueError(
            f"conformance suite must cover every manifest case; missing={missing}, extra={extra}"
        )

    for suite_case in suite_cases:
        expected = manifest_cases.get(suite_case.case_id)
        if expected is None:
            raise ValueError(
                f"suite case is missing from manifest: {suite_case.case_id}"
            )
        if suite_case.rule_id != expected.terminal_rule_id:
            raise ValueError(f"suite rule differs for {suite_case.case_id}")
        expects_projection = expected.semantic_projection_sha256 is not None
        if expects_projection != (suite_case.semantic_projection != "NONE"):
            raise ValueError(f"suite projection differs for {suite_case.case_id}")
        required_consumers = manifest_consumers[suite_case.case_id]
        if any(
            not _consumer_can_own_execution(consumer, required_consumers)
            for consumer in suite_case.consumers
        ):
            raise ValueError(
                f"suite claims an inapplicable execution owner for {suite_case.case_id}"
            )
        required_platform_owners = tuple(
            consumer
            for consumer in required_consumers
            if consumer in {"BACKEND", "WEB", "ANDROID"}
            or (consumer == "IOS" and suite_case.evaluator in IOS_EXECUTABLE_EVALUATORS)
        )
        claimed_platform_owners = tuple(
            consumer for consumer in suite_case.consumers if consumer != "KMP"
        )
        if claimed_platform_owners != required_platform_owners:
            raise ValueError(
                f"suite platform execution owners differ for {suite_case.case_id}: "
                f"expected {required_platform_owners}, got {claimed_platform_owners}"
            )
        policy_consumers = policy_rules.get(suite_case.rule_id)
        if policy_consumers is None:
            raise ValueError(
                f"suite references an unknown policy rule: {suite_case.rule_id}"
            )
        if required_consumers != policy_consumers:
            raise ValueError(
                f"manifest consumer obligations differ for {suite_case.case_id}"
            )

    manifest_rule_ids = {
        expected.terminal_rule_id for expected in manifest_cases.values()
    }
    suite_rule_ids = {case.rule_id for case in suite_cases}
    if manifest_rule_ids != set(policy_rules):
        raise ValueError(
            "fixture manifest does not cover every authoritative policy rule"
        )
    if suite_rule_ids != set(policy_rules):
        raise ValueError(
            "executable suite does not cover every authoritative policy rule"
        )
    return suite, tuple(suite_cases), manifest_cases


def validate_report(
    value: object,
    *,
    suite: Mapping[str, object],
    suite_cases: tuple[SuiteCase, ...],
    expected_cases: Mapping[str, ExpectedCase],
) -> ConformanceReport:
    report = _mapping(value, field="report")
    _exact_keys(
        report,
        field="report",
        keys={
            "schemaVersion",
            "policyId",
            "policyVersion",
            "policyDigest",
            "consumer",
            "engine",
            "results",
            "omissions",
        },
    )
    if _integer(report.get("schemaVersion"), field="report.schemaVersion") != 1:
        raise ValueError("unsupported report schemaVersion")
    for field in ("policyId", "policyVersion", "policyDigest"):
        if report.get(field) != suite.get(field):
            raise ValueError(f"report {field} does not match the conformance suite")
    digest = _string(report.get("policyDigest"), field="report.policyDigest")
    if not SHA256.fullmatch(digest):
        raise ValueError("report policyDigest is invalid")
    consumer = _string(report.get("consumer"), field="report.consumer")
    if consumer not in REPORT_CONSUMERS:
        raise ValueError(f"unsupported report consumer: {consumer}")
    engine = _string(report.get("engine"), field="report.engine")

    expected_ids = tuple(
        case.case_id for case in suite_cases if consumer in case.consumers
    )
    results: list[ReportResult] = []
    for index, raw_result in enumerate(
        _sequence(report.get("results"), field="report.results")
    ):
        result = _mapping(raw_result, field=f"report.results[{index}]")
        _exact_keys(
            result,
            field=f"report.results[{index}]",
            keys={
                "caseId",
                "inputSha256",
                "terminalRuleId",
                "action",
                "errorCode",
                "orderedRuleEvents",
                "semanticProjectionSha256",
            },
        )
        case_id = _string(result.get("caseId"), field=f"report.results[{index}].caseId")
        parsed = ReportResult(
            case_id=case_id,
            input_sha256=_string(
                result.get("inputSha256"),
                field=f"report.results[{index}].inputSha256",
            ),
            terminal_rule_id=_string(
                result.get("terminalRuleId"),
                field=f"report.results[{index}].terminalRuleId",
            ),
            action=_string(
                result.get("action"), field=f"report.results[{index}].action"
            ),
            error_code=_nullable_string(
                result.get("errorCode"),
                field=f"report.results[{index}].errorCode",
            ),
            ordered_rule_events=_string_tuple(
                result.get("orderedRuleEvents"),
                field=f"report.results[{index}].orderedRuleEvents",
            ),
            semantic_projection_sha256=_nullable_string(
                result.get("semanticProjectionSha256"),
                field=f"report.results[{index}].semanticProjectionSha256",
            ),
        )
        if not SHA256.fullmatch(parsed.input_sha256):
            raise ValueError(f"invalid input hash for {case_id}")
        if not RULE_ID.fullmatch(parsed.terminal_rule_id):
            raise ValueError(f"invalid terminal rule for {case_id}")
        if parsed.action not in ACTIONS:
            raise ValueError(f"invalid action for {case_id}")
        if parsed.error_code is not None and not ERROR_CODE.fullmatch(
            parsed.error_code
        ):
            raise ValueError(f"invalid error code for {case_id}")
        if parsed.semantic_projection_sha256 is not None and not SHA256.fullmatch(
            parsed.semantic_projection_sha256
        ):
            raise ValueError(f"invalid semantic projection hash for {case_id}")
        expected = expected_cases.get(case_id)
        if expected is None or parsed != ReportResult(
            case_id=expected.case_id,
            input_sha256=expected.input_sha256,
            terminal_rule_id=expected.terminal_rule_id,
            action=expected.action,
            error_code=expected.error_code,
            ordered_rule_events=expected.ordered_rule_events,
            semantic_projection_sha256=expected.semantic_projection_sha256,
        ):
            raise ValueError(f"actual conformance result differs for {case_id}")
        results.append(parsed)

    result_ids = tuple(result.case_id for result in results)
    if len(result_ids) != len(set(result_ids)):
        raise ValueError(f"{consumer} report contains duplicate results")

    omissions = _sequence(report.get("omissions"), field="report.omissions")
    if omissions:
        raise ValueError(
            f"{consumer} report cannot omit a declared executable implementation owner"
        )
    if result_ids != expected_ids:
        raise ValueError(
            f"{consumer} report coverage/order differs: expected {expected_ids}, "
            f"got results={result_ids}"
        )
    return ConformanceReport(
        consumer=consumer,
        engine=engine,
        results=tuple(results),
        omissions=(),
    )


def verify_report_paths(
    report_paths: Sequence[Path],
    *,
    required_consumers: frozenset[str] = frozenset(),
) -> tuple[ConformanceReport, ...]:
    suite, suite_cases, expected_cases = load_suite_and_expected()
    reports = tuple(
        validate_report(
            _load_json(path),
            suite=suite,
            suite_cases=suite_cases,
            expected_cases=expected_cases,
        )
        for path in report_paths
    )
    identities = {(report.consumer, report.engine) for report in reports}
    if len(identities) != len(reports):
        raise ValueError("duplicate consumer/engine conformance report")
    present_consumers = {report.consumer for report in reports}
    missing = required_consumers - present_consumers
    if missing:
        raise ValueError(f"missing required conformance reports: {sorted(missing)}")

    unavailable = {
        report.consumer: report.omissions for report in reports if report.omissions
    }
    if unavailable:
        details = ", ".join(
            f"{consumer}={list(case_ids)}" for consumer, case_ids in unavailable.items()
        )
        raise ValueError(
            f"required conformance production adapters unavailable: {details}"
        )

    by_case: dict[str, ReportResult] = {}
    for report in reports:
        for result in report.results:
            previous = by_case.setdefault(result.case_id, result)
            if previous != result:
                raise ValueError(f"cross-platform result differs for {result.case_id}")
    return reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument(
        "--require-consumer",
        action="append",
        default=[],
        choices=sorted(REPORT_CONSUMERS),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reports = verify_report_paths(
        args.reports,
        required_consumers=frozenset(args.require_consumer),
    )
    summary = ", ".join(
        f"{report.consumer}/{report.engine}:{len(report.results)}" for report in reports
    )
    print(f"Reader safety conformance verified: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
