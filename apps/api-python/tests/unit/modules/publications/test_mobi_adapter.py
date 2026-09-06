from __future__ import annotations

import ctypes
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest

from app.contracts.publication_sources import PublicationSource
from app.contracts.reader_safety_policy_generated import ReaderSafetyRuleId
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationIntegrityError,
    PublicationLink,
    PublicationMarkupError,
    PublicationParserError,
    PublicationResourceBlockedError,
    PublicationResourceTooLargeError,
    PublicationRevision,
)
from app.modules.publications.infrastructure.mobi_adapter import (
    MobiPublicationAdapter,
    _MobiCore,
    _MobiResourceDescriptor,
    _MobiSnapshot,
    _publication_media_type,
)


class _StatusLibrary:
    def __init__(self, name: str) -> None:
        self._name = name

    def ermao_mobi_status_name(self, _status: int) -> bytes:
        return self._name.encode("ascii")


def _core_for_status(name: str) -> _MobiCore:
    core = object.__new__(_MobiCore)
    core._library = cast(ctypes.CDLL, _StatusLibrary(name))
    return core


def test_native_unsupported_uses_generated_format_capability_rule() -> None:
    with pytest.raises(PublicationParserError) as failure:
        _core_for_status("unsupported").require_ok(1, "open")

    assert failure.value.code == "PUBLICATION_MIME_MISMATCH"
    assert failure.value.rule_id == ReaderSafetyRuleId.COMMON_EXACT_FORMAT_MIME.value


@pytest.mark.parametrize("status", ["limit_exceeded", "out_of_memory"])
def test_native_memory_limit_uses_generated_snapshot_budget_rule(status: str) -> None:
    with pytest.raises(PublicationResourceTooLargeError) as failure:
        _core_for_status(status).require_ok(1, "open")

    assert failure.value.code == "PUBLICATION_TOO_LARGE"
    assert (
        failure.value.rule_id == ReaderSafetyRuleId.COMMON_PARSER_SNAPSHOT_MEMORY.value
    )


@pytest.mark.parametrize(
    ("category", "core_media_type", "expected"),
    [
        (1, None, "text/html"),
        (3, None, "application/octet-stream"),
        (3, "text/css; charset=utf-8", "text/css"),
    ],
)
def test_missing_and_parameterized_media_types_remain_decoder_inputs(
    category: int,
    core_media_type: str | None,
    expected: str,
) -> None:
    assert (
        _publication_media_type(
            category=category,
            core_media_type=core_media_type,
        )
        == expected
    )


def test_missing_native_media_type_is_not_rejected() -> None:
    core = object.__new__(_MobiCore)
    core._library = cast(
        ctypes.CDLL,
        SimpleNamespace(ermao_mobi_copy_resource_media_type=object()),
    )

    with patch.object(_MobiCore, "_copy_string", return_value=None):
        assert core.copy_resource_type(ctypes.c_void_p(), 0) is None


class _ReadCore:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def read_resource(
        self, _book: ctypes.c_void_p, _descriptor: _MobiResourceDescriptor
    ) -> bytes:
        return self.content


def _source(tmp_path: Path) -> PublicationSource:
    path = tmp_path / "book.mobi"
    path.write_bytes(b"mobi")
    return PublicationSource(
        resource_id="mobi-resource",
        asset_id="mobi-asset",
        source_format="mobi",
        path=str(path),
        size_bytes=path.stat().st_size,
        mtime_ms=0,
        title="MOBI",
        author=None,
        library_root=None,
    )


def _snapshot_for(
    descriptor: _MobiResourceDescriptor,
    *,
    required: bool,
) -> _MobiSnapshot:
    publication = NormalizedPublication(
        identifier="urn:test:mobi",
        title="MOBI",
        author=None,
        language=None,
        reading_progression="ltr",
        revision=PublicationRevision(
            source_size_bytes=4,
            source_mtime_ms=0,
            parser="test",
            normalization="test",
        ),
        reading_order=(
            PublicationLink(
                href=descriptor.href,
                media_type=descriptor.media_type,
            ),
        )
        if required
        else (),
        resources=()
        if required
        else (
            PublicationLink(
                href=descriptor.href,
                media_type=descriptor.media_type,
            ),
        ),
        toc=(),
    )
    return _MobiSnapshot(
        book=ctypes.c_void_p(),
        publication=publication,
        resources_by_href={descriptor.href: descriptor},
        reading_order_hrefs=frozenset({descriptor.href} if required else set()),
    )


