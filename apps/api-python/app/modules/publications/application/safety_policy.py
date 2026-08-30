"""Generated-policy decision boundary for publication safety findings."""

from __future__ import annotations

from app.contracts.reader_safety_policy_generated import (
    READER_SAFETY_IMPLEMENTATION_FAILURE_CODES,
    ReaderSafetyAction,
    ReaderSafetyErrorCode,
    ReaderSafetyRule,
    ReaderSafetyRuleId,
    reader_safety_rule,
)
from app.modules.publications.domain.model import (
    PublicationParserError,
    PublicationParserLimitError,
    PublicationResourceTooLargeError,
    PublicationSecurityError,
)


def _checked_rule(
    rule_id: ReaderSafetyRuleId,
    *,
    actions: tuple[ReaderSafetyAction, ...],
    error_codes: tuple[ReaderSafetyErrorCode, ...],
) -> ReaderSafetyRule:
    rule = reader_safety_rule(rule_id)
    if rule.action not in actions or rule.error_code not in error_codes:
        raise ValueError(f"{rule_id.value} does not match the requested policy failure")
    return rule


def publication_security_rejection(
    rule_id: ReaderSafetyRuleId,
    message: str,
) -> PublicationSecurityError:
    """Map one generated rejection rule to the sole security-error type."""

    _checked_rule(
        rule_id,
        actions=(ReaderSafetyAction.REJECT_PUBLICATION,),
        error_codes=(ReaderSafetyErrorCode.PUBLICATION_SECURITY_REJECTED,),
    )
    return PublicationSecurityError(message, rule_id=rule_id.value)


def publication_parser_limit(
    rule_id: ReaderSafetyRuleId,
    message: str,
) -> PublicationParserLimitError:
    """Create a parser-budget failure from the generated policy decision."""

    _checked_rule(
        rule_id,
        actions=(ReaderSafetyAction.REJECT_PUBLICATION,),
        error_codes=(ReaderSafetyErrorCode.PUBLICATION_PARSER_LIMIT,),
    )
    return PublicationParserLimitError(message, rule_id=rule_id.value)


def publication_resource_limit(
    rule_id: ReaderSafetyRuleId,
    message: str,
) -> PublicationResourceTooLargeError:
    """Create an admission/resource limit failure from the generated policy."""

    rule = _checked_rule(
        rule_id,
        actions=(
            ReaderSafetyAction.BLOCK_RESOURCE,
            ReaderSafetyAction.REJECT_PUBLICATION,
        ),
        error_codes=(
            ReaderSafetyErrorCode.PUBLICATION_RESOURCE_BLOCKED,
            ReaderSafetyErrorCode.PUBLICATION_TOO_LARGE,
        ),
    )
    error_code = rule.error_code
    if error_code is None:  # Guarded by _checked_rule; keeps the boundary explicit.
        raise ValueError(f"{rule_id.value} has no generated error code")
    return PublicationResourceTooLargeError(
        message,
        code=error_code.value,
        rule_id=rule_id.value,
    )


def publication_native_parser_rejection(
    rule_id: ReaderSafetyRuleId,
    *,
    parser: str,
    operation: str,
    reason: str,
) -> PublicationParserError:
    """Map a native parser fact to a generated non-security rejection code."""

    rule = _checked_rule(
        rule_id,
        actions=(ReaderSafetyAction.REJECT_PUBLICATION,),
        error_codes=(ReaderSafetyErrorCode.PUBLICATION_DRM_UNSUPPORTED,),
    )
    error_code = rule.error_code
    if error_code is None:  # Guarded by _checked_rule.
        raise ValueError(f"{rule_id.value} has no generated error code")
    return PublicationParserError(
        code=error_code.value,
        parser=parser,
        operation=operation,
        reason=reason,
        rule_id=rule_id.value,
    )


def publication_native_parser_implementation_failure(
    rule_id: ReaderSafetyRuleId,
    *,
    parser: str,
    operation: str,
    reason: str,
) -> PublicationParserError:
    """Report an engine limitation without misclassifying source content."""

    error_code = ReaderSafetyErrorCode.ENGINE_POLICY_ALGORITHM_UNSUPPORTED
    if error_code not in READER_SAFETY_IMPLEMENTATION_FAILURE_CODES:
        raise ValueError("generated Reader safety implementation failure is missing")
    return PublicationParserError(
        code=error_code.value,
        parser=parser,
        operation=operation,
        reason=reason,
        rule_id=rule_id.value,
    )


__all__ = [
    "publication_native_parser_implementation_failure",
    "publication_native_parser_rejection",
    "publication_parser_limit",
    "publication_resource_limit",
    "publication_security_rejection",
]
