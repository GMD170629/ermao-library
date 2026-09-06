"""Pinned libmobi ABI adapter for runtime Readium Web publications."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import posixpath
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.contracts.reader_safety_policy_generated import (
    ReaderSafetyBudgetName,
    ReaderSafetyRuleId,
    reader_safety_budget,
)
from app.modules.publications.application.ports import (
    PublicationAdapter,
    PublicationSource,
)
from app.modules.publications.application.safety_policy import (
    publication_integrity_failure,
    publication_native_parser_rejection,
    publication_parser_limit,
    publication_resource_limit,
)
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationCorruptError,
    PublicationLink,
    PublicationMarkupError,
    PublicationParserError,
    PublicationResource,
    PublicationResourceNotFoundError,
    PublicationRevision,
    PublicationUnsupportedError,
)
from app.modules.publications.infrastructure.chapter_core import (
    ChapterCore,
    MobiChapterNode,
)
from app.modules.publications.infrastructure.locator_dom import (
    sanitize_css_resource,
    sanitize_markup_resource,
)
from app.modules.publications.infrastructure.snapshot_cache import (
    PublicationSnapshotCache,
    publication_snapshot_weight,
)
from app.modules.publications.infrastructure.source_files import (
    resolve_publication_source,
    select_publication_source_root,
)

_OK = 0
_NOT_FOUND = 11
_BUFFER_TOO_SMALL = 13
_INDEX_NONE = 2**32 - 1
_MARKUP_CATEGORY = 1
_SVG_MEDIA_TYPE = "image/svg+xml"
_MAX_READ_BYTES = 256 * 1024
_MAX_RESOURCE_BYTES = reader_safety_budget(
    ReaderSafetyBudgetName.BINARY_RESOURCE_MAX_BYTES
)
_MAX_MARKUP_RESOURCE_BYTES = reader_safety_budget(
    ReaderSafetyBudgetName.REFLOWABLE_MARKUP_MAX_BYTES
)
_MAX_SOURCE_BYTES = reader_safety_budget(ReaderSafetyBudgetName.ORIGINAL_MAX_BYTES)
_MOBI_FORMATS = frozenset({"mobi", "azw", "azw3", "prc"})
MOBI_NORMALIZATION_IDENTIFIER = "ermao-mobi-core-v1+shuku-locator-dom-v4"


def _base_media_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def _publication_media_type(*, category: int, core_media_type: str | None) -> str:
    # libmobi reconstructs legacy Mobipocket markup as HTML. Some sources retain
    # private prefixes such as ``mbp:pagebreak`` without XML namespace
    # declarations, so advertising these unchanged bytes as XHTML makes XML
    # consumers reject otherwise valid reading content.
    if category == _MARKUP_CATEGORY:
        return "text/html"
    return _base_media_type(core_media_type) or "application/octet-stream"


class _OpenOptions(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("max_read_bytes", ctypes.c_uint32),
        ("max_file_bytes", ctypes.c_uint64),
    ]


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
    book: ctypes.c_void_p
    publication: NormalizedPublication
    resources_by_href: dict[str, _MobiResourceDescriptor]
    reading_order_hrefs: frozenset[str]


def _is_markup_resource(descriptor: _MobiResourceDescriptor) -> bool:
    return descriptor.category == _MARKUP_CATEGORY or (
        _base_media_type(descriptor.media_type) == _SVG_MEDIA_TYPE
    )


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
        library.ermao_mobi_default_options.argtypes = [ctypes.POINTER(_OpenOptions)]
        library.ermao_mobi_default_options.restype = None
        library.ermao_mobi_open.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(_OpenOptions),
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
        options = _OpenOptions()
        self._library.ermao_mobi_default_options(ctypes.byref(options))
        options.max_file_bytes = _MAX_SOURCE_BYTES
        book = ctypes.c_void_p()
        status = self._library.ermao_mobi_open(
            os.fsencode(path),
            ctypes.byref(options),
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
        if name == "drm_protected":
            raise publication_native_parser_rejection(
                ReaderSafetyRuleId.COMMON_DRM_REJECTED,
                parser="libmobi",
                operation=operation,
                reason=name,
            )
        if name in {"limit_exceeded", "out_of_memory"}:
            raise publication_resource_limit(
                ReaderSafetyRuleId.COMMON_PARSER_SNAPSHOT_MEMORY,
                f"libmobi parser memory reservation failed: {name}",
            )
        if name == "unsupported":
            raise publication_native_parser_rejection(
                ReaderSafetyRuleId.COMMON_EXACT_FORMAT_MIME,
                parser="libmobi",
                operation=operation,
                reason=name,
            )
        code = {
            "file_not_found": "PUBLICATION_NOT_FOUND",
            "not_found": "PUBLICATION_RESOURCE_NOT_FOUND",
            "io": "PUBLICATION_READ_FAILED",
            "no_content": "PUBLICATION_STRUCTURE_INVALID",
        }.get(name, "PUBLICATION_PARSE_FAILED")
        raise PublicationParserError(
            code=code, parser="libmobi", operation=operation, reason=name
        )

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

    def copy_resource_type(self, book: ctypes.c_void_p, index: int) -> str | None:
        return self._copy_string(
            self._library.ermao_mobi_copy_resource_media_type,
            book,
            index,
        )

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
            raise publication_resource_limit(
                ReaderSafetyRuleId.COMMON_BINARY_RESOURCE_MAX_BYTES,
                "MOBI-family resource exceeds the runtime limit",
            )
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


def _snapshot(
    core: _MobiCore,
    source_path_value: str,
    source_size: int,
    source_mtime_ns: int,
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
                media_type=_publication_media_type(
                    category=resource_info.category,
                    core_media_type=core.copy_resource_type(book, index),
                ),
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

        chapter_nodes: list[MobiChapterNode] = []
        for index, entry in enumerate(toc_info):
            chapter_href: str | None = None
            if entry.target_resource_index != _INDEX_NONE:
                if not 0 <= entry.target_resource_index < len(descriptors):
                    raise PublicationCorruptError("MOBI directory target is invalid")
                fragment = core.copy_toc_fragment(book, index)
                chapter_href = descriptors[entry.target_resource_index].href + (
                    f"#{fragment}" if fragment else ""
                )
            chapter_nodes.append(
                MobiChapterNode(
                    parent_index=-1
                    if entry.parent_index == _INDEX_NONE
                    else entry.parent_index,
                    title=core.copy_toc_title(book, index) or "",
                    target_href=chapter_href,
                )
            )
        toc = ChapterCore.load().from_mobi(chapter_nodes).table_of_contents()
        publication = NormalizedPublication(
            identifier=f"urn:shuku:mobi:{source_size}:{source_mtime_ns}",
            title=core.copy_metadata(book, 1) or "",
            author=core.copy_metadata(book, 2),
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
        return _MobiSnapshot(
            book=book,
            publication=publication,
            resources_by_href=by_href,
            reading_order_hrefs=frozenset(link.href for link in reading_order),
        )
    except BaseException:
        core.close(book)
        raise


class MobiPublicationAdapter(PublicationAdapter):
    def __init__(self, storage_root: Path, core: _MobiCore | None = None) -> None:
        self._storage_root = storage_root
        self._core = core or load_mobi_core()
        self._cache: PublicationSnapshotCache[_MobiSnapshot] = PublicationSnapshotCache(
            dispose=self._close_snapshot,
        )

    def _close_snapshot(self, snapshot: _MobiSnapshot) -> None:
        if self._core is not None:
            self._core.close(snapshot.book)

    def close(self) -> None:
        self._cache.close()

    def open(self, source: PublicationSource) -> NormalizedPublication:
        with self._snapshot(source) as snapshot:
            return replace(
                snapshot.publication,
                title=snapshot.publication.title or source.title,
                author=snapshot.publication.author or source.author,
            )

    def read_resource(
        self, source: PublicationSource, href: str
    ) -> PublicationResource:
        core = self._require_core(source)
        with self._snapshot(source) as snapshot:
            safe_href = _safe_href(href)
            descriptor = snapshot.resources_by_href.get(safe_href)
            if descriptor is None:
                raise PublicationResourceNotFoundError
            is_markup = _is_markup_resource(descriptor)
            limit = _MAX_MARKUP_RESOURCE_BYTES if is_markup else _MAX_RESOURCE_BYTES
            if descriptor.decoded_length > limit:
                if is_markup:
                    raise publication_parser_limit(
                        ReaderSafetyRuleId.REFLOWABLE_MARKUP_MAX_BYTES,
                        "MOBI-family markup exceeds the size limit",
                    )
                raise publication_resource_limit(
                    ReaderSafetyRuleId.COMMON_BINARY_RESOURCE_MAX_BYTES,
                    "MOBI-family resource exceeds the size limit",
                )
            content = core.read_resource(snapshot.book, descriptor)
            if is_markup:
                # MOBI's native decoder returns authored HTML in memory. Run
                # the shared preparation/sanitization projection before
                # publication, selecting HTML explicitly rather than retrying
                # failed XML. SVG remains strict XML. The original is unchanged.
                try:
                    content = sanitize_markup_resource(
                        content,
                        syntax="html"
                        if _base_media_type(descriptor.media_type) == "text/html"
                        else "xml",
                    )
                except PublicationMarkupError as error:
                    if safe_href in snapshot.reading_order_hrefs:
                        raise publication_integrity_failure(
                            ReaderSafetyRuleId.REFLOWABLE_REQUIRED_READING_ORDER_MARKUP,
                            "required MOBI-family markup cannot be decoded or parsed",
                        ) from error
                    raise publication_integrity_failure(
                        ReaderSafetyRuleId.REFLOWABLE_OPTIONAL_RESOURCE_FAILURE,
                        "optional MOBI-family markup cannot be decoded or parsed",
                        optional=True,
                    ) from error
            elif _base_media_type(descriptor.media_type) == "text/css":
                content = sanitize_css_resource(content)
            return PublicationResource(
                href=safe_href,
                media_type=descriptor.media_type,
                content=content,
                source_mtime=snapshot.publication.revision.source_mtime_ms / 1000,
            )

    @contextmanager
    def _snapshot(self, source: PublicationSource) -> Iterator[_MobiSnapshot]:
        core = self._require_core(source)
        path = resolve_publication_source(
            source.path,
            select_publication_source_root(source.library_root, self._storage_root),
        )
        stat = path.stat()
        if stat.st_size > _MAX_SOURCE_BYTES:
            raise publication_resource_limit(
                ReaderSafetyRuleId.COMMON_ORIGINAL_MAX_BYTES,
                "MOBI-family source exceeds the size limit",
            )
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        with self._cache.lease(
            key,
            lambda: _snapshot(core, *key),
            publication_snapshot_weight(stat.st_size),
        ) as snapshot:
            yield snapshot

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

    def close(self) -> None:
        closed: set[int] = set()
        for adapter in self._adapters.values():
            if id(adapter) in closed:
                continue
            closed.add(id(adapter))
            close = getattr(adapter, "close", None)
            if callable(close):
                close()

    def _adapter(self, source: PublicationSource) -> PublicationAdapter:
        adapter = self._adapters.get(source.source_format)
        if adapter is None:
            raise PublicationUnsupportedError(source.source_format)
        return adapter


@lru_cache(maxsize=1)
def load_mobi_core() -> _MobiCore | None:
    """Load and ABI-check the process-wide pinned libmobi runtime once."""

    return _MobiCore.load()
