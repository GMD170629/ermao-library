"""Target Library organization modes for ADR 0018 (no AUDIOBOOK)."""

from __future__ import annotations

from enum import Enum


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
    except ValueError:
        return OrganizationModeViolationCode.UNSUPPORTED_MODE
