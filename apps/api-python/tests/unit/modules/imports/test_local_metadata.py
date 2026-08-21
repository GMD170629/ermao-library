import pytest

from app.contracts.local_metadata import (
    DEFAULT_LOCAL_METADATA_PRIORITY,
    validate_local_metadata_priority,
)

def test_default_priority_is_opf_then_embedded_then_path() -> None:
    assert DEFAULT_LOCAL_METADATA_PRIORITY == (
        "SIDECAR_OPF",
        "EMBEDDED",
        "PATH",
    )


@pytest.mark.parametrize(
    "value",
    (
        ["SIDECAR_OPF", "EMBEDDED"],
        ["SIDECAR_OPF", "EMBEDDED", "EMBEDDED"],
        ["SIDECAR_OPF", "EMBEDDED", "REMOTE"],
    ),
)
def test_priority_validation_requires_each_local_source_once(value: list[str]) -> None:
    with pytest.raises((TypeError, ValueError)):
        validate_local_metadata_priority(value)


def test_priority_validation_normalizes_source_names() -> None:
    assert validate_local_metadata_priority(
        ["sidecar_opf", "embedded", "path"]
    ) == DEFAULT_LOCAL_METADATA_PRIORITY
