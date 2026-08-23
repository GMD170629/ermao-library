from __future__ import annotations

import pytest

from app.modules.library.domain.readable_resource_states import (
    ResourceEnablementState,
    ResourceImportState,
    meets_minimum_ready_assets,
    resource_is_openable,
)


@pytest.mark.parametrize(
    ("enablement", "import_state", "expected"),
    (
        (ResourceEnablementState.ENABLED, ResourceImportState.READY, True),
        (ResourceEnablementState.DISABLED, ResourceImportState.READY, False),
        (ResourceEnablementState.ENABLED, ResourceImportState.PENDING, False),
        (ResourceEnablementState.ENABLED, ResourceImportState.FAILED, False),
        (ResourceEnablementState.DISABLED, ResourceImportState.FAILED, False),
    ),
)
def test_resource_is_openable(
    enablement: ResourceEnablementState,
    import_state: ResourceImportState,
    expected: bool,
) -> None:
    assert (
        resource_is_openable(enablement=enablement, import_state=import_state)
        is expected
    )


def test_meets_minimum_ready_assets() -> None:
    assert (
        meets_minimum_ready_assets(ready_asset_count=0, minimum_ready_assets=1) is False
    )
    assert (
        meets_minimum_ready_assets(ready_asset_count=1, minimum_ready_assets=1) is True
    )
    assert (
        meets_minimum_ready_assets(ready_asset_count=3, minimum_ready_assets=2) is True
    )
    assert (
        meets_minimum_ready_assets(ready_asset_count=1, minimum_ready_assets=2) is False
    )


def test_meets_minimum_ready_assets_rejects_invalid_minimum() -> None:
    with pytest.raises(ValueError, match="minimum_ready_assets"):
        meets_minimum_ready_assets(ready_asset_count=1, minimum_ready_assets=0)
