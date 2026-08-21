"""ReadableResource enablement/import states and readiness policy."""

from __future__ import annotations

from enum import Enum


class ResourceEnablementState(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class ResourceImportState(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"


class AssetImportState(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"


class AssetRole(str, Enum):
    PRIMARY = "PRIMARY"
    TRACK = "TRACK"
    PAGE = "PAGE"
    SIDECAR = "SIDECAR"
    SUPPLEMENT = "SUPPLEMENT"


def resource_is_openable(
    *,
    enablement: ResourceEnablementState,
    import_state: ResourceImportState,
) -> bool:
    return (
        enablement is ResourceEnablementState.ENABLED
        and import_state is ResourceImportState.READY
    )


def meets_minimum_ready_assets(
    *,
    ready_asset_count: int,
    minimum_ready_assets: int,
) -> bool:
    if minimum_ready_assets < 1:
        raise ValueError("minimum_ready_assets must be >= 1")
    return ready_asset_count >= minimum_ready_assets
