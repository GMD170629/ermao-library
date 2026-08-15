"""Pinned libmobi ABI adapter for runtime Readium Web publications."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import posixpath
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.modules.publications.application.ports import (
    PublicationAdapter,
    PublicationSource,
)
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationCorruptError,
    PublicationLink,
    PublicationResource,
    PublicationResourceNotFoundError,
    PublicationRevision,
    PublicationTocEntry,
    PublicationUnsupportedError,
)
from app.modules.publications.infrastructure.source_files import (
    resolve_publication_source,
)

_OK = 0
_NOT_FOUND = 11
_BUFFER_TOO_SMALL = 13
_INDEX_NONE = 2**32 - 1
_MAX_READ_BYTES = 256 * 1024
_MAX_RESOURCE_BYTES = 64 * 1024 * 1024
_MOBI_FORMATS = frozenset({"mobi", "azw", "azw3", "prc"})
MOBI_NORMALIZATION_IDENTIFIER = "ermao-mobi-core-v1+shuku-locator-dom-v2"


class _BookInfo(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("format", ctypes.c_uint32),
        ("reading_direction", ctypes.c_uint32),
        ("resource_count", ctypes.c_uint32),
        ("reading_order_count", ctypes.c_uint32),
        ("toc_count", ctypes.c_uint32),
        ("warning_count", ctypes.c_uint32),
        ("cover_resource_index", ctypes.c_uint32),
    ]


class _ResourceInfo(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("category", ctypes.c_uint32),
        ("source_uid", ctypes.c_uint64),
        ("decoded_length", ctypes.c_uint64),
    ]


class _TocInfo(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("parent_index", ctypes.c_uint32),
        ("target_resource_index", ctypes.c_uint32),
    ]


@dataclass(frozen=True, slots=True)
class _MobiResourceDescriptor:
    index: int
    href: str
    media_type: str
    category: int
    decoded_length: int


@dataclass(frozen=True, slots=True)
class _MobiSnapshot:
    publication: NormalizedPublication
    resources_by_href: dict[str, _MobiResourceDescriptor]


class _MobiCore:
    def __init__(self, path: str) -> None:
        self._library = ctypes.CDLL(path)
        self._configure()
        if self._library.ermao_mobi_abi_version() != 1:
            raise PublicationUnsupportedError("unsupported libmobi ABI")

    @classmethod
    def load(cls) -> _MobiCore | None:
        configured = os.environ.get("ERMAO_MOBI_CORE_LIBRARY")
        candidates = [
            configured,
            ctypes.util.find_library("ermao_mobi_core"),
            "/usr/local/lib/libermao_mobi_core.so",
            "/usr/local/lib/libermao_mobi_core.dylib",
        ]
        for candidate in candidates:
            if not candidate:
                continue
            try:
                return cls(candidate)
            except OSError:
                continue
        return None

    def _configure(self) -> None:
        library = self._library
        library.ermao_mobi_abi_version.restype = ctypes.c_uint32
        library.ermao_mobi_parser_identifier.restype = ctypes.c_char_p
        library.ermao_mobi_normalization_identifier.restype = ctypes.c_char_p
        library.ermao_mobi_status_name.argtypes = [ctypes.c_int]
        library.ermao_mobi_status_name.restype = ctypes.c_char_p
        library.ermao_mobi_open.argtypes = [
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.ermao_mobi_open.restype = ctypes.c_int
        library.ermao_mobi_close.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        library.ermao_mobi_get_book_info.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_BookInfo),
        ]
        library.ermao_mobi_get_book_info.restype = ctypes.c_int
        library.ermao_mobi_copy_metadata.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        library.ermao_mobi_copy_metadata.restype = ctypes.c_int
        library.ermao_mobi_get_resource_info.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(_ResourceInfo),
        ]
        library.ermao_mobi_get_resource_info.restype = ctypes.c_int
        for function_name in (
            "ermao_mobi_copy_resource_source_name",
            "ermao_mobi_copy_resource_media_type",
            "ermao_mobi_copy_toc_title",
            "ermao_mobi_copy_toc_fragment",
        ):
            function = getattr(library, function_name)
            function.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_uint32),
            ]
            function.restype = ctypes.c_int
        library.ermao_mobi_reading_order_resource_index.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        library.ermao_mobi_reading_order_resource_index.restype = ctypes.c_int
        library.ermao_mobi_get_toc_info.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(_TocInfo),
        ]
        library.ermao_mobi_get_toc_info.restype = ctypes.c_int
        library.ermao_mobi_read_resource.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        library.ermao_mobi_read_resource.restype = ctypes.c_int

    @property
    def parser_identifier(self) -> str:
        return self._library.ermao_mobi_parser_identifier().decode("utf-8")

    @property
    def normalization_identifier(self) -> str:
        return self._library.ermao_mobi_normalization_identifier().decode("utf-8")

    def open(self, path: Path) -> ctypes.c_void_p:
        book = ctypes.c_void_p()
        status = self._library.ermao_mobi_open(
            os.fsencode(path),
            None,
            ctypes.byref(book),
        )
        self.require_ok(status, "open")
        return book

    def close(self, book: ctypes.c_void_p) -> None:
        self._library.ermao_mobi_close(ctypes.byref(book))

    def require_ok(self, status: int, operation: str) -> None:
        if status == _OK:
            return
        name = self._library.ermao_mobi_status_name(status).decode("ascii", "replace")
        if name in {"unsupported", "drm_protected", "limit_exceeded"}:
            raise PublicationUnsupportedError(name)
        raise PublicationCorruptError(f"libmobi {operation} failed: {name}")

    def book_info(self, book: ctypes.c_void_p) -> _BookInfo:
        result = _BookInfo(struct_size=ctypes.sizeof(_BookInfo))
        self.require_ok(
            self._library.ermao_mobi_get_book_info(book, ctypes.byref(result)),
            "book info",
        )
        return result

    def resource_info(self, book: ctypes.c_void_p, index: int) -> _ResourceInfo:
        result = _ResourceInfo(struct_size=ctypes.sizeof(_ResourceInfo))
        self.require_ok(
            self._library.ermao_mobi_get_resource_info(
                book, index, ctypes.byref(result)
            ),
            "resource info",
        )
        return result

    def toc_info(self, book: ctypes.c_void_p, index: int) -> _TocInfo:
        result = _TocInfo(struct_size=ctypes.sizeof(_TocInfo))
        self.require_ok(
            self._library.ermao_mobi_get_toc_info(book, index, ctypes.byref(result)),
            "TOC info",
        )
        return result

    def reading_order_index(self, book: ctypes.c_void_p, position: int) -> int:
        result = ctypes.c_uint32()
        self.require_ok(
            self._library.ermao_mobi_reading_order_resource_index(
                book,
                position,
                ctypes.byref(result),
            ),
            "reading order",
        )
        return int(result.value)

    def copy_metadata(self, book: ctypes.c_void_p, field: int) -> str | None:
        return self._copy_string(self._library.ermao_mobi_copy_metadata, book, field)

    def copy_resource_name(self, book: ctypes.c_void_p, index: int) -> str:
        value = self._copy_string(
            self._library.ermao_mobi_copy_resource_source_name,
            book,
            index,
        )
        if value is None:
            raise PublicationCorruptError("libmobi resource name is missing")
        return value

    def copy_resource_type(self, book: ctypes.c_void_p, index: int) -> str:
        value = self._copy_string(
            self._library.ermao_mobi_copy_resource_media_type,
            book,
            index,
        )
        if value is None:
            raise PublicationCorruptError("libmobi resource type is missing")
        return value

    def copy_toc_title(self, book: ctypes.c_void_p, index: int) -> str | None:
        return self._copy_string(self._library.ermao_mobi_copy_toc_title, book, index)

    def copy_toc_fragment(self, book: ctypes.c_void_p, index: int) -> str | None:
        return self._copy_string(
            self._library.ermao_mobi_copy_toc_fragment, book, index
        )

    def _copy_string(
        self,
        function: Callable[..., int],
        book: ctypes.c_void_p,
        index: int,
    ) -> str | None:
        required = ctypes.c_uint32()
        status = function(book, index, None, 0, ctypes.byref(required))
        if status == _NOT_FOUND:
            return None
        if status != _BUFFER_TOO_SMALL or required.value == 0:
            self.require_ok(status, "copy string")
        buffer = ctypes.create_string_buffer(required.value)
        self.require_ok(
            function(book, index, buffer, required.value, ctypes.byref(required)),
            "copy string",
        )
        return buffer.value.decode("utf-8")

    def read_resource(
        self,
        book: ctypes.c_void_p,
        descriptor: _MobiResourceDescriptor,
    ) -> bytes:
        if descriptor.decoded_length > _MAX_RESOURCE_BYTES:
            raise PublicationUnsupportedError("resource exceeds runtime limit")
        output = bytearray()
        buffer = ctypes.create_string_buffer(_MAX_READ_BYTES)
        offset = 0
        while offset < descriptor.decoded_length:
            requested = min(_MAX_READ_BYTES, descriptor.decoded_length - offset)
            read = ctypes.c_uint32()
            self.require_ok(
                self._library.ermao_mobi_read_resource(
                    book,
                    descriptor.index,
                    offset,
                    buffer,
                    requested,
                    ctypes.byref(read),
                ),
                "resource read",
            )
            if read.value == 0:
                raise PublicationCorruptError("libmobi resource ended early")
            output.extend(buffer.raw[: read.value])
            offset += read.value
        return bytes(output)


def _safe_href(value: str) -> str:
    split = urlsplit(value)
    decoded = unquote(split.path)
    normalized = posixpath.normpath(decoded)
    if (
        split.scheme
        or split.netloc
        or split.query
        or not normalized
        or normalized in {".", ".."}
        or normalized.startswith(("../", "/"))
        or "\\" in normalized
    ):
        raise PublicationCorruptError("libmobi produced an unsafe virtual href")
    return normalized


@lru_cache(maxsize=32)
def _snapshot(
    core: _MobiCore,
    source_path_value: str,
    source_size: int,
    source_mtime_ns: int,
    fallback_title: str,
    fallback_author: str | None,
) -> _MobiSnapshot:
    source_path = Path(source_path_value)
    book = core.open(source_path)
    try:
        info = core.book_info(book)
        descriptors: list[_MobiResourceDescriptor] = []
        by_href: dict[str, _MobiResourceDescriptor] = {}
        for index in range(info.resource_count):
            resource_info = core.resource_info(book, index)
            href = _safe_href(core.copy_resource_name(book, index))
            if href in by_href:
                raise PublicationCorruptError(
                    "libmobi produced duplicate virtual hrefs"
                )
            descriptor = _MobiResourceDescriptor(
                index=index,
                href=href,
                media_type=core.copy_resource_type(book, index),
                category=resource_info.category,
                decoded_length=resource_info.decoded_length,
            )
            descriptors.append(descriptor)
            by_href[href] = descriptor
        reading_indices = [
            core.reading_order_index(book, position)
            for position in range(info.reading_order_count)
        ]
        reading_set = set(reading_indices)
        reading_order = tuple(
            PublicationLink(
                href=descriptors[index].href,
                media_type=descriptors[index].media_type,
            )
            for index in reading_indices
        )
        if not reading_order:
            raise PublicationCorruptError("libmobi reading order is empty")
        resources = tuple(
            PublicationLink(
                href=descriptor.href,
                media_type=descriptor.media_type,
                rel=("cover",) if descriptor.index == info.cover_resource_index else (),
            )
            for descriptor in descriptors
            if descriptor.index not in reading_set
        )
        toc_info = [core.toc_info(book, index) for index in range(info.toc_count)]

        def toc_node(index: int) -> PublicationTocEntry | None:
            entry = toc_info[index]
            if entry.target_resource_index == _INDEX_NONE:
                return None
            target = descriptors[entry.target_resource_index]
            fragment = core.copy_toc_fragment(book, index)
            href = target.href + (f"#{fragment}" if fragment else "")
            children = tuple(
                child
                for child_index, child_info in enumerate(toc_info)
                if child_info.parent_index == index
                for child in [toc_node(child_index)]
                if child is not None
            )
            return PublicationTocEntry(
                href=href,
                title=core.copy_toc_title(book, index) or target.href,
                children=children,
            )

        toc = tuple(
            entry
            for index, entry_info in enumerate(toc_info)
            if entry_info.parent_index == _INDEX_NONE
            for entry in [toc_node(index)]
            if entry is not None
        )
        publication = NormalizedPublication(
            identifier=f"urn:shuku:mobi:{source_size}:{source_mtime_ns}",
            title=core.copy_metadata(book, 1) or fallback_title,
            author=core.copy_metadata(book, 2) or fallback_author,
            language=core.copy_metadata(book, 4),
            reading_progression="rtl" if info.reading_direction == 2 else "ltr",
            revision=PublicationRevision(
                source_size_bytes=source_size,
                source_mtime_ms=source_mtime_ns // 1_000_000,
                parser=core.parser_identifier,
                normalization=MOBI_NORMALIZATION_IDENTIFIER,
            ),
            reading_order=reading_order,
            resources=resources,
            toc=toc,
        )
        return _MobiSnapshot(publication=publication, resources_by_href=by_href)
    finally:
        core.close(book)


class MobiPublicationAdapter(PublicationAdapter):
    def __init__(self, storage_root: Path, core: _MobiCore | None = None) -> None:
        self._storage_root = storage_root
        self._core = core or load_mobi_core()

    def open(self, source: PublicationSource) -> NormalizedPublication:
        return self._snapshot(source).publication

    def read_resource(
        self,
        source: PublicationSource,
        href: str,
    ) -> PublicationResource:
        core = self._require_core(source)
        snapshot = self._snapshot(source)
        safe_href = _safe_href(href)
        descriptor = snapshot.resources_by_href.get(safe_href)
        if descriptor is None:
            raise PublicationResourceNotFoundError
        source_path = resolve_publication_source(source.path, self._storage_root)
        book = core.open(source_path)
        try:
            content = core.read_resource(book, descriptor)
        finally:
            core.close(book)
        return PublicationResource(
            href=safe_href,
            media_type=descriptor.media_type,
            content=content,
            source_mtime=source_path.stat().st_mtime,
        )

    def _snapshot(self, source: PublicationSource) -> _MobiSnapshot:
        core = self._require_core(source)
        source_path = resolve_publication_source(source.path, self._storage_root)
        stat_result = source_path.stat()
        return _snapshot(
            core,
            str(source_path),
            stat_result.st_size,
            stat_result.st_mtime_ns,
            source.title,
            source.author,
        )

    def _require_core(self, source: PublicationSource) -> _MobiCore:
        if source.source_format not in _MOBI_FORMATS:
            raise PublicationUnsupportedError(source.source_format)
        if self._core is None:
            raise PublicationUnsupportedError("libmobi runtime is unavailable")
        return self._core


class CompositePublicationAdapter(PublicationAdapter):
    def __init__(self, adapters: dict[str, PublicationAdapter]) -> None:
        self._adapters = dict(adapters)

    def open(self, source: PublicationSource) -> NormalizedPublication:
        return self._adapter(source).open(source)

    def read_resource(
        self,
        source: PublicationSource,
        href: str,
    ) -> PublicationResource:
        return self._adapter(source).read_resource(source, href)

    def _adapter(self, source: PublicationSource) -> PublicationAdapter:
        adapter = self._adapters.get(source.source_format)
        if adapter is None:
            raise PublicationUnsupportedError(source.source_format)
        return adapter


@lru_cache(maxsize=1)
def load_mobi_core() -> _MobiCore | None:
    """Load and ABI-check the process-wide pinned libmobi runtime once."""

    return _MobiCore.load()
