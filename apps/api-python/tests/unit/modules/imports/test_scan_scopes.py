import pytest

from app.modules.imports.domain.scan_policy import (
    ScanScope,
    decode_scan_scopes,
    encode_scan_scopes,
    merge_scan_scopes,
)


def test_scope_merge_keeps_shallow_parent_and_recursive_child() -> None:
    scopes = merge_scan_scopes(
        (ScanScope("a"),),
        (
            ScanScope("a/b", True),
            ScanScope("a/b/c"),
            ScanScope("a/b", True),
        ),
    )
    assert scopes == (ScanScope("a"), ScanScope("a/b", True))
    assert decode_scan_scopes(encode_scan_scopes(scopes)) == scopes
    assert merge_scan_scopes(scopes, None) is None
    assert merge_scan_scopes(scopes, (ScanScope("", True),)) == (ScanScope("", True),)


@pytest.mark.parametrize("value", ["../a", "/a", "a//b", "a/../b", "a\\b", "a\x00b"])
def test_scope_rejects_unsafe_paths(value: str) -> None:
    with pytest.raises(ValueError):
        ScanScope(value)
