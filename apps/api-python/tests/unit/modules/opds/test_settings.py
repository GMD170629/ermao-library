import pytest

from app.modules.opds.application.settings import (
    OpdsPublicBaseUrlInvalid,
    OpdsPublicBaseUrlRequired,
    normalize_opds_public_base_url,
    resolve_opds_settings,
    validate_opds_activation,
)


def test_database_settings_control_opds_availability() -> None:
    disabled = resolve_opds_settings(
        False,
        stored_public_base_url="https://books.example.com/",
    )
    enabled = resolve_opds_settings(
        True,
        stored_public_base_url="https://books.example.com/",
    )

    assert disabled.enabled is False
    assert disabled.catalog_url is None
    assert enabled.enabled is True
    assert enabled.catalog_url == "https://books.example.com/opds/v1.2/catalog"


def test_opds_cannot_activate_without_public_base_url() -> None:
    with pytest.raises(OpdsPublicBaseUrlRequired):
        validate_opds_activation(True, None)

    snapshot = resolve_opds_settings(True, stored_public_base_url=None)
    assert snapshot.configured is False
    assert snapshot.enabled is False


@pytest.mark.parametrize(
    "public_url",
    [
        "catalog.example.com",
        "https://user:password@catalog.example.com",
        "https://catalog.example.com?token=secret",
        "https://catalog.example.com/#fragment",
    ],
)
def test_public_url_rejects_unsafe_values(public_url: str) -> None:
    with pytest.raises(OpdsPublicBaseUrlInvalid):
        normalize_opds_public_base_url(public_url)


def test_public_url_accepts_http_and_https() -> None:
    assert normalize_opds_public_base_url("http://catalog.example.com/") == (
        "http://catalog.example.com"
    )
    assert normalize_opds_public_base_url("https://books.example.com/root/") == (
        "https://books.example.com/root"
    )
    assert normalize_opds_public_base_url("http://127.0.0.1:8000") == (
        "http://127.0.0.1:8000"
    )
