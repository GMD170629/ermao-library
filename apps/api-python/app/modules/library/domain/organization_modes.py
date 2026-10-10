"""Target Library organization modes for ADR 0018 (no AUDIOBOOK)."""

from __future__ import annotations

from enum import Enum

from app.core.exception_diagnostics import capture_exception


class TargetLibraryOrganizationMode(str, Enum):
    FLAT = "FLAT"
    VOLUMES = "VOLUMES"


class OrganizationModeViolationCode(str, Enum):
    UNSUPPORTED_MODE = "UNSUPPORTED_MODE"
    MODE_SWITCH_REQUIRES_EMPTY_SOURCE_TREE = "MODE_SWITCH_REQUIRES_EMPTY_SOURCE_TREE"


def parse_target_organization_mode(
    value: str,
) -> TargetLibraryOrganizationMode | OrganizationModeViolationCode:
    try:
        return TargetLibraryOrganizationMode(value)
    except ValueError as _caught_error:
        # diagnostics-control-flow: enum membership is the domain validation result; the caller handles UNSUPPORTED_MODE.
        capture_exception(_caught_error)
        return OrganizationModeViolationCode.UNSUPPORTED_MODE