def _patched_snapshot(snapshot: _MobiSnapshot):
    @contextmanager
    def lease(_source: PublicationSource):
        yield snapshot

    return lease


def test_named_svg_resource_uses_markup_sanitizer_before_delivery(
    tmp_path: Path,
) -> None:
    descriptor = _MobiResourceDescriptor(
        index=0,
        href="images/cover.svg",
        media_type="image/svg+xml; charset=utf-8",
        category=3,
        decoded_length=82,
    )
    adapter = MobiPublicationAdapter(
        tmp_path,
        core=cast(
            _MobiCore,
            _ReadCore(
                b"<svg xmlns='http://www.w3.org/2000/svg'><script>bad</script>"
                b"<path d='ok'/></svg>"
            ),
        ),
    )
    source = _source(tmp_path)
    snapshot = _snapshot_for(descriptor, required=False)
    with patch.object(adapter, "_snapshot", _patched_snapshot(snapshot)):
        result = adapter.read_resource(source, descriptor.href)

    assert b"<script" not in result.content
    assert b"path" in result.content
    assert result.media_type == descriptor.media_type


def test_legacy_html_remains_readable_and_sanitized_without_rewriting_source(
    tmp_path: Path,
) -> None:
    content = (
        b"<html><head><title>Legacy book</title></head><body>"
        b"<!-- authored comment --><mbp:pagebreak/><p id=chapter>Readable &amp; safe"
        b"<br>next line<script>bad()</script><img src='https://invalid.test/pixel' "
        b"onerror='bad()'><a href='javascript:bad()'>link</a>"
        b"<svg><script>bad()</script><path d='M0 0'/></svg></body></html>"
    )
    descriptor = _MobiResourceDescriptor(
        index=0,
        href="part00000.html",
        media_type="text/html",
        category=1,
        decoded_length=len(content),
    )
    adapter = MobiPublicationAdapter(tmp_path, core=cast(_MobiCore, _ReadCore(content)))
    source = _source(tmp_path)
    before = Path(source.path).read_bytes()
    snapshot = _snapshot_for(descriptor, required=True)
    with patch.object(adapter, "_snapshot", _patched_snapshot(snapshot)):
        result = adapter.read_resource(source, descriptor.href)

    assert result.media_type == "text/html"
    assert b"Readable &amp; safe" in result.content
    assert b"next line" in result.content
    assert b"mbp:pagebreak" in result.content
    assert b"path" in result.content
    for forbidden in (b"<script", b"onerror", b"javascript:", b"invalid.test"):
        assert forbidden not in result.content
    assert Path(source.path).read_bytes() == before
    assert list(tmp_path.iterdir()) == [Path(source.path)]


@pytest.mark.parametrize(
    ("required", "error_type", "rule_id"),
    [
        (
            False,
            PublicationResourceBlockedError,
            ReaderSafetyRuleId.REFLOWABLE_OPTIONAL_RESOURCE_FAILURE.value,
        ),
        (
            True,
            PublicationIntegrityError,
            ReaderSafetyRuleId.REFLOWABLE_REQUIRED_READING_ORDER_MARKUP.value,
        ),
    ],
)
def test_malformed_named_svg_keeps_optional_or_required_generated_outcome(
    tmp_path: Path,
    required: bool,
    error_type: type[Exception],
    rule_id: str,
) -> None:
    descriptor = _MobiResourceDescriptor(
        index=0,
        href="images/body.svg" if required else "images/cover.svg",
        media_type="image/svg+xml",
        category=3,
        decoded_length=12,
    )
    adapter = MobiPublicationAdapter(
        tmp_path,
        core=cast(_MobiCore, _ReadCore(b"<svg>")),
    )
    source = _source(tmp_path)
    snapshot = _snapshot_for(descriptor, required=required)
    with (
        patch.object(adapter, "_snapshot", _patched_snapshot(snapshot)),
        patch(
            "app.modules.publications.infrastructure.mobi_adapter.sanitize_markup_resource",
            side_effect=PublicationMarkupError("malformed SVG"),
        ),
        pytest.raises(error_type) as failure,
    ):
        adapter.read_resource(source, descriptor.href)

    assert failure.value.rule_id == rule_id
