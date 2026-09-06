"""FFI adapter for the single, renderer-independent chapter implementation."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from app.modules.publications.domain.model import (
    PublicationReadError,
    PublicationStructureError,
    PublicationTocEntry,
)


@dataclass(frozen=True, slots=True)
class ChapterEntry:
    index: int
    parent_index: int
    key: str
    title: str
    href: str | None
    source_start: int
    source_end: int
    content_start: int


@dataclass(frozen=True, slots=True)
class ChapterProjection:
    entries: tuple[ChapterEntry, ...]
    text: bytes = b""

    def table_of_contents(self) -> tuple[PublicationTocEntry, ...]:
        children: dict[int, list[ChapterEntry]] = {}
        for entry in self.entries:
            children.setdefault(entry.parent_index, []).append(entry)

        def nodes(parent: int) -> tuple[PublicationTocEntry, ...]:
            return tuple(
                PublicationTocEntry(
                    href=entry.href,
                    title=entry.title,
                    navigation_key=entry.key,
                    children=nodes(entry.index),
                )
                for entry in children.get(parent, ())
            )

        return nodes(-1)


@dataclass(frozen=True, slots=True)
class XmlChapterEvent:
    kind: int
    name: str = ""
    text: str = ""
    attributes: tuple[tuple[str, str], ...] = ()
    target_href: str | None = None


@dataclass(frozen=True, slots=True)
class MobiChapterNode:
    parent_index: int
    title: str
    target_href: str | None


def xml_chapter_events(
    root: ElementTree.Element,
    target: Callable[[ElementTree.Element], str | None],
) -> Iterator[XmlChapterEvent]:
    """Forward parsed XML facts, including inline title text and mixed-content tails."""
    yield XmlChapterEvent(
        1,
        name=root.tag.rsplit("}", 1)[-1],
        attributes=tuple(
            (key.rsplit("}", 1)[-1], value) for key, value in root.attrib.items()
        ),
        target_href=target(root),
    )
    if root.text:
        yield XmlChapterEvent(2, text=root.text)
    for child in root:
        yield from xml_chapter_events(child, target)
        if child.tail:
            yield XmlChapterEvent(2, text=child.tail)
    yield XmlChapterEvent(3, name=root.tag.rsplit("}", 1)[-1])


class _Attribute(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p), ("value", ctypes.c_char_p)]


class _Event(ctypes.Structure):
    _fields_ = [
        ("kind", ctypes.c_uint32),
        ("name", ctypes.c_char_p),
        ("text", ctypes.c_char_p),
        ("attributes", ctypes.POINTER(_Attribute)),
        ("attribute_count", ctypes.c_uint32),
        ("target_href", ctypes.c_char_p),
    ]


class _MobiNode(ctypes.Structure):
    _fields_ = [
        ("parent_index", ctypes.c_int32),
        ("title", ctypes.c_char_p),
        ("target_href", ctypes.c_char_p),
    ]


class _Entry(ctypes.Structure):
    index: int
    parent_index: int
    navigable: int
    key: bytes
    title: bytes
    href: bytes | None
    source_start: int
    source_end: int
    content_start: int
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("parent_index", ctypes.c_int32),
        ("navigable", ctypes.c_uint32),
        ("key", ctypes.c_char_p),
        ("title", ctypes.c_char_p),
        ("href", ctypes.c_char_p),
        ("source_start", ctypes.c_uint64),
        ("source_end", ctypes.c_uint64),
        ("content_start", ctypes.c_uint64),
    ]


class ChapterCore:
    def __init__(self, library_path: str) -> None:
        self._library = ctypes.CDLL(library_path)
        lib = self._library
        lib.ermao_chapters_abi_version.restype = ctypes.c_uint32
        if lib.ermao_chapters_abi_version() != 1:
            raise PublicationReadError("Chapter engine ABI is unsupported")
        result_out = ctypes.POINTER(ctypes.c_void_p)
        lib.ermao_chapters_parse_txt.argtypes = [
            ctypes.c_char_p,
            ctypes.c_uint64,
            result_out,
        ]
        lib.ermao_chapters_parse_xml.argtypes = [
            ctypes.c_uint32,
            ctypes.POINTER(_Event),
            ctypes.c_uint32,
            result_out,
        ]
        lib.ermao_chapters_from_mobi.argtypes = [
            ctypes.POINTER(_MobiNode),
            ctypes.c_uint32,
            result_out,
        ]
        for name in (
            "ermao_chapters_parse_txt",
            "ermao_chapters_parse_xml",
            "ermao_chapters_from_mobi",
        ):
            getattr(lib, name).restype = ctypes.c_int
        lib.ermao_chapters_count.argtypes = [ctypes.c_void_p]
        lib.ermao_chapters_count.restype = ctypes.c_uint32
        lib.ermao_chapters_entry.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        lib.ermao_chapters_entry.restype = ctypes.POINTER(_Entry)
        lib.ermao_chapters_text.argtypes = [ctypes.c_void_p]
        lib.ermao_chapters_text.restype = ctypes.c_void_p
        lib.ermao_chapters_text_length.argtypes = [ctypes.c_void_p]
        lib.ermao_chapters_text_length.restype = ctypes.c_uint64
        lib.ermao_chapters_free.argtypes = [ctypes.c_void_p]
        lib.ermao_chapters_free.restype = None

    @classmethod
    def load(cls) -> ChapterCore:
        configured = os.environ.get("ERMAO_CHAPTER_CORE_LIBRARY")
        root = Path(__file__).resolve().parents[6]
        build = root / "packages/reader-core/native/chapters/build"
        candidates = (
            [configured]
            if configured
            else [
                ctypes.util.find_library("ermao_chapters"),
                "/usr/local/lib/libermao_chapters.so",
                "/usr/local/lib/libermao_chapters.dylib",
                str(build / "Release/ermao_chapters.dll"),
                str(build / "ermao_chapters.dll"),
                str(build / "libermao_chapters.so"),
            ]
        )
        last_error: OSError | None = None
        for candidate in candidates:
            if candidate:
                try:
                    return cls(candidate)
                except OSError as error:
                    last_error = error
        raise PublicationReadError("Chapter engine is unavailable") from last_error

    def parse_txt(self, text: str) -> ChapterProjection:
        encoded = text.encode("utf-8")
        result = ctypes.c_void_p()
        status = self._library.ermao_chapters_parse_txt(
            encoded, len(encoded), ctypes.byref(result)
        )
        return self._consume(status, result)

    def parse_xml(
        self, format_id: int, events: Sequence[XmlChapterEvent]
    ) -> ChapterProjection:
        attributes = [
            (_Attribute * len(event.attributes))(
                *[
                    _Attribute(name.encode(), value.encode())
                    for name, value in event.attributes
                ]
            )
            for event in events
        ]
        native = (_Event * len(events))(
            *[
                _Event(
                    event.kind,
                    event.name.encode(),
                    event.text.encode(),
                    attrs,
                    len(attrs),
                    event.target_href.encode() if event.target_href else None,
                )
                for event, attrs in zip(events, attributes, strict=True)
            ]
        )
        result = ctypes.c_void_p()
        status = self._library.ermao_chapters_parse_xml(
            format_id, native, len(native), ctypes.byref(result)
        )
        return self._consume(status, result)

    def from_mobi(self, nodes: Sequence[MobiChapterNode]) -> ChapterProjection:
        native = (_MobiNode * len(nodes))(
            *[
                _MobiNode(
                    node.parent_index,
                    node.title.encode(),
                    node.target_href.encode() if node.target_href else None,
                )
                for node in nodes
            ]
        )
        result = ctypes.c_void_p()
        status = self._library.ermao_chapters_from_mobi(
            native, len(native), ctypes.byref(result)
        )
        return self._consume(status, result)

    def _consume(self, status: int, result: ctypes.c_void_p) -> ChapterProjection:
        try:
            if status == 2:
                raise PublicationReadError("Chapter engine allocation failed")
            if status != 0 or not result.value:
                raise PublicationStructureError("Chapter input is invalid")
            count = int(self._library.ermao_chapters_count(result))
            entries: list[ChapterEntry] = []
            for index in range(count):
                raw = self._library.ermao_chapters_entry(result, index).contents
                entries.append(
                    ChapterEntry(
                        index=raw.index,
                        parent_index=raw.parent_index,
                        key=raw.key.decode(),
                        title=raw.title.decode(),
                        href=raw.href.decode() if raw.href else None,
                        source_start=raw.source_start,
                        source_end=raw.source_end,
                        content_start=raw.content_start,
                    )
                )
            length = int(self._library.ermao_chapters_text_length(result))
            text = (
                ctypes.string_at(self._library.ermao_chapters_text(result), length)
                if length
                else b""
            )
            return ChapterProjection(tuple(entries), text)
        finally:
            self._library.ermao_chapters_free(result)
