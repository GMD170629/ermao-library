from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from appv2.platform.auth import PasswordHasher, new_session_token, token_digest
from appv2.platform.config import Settings
from appv2.platform.filesystem import StorageLayout
from appv2.platform.http.models import CamelModel
from appv2.platform.http.ranges import InvalidRange, parse_range_header


class ExampleModel(CamelModel):
    page_size: int
    trace_id: str


def test_http_models_emit_camel_case() -> None:
    model = ExampleModel(page_size=24, trace_id="abc")
    assert model.model_dump(by_alias=True) == {"pageSize": 24, "traceId": "abc"}


@pytest.mark.parametrize(
    ("raw", "start", "end"),
    [
        ("bytes=0-99", 0, 99),
        ("bytes=100-", 100, None),
        ("bytes=-500", None, 500),
    ],
)
def test_parse_single_byte_ranges(raw: str, start: int | None, end: int | None) -> None:
    parsed = parse_range_header(raw)
    assert parsed is not None
    assert (parsed.start, parsed.end) == (start, end)


@pytest.mark.parametrize(
    "raw",
    ["items=0-1", "bytes=2-1", "bytes=1-2,4-5", "bytes=-", "bytes=bad-2"],
)
def test_reject_invalid_ranges(raw: str) -> None:
    with pytest.raises(InvalidRange):
        parse_range_header(raw)


def test_password_hashes_are_salted_and_verified() -> None:
    hasher = PasswordHasher()
    first = hasher.hash("correct horse battery staple")
    second = hasher.hash("correct horse battery staple")
    assert first != second
    assert hasher.verify("correct horse battery staple", first)
    assert not hasher.verify("wrong password", first)


def test_session_digest_is_keyed_and_stable() -> None:
    token = new_session_token()
    assert token_digest(token, "first") == token_digest(token, "first")
    assert token_digest(token, "first") != token_digest(token, "second")


def test_settings_reject_sqlite(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url=SecretStr(f"sqlite:///{tmp_path / 'legacy.db'}"),
            storage_root=tmp_path,
        )


def test_storage_layout_never_uses_legacy_database_directory(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path / "v2")
    layout.ensure()
    assert {path.name for path in layout.root.iterdir()} == {
        "backups",
        "control",
        "conversions",
        "covers",
        "logs",
        "secrets",
        "temp",
    }
    assert not (tmp_path / "database").exists()
    with pytest.raises(ValueError):
        layout.resolve_inside(tmp_path / "outside")
