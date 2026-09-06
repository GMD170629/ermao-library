"""Safe zero-copy EPUB to Readium Web Publication adapter."""

from __future__ import annotations

import mimetypes
import posixpath
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree

from app.contracts.reader_safety_policy_generated import (
    ReaderSafetyBudgetName,
    ReaderSafetyRuleId,
    reader_safety_budget,
)
from app.infrastructure.archive_integrity import (
    UnsafeArchivePathError,
    normalize_archive_path,
    zip_entry_data_span,
)
from app.modules.publications.application.ports import (
    PublicationAdapter,
    PublicationSource,
)
from app.modules.publications.application.safety_policy import (
    publication_integrity_failure,
    publication_native_parser_implementation_failure,
    publication_native_parser_rejection,
    publication_optional_resource_failure,
    publication_parser_limit,
    publication_resource_limit,
    publication_security_rejection,
)
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationCorruptError,
    PublicationLink,
    PublicationMarkupError,
    PublicationReadError,
    PublicationResource,
    PublicationResourceBlockedError,
    PublicationResourceNotFoundError,
    PublicationRevision,
    PublicationStructureError,
    PublicationTocEntry,
    PublicationUnsupportedError,
)
from app.modules.publications.infrastructure.chapter_core import (
    ChapterCore,
    xml_chapter_events,
)
from app.modules.publications.infrastructure.locator_dom import (
    parse_safe_markup_root,
    sanitize_css_resource,
    sanitize_markup_resource,
)
from app.modules.publications.infrastructure.snapshot_cache import (
    PublicationSnapshotCache,
)
from app.modules.publications.infrastructure.source_files import (
    resolve_publication_source,
    select_publication_source_root,
)
from app.modules.publications.infrastructure.xml_policy import (
    XmlPolicyDecodeError,
    XmlPolicyExpansionLimitError,
    XmlPolicyPreparationError,
    parse_xml,
)

EPUB_PARSER_IDENTIFIER = "epub-package:1"
EPUB_NORMALIZATION_IDENTIFIER = "shuku-epub-locator-dom-v4"
MAX_ARCHIVE_ENTRIES = reader_safety_budget(
    ReaderSafetyBudgetName.ARCHIVE_ENTRY_MAX_COUNT
)
MAX_SINGLE_RESOURCE_BYTES = reader_safety_budget(
    ReaderSafetyBudgetName.ARCHIVE_ENTRY_MAX_BYTES
)
MAX_MARKUP_RESOURCE_BYTES = reader_safety_budget(
    ReaderSafetyBudgetName.REFLOWABLE_MARKUP_MAX_BYTES
)
MAX_TOTAL_UNCOMPRESSED_BYTES = reader_safety_budget(
    ReaderSafetyBudgetName.ARCHIVE_EXPANDED_MAX_BYTES
)
MAX_COMPRESSION_RATIO = reader_safety_budget(
    ReaderSafetyBudgetName.ARCHIVE_COMPRESSION_RATIO_MAX
)
MAX_XML_CONTROL_DOCUMENT_BYTES = reader_safety_budget(
    ReaderSafetyBudgetName.XML_CONTROL_DOCUMENT_MAX_BYTES
)
MAX_EPUB_SOURCE_BYTES = reader_safety_budget(ReaderSafetyBudgetName.ORIGINAL_MAX_BYTES)


@dataclass(frozen=True, slots=True)
class _IndexedEpub:
    source_path: Path
    source_mtime: float
    publication: NormalizedPublication
    entries_by_href: dict[str, str]
    media_types_by_href: dict[str, str]
    required_hrefs: frozenset[str]
    integrity_hrefs: frozenset[str]


@dataclass(frozen=True, slots=True)
class _ValidatedArchive:
    entries: dict[str, zipfile.ZipInfo]
    integrity_hrefs: frozenset[str]


def _xml_root(content: bytes) -> ElementTree.Element:
    if len(content) > MAX_XML_CONTROL_DOCUMENT_BYTES:
        raise publication_parser_limit(
            ReaderSafetyRuleId.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES,
            "publication XML control document exceeds the size limit",
        )
    try:
        _projection, root = parse_xml(
            content,
            expansion_limit_bytes=MAX_XML_CONTROL_DOCUMENT_BYTES,
        )
        return root
    except (ElementTree.ParseError, UnicodeDecodeError) as error:
        raise PublicationMarkupError("publication XML is invalid") from error
    except XmlPolicyExpansionLimitError as error:
        raise publication_parser_limit(
            ReaderSafetyRuleId.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES,
            "publication XML entity expansion exceeds the size limit",
        ) from error
    except XmlPolicyDecodeError as error:
        raise PublicationMarkupError("publication XML encoding is invalid") from error
    except XmlPolicyPreparationError as error:
        raise publication_native_parser_implementation_failure(
            ReaderSafetyRuleId.REFLOWABLE_PREPARE_XML,
            parser="reader-xml-policy",
            operation="prepare",
            reason="generated XML preparation defense is unavailable",
        ) from error


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _canonical_href(base: str, href: str) -> str:
    split = urlsplit(href)
    if split.scheme or split.netloc or split.query:
        raise publication_security_rejection(
            ReaderSafetyRuleId.EPUB_ARCHIVE_STRUCTURE,
            "publication href must be local",
        )
    decoded = unquote(split.path).replace("\\", "/")
    if (
        "\x00" in decoded
        or decoded.startswith("/")
        or len(decoded) >= 3
        and decoded[1] == ":"
        and decoded[2] == "/"
    ):
        raise publication_security_rejection(
            ReaderSafetyRuleId.EPUB_ARCHIVE_STRUCTURE,
            "publication href escapes its archive",
        )
    joined = posixpath.normpath(posixpath.join(base, decoded))
    if joined in {"", ".", ".."} or joined.startswith("../"):
        raise publication_security_rejection(
            ReaderSafetyRuleId.EPUB_ARCHIVE_STRUCTURE,
            "publication href escapes its archive",
        )
    encoded = quote(joined, safe="/!$&'()*+,-.:;=@_~")
    return encoded + (f"#{split.fragment}" if split.fragment else "")


def _entry_key(href: str) -> str:
    # ZIP publication paths are POSIX names. Treat a backslash as a separator
    # before normalization so harmless mixed-separator/dot spelling resolves to
    # one canonical in-memory key; traversal still remains a boundary failure.
    path = unquote(urlsplit(href).path).replace("\\", "/")
    try:
        return normalize_archive_path(path)
    except UnsafeArchivePathError as error:
        raise PublicationResourceNotFoundError from error


def _validated_entries(archive: zipfile.ZipFile) -> _ValidatedArchive:
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise publication_parser_limit(
            ReaderSafetyRuleId.EPUB_ARCHIVE_ENTRY_MAX_COUNT,
            "publication has too many resources",
        )
    entries: dict[str, zipfile.ZipInfo] = {}
    integrity_hrefs: set[str] = set()
    total = 0
    spans: list[tuple[int, int, str | None]] = []
    for info in infos:
        total += info.file_size
        if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise publication_parser_limit(
                ReaderSafetyRuleId.EPUB_ARCHIVE_EXPANDED_MAX_BYTES,
                "publication exceeds the expanded size limit",
            )
        if info.file_size > MAX_SINGLE_RESOURCE_BYTES:
            raise publication_parser_limit(
                ReaderSafetyRuleId.EPUB_ARCHIVE_ENTRY_MAX_BYTES,
                "publication resource exceeds the size limit",
            )
        if info.compress_size == 0 and info.file_size > 0:
            raise publication_parser_limit(
                ReaderSafetyRuleId.EPUB_ARCHIVE_COMPRESSION_RATIO,
                "publication resource has an invalid compression ratio",
            )
        if (
            info.compress_size
            and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
        ):
            raise publication_parser_limit(
                ReaderSafetyRuleId.EPUB_ARCHIVE_COMPRESSION_RATIO,
                "publication resource compression ratio is unsafe",
            )
        key: str | None
        try:
            key = normalize_archive_path(info.filename)
        except UnsafeArchivePathError:
            # An unused escaped name cannot be extracted through this adapter.
            # Quarantine it while retaining the archive-wide bounds above; a
            # required package/manifest lookup will fail when it is addressed.
            key = None
        unix_mode = info.external_attr >> 16
        if stat.S_ISLNK(unix_mode):
            if key is not None:
                # A same-name regular member must not later resolve through
                # ZipFile.getinfo() to this quarantined link (or vice versa).
                integrity_hrefs.add(key)
            key = None
        duplicate = key is not None and key in entries
        if duplicate and key is not None:
            integrity_hrefs.add(key)
        if key is not None and not duplicate:
            entries[key] = info
        span = zip_entry_data_span(archive, info)
        if span is not None and span[0] < span[1]:
            spans.append((span[0], span[1], key))
    spans.sort(key=lambda item: (item[0], item[1]))
    previous_end = -1
    for start, end, key in spans:
        if start < previous_end:
            if key is not None:
                integrity_hrefs.add(key)
            for previous_start, previous_span_end, previous_key in spans:
                if (
                    previous_start < end
                    and start < previous_span_end
                    and previous_key is not None
                ):
                    integrity_hrefs.add(previous_key)
        previous_end = max(previous_end, end)
    return _ValidatedArchive(entries, frozenset(integrity_hrefs))


def _read_archive_resource(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    required: bool,
    integrity_failed: bool = False,
    parser_budget: tuple[ReaderSafetyRuleId, int] | None = None,
) -> bytes:
    """Read one entry and classify checksum/decoder failures by role."""

    if parser_budget is not None:
        rule_id, maximum_bytes = parser_budget
        if info.file_size > maximum_bytes:
            raise publication_parser_limit(
                rule_id, "EPUB parser resource exceeds its byte budget"
            )

    if integrity_failed:
        if required:
            raise publication_integrity_failure(
                ReaderSafetyRuleId.EPUB_RESOURCE_INTEGRITY,
                "required EPUB resource has conflicting archive entries",
            )
        raise publication_integrity_failure(
            ReaderSafetyRuleId.REFLOWABLE_OPTIONAL_RESOURCE_FAILURE,
            "optional EPUB resource has conflicting archive entries",
            optional=True,
        )
    if info.flag_bits & 0x1:
        if not required:
            raise publication_optional_resource_failure(
                ReaderSafetyRuleId.COMMON_DRM_REJECTED,
                "optional encrypted EPUB resource cannot be decrypted",
            )
        raise publication_native_parser_rejection(
            ReaderSafetyRuleId.COMMON_DRM_REJECTED,
            parser="python-zipfile",
            operation="read-entry",
            reason="encrypted EPUB resource is unsupported",
        )
    try:
        return archive.read(info)
    except (NotImplementedError, RuntimeError) as error:
        raise publication_native_parser_implementation_failure(
            ReaderSafetyRuleId.EPUB_RESOURCE_INTEGRITY,
            parser="python-zipfile",
            operation="read-entry",
            reason="archive decoder cannot provide this resource",
        ) from error
    except (EOFError, zipfile.BadZipFile) as error:
        if required:
            raise publication_integrity_failure(
                ReaderSafetyRuleId.EPUB_RESOURCE_INTEGRITY,
                "required EPUB resource failed integrity or decoder validation",
            ) from error
        raise publication_integrity_failure(
            ReaderSafetyRuleId.REFLOWABLE_OPTIONAL_RESOURCE_FAILURE,
            "optional EPUB resource failed integrity or decoder validation",
            optional=True,
        ) from error
    except ValueError as error:
        raise PublicationReadError("EPUB resource cannot be read") from error
    except OSError as error:
        raise PublicationReadError("EPUB resource cannot be read") from error


def _container_opf_path(
    archive: zipfile.ZipFile,
    entries: dict[str, zipfile.ZipInfo],
    integrity_hrefs: frozenset[str],
) -> str:
    container = entries.get("META-INF/container.xml")
    if container is None:
        raise PublicationStructureError("EPUB container is missing")
    try:
        root = _xml_root(
            _read_archive_resource(
                archive,
                container,
                required=True,
                integrity_failed="META-INF/container.xml" in integrity_hrefs,
                parser_budget=(
                    ReaderSafetyRuleId.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES,
                    MAX_XML_CONTROL_DOCUMENT_BYTES,
                ),
            )
        )
    except PublicationMarkupError as error:
        raise PublicationStructureError("EPUB container is invalid") from error
    for element in root.iter():
        if _local_name(element.tag) == "rootfile":
            value = element.attrib.get("full-path", "")
            try:
                key = _entry_key(value)
            except PublicationResourceNotFoundError as error:
                raise publication_security_rejection(
                    ReaderSafetyRuleId.EPUB_ARCHIVE_STRUCTURE,
                    "EPUB package path escapes its archive",
                ) from error
            if key in integrity_hrefs:
                raise publication_integrity_failure(
                    ReaderSafetyRuleId.EPUB_RESOURCE_INTEGRITY,
                    "EPUB package path has conflicting archive entries",
                )
            if key in entries:
                return key
    raise PublicationStructureError("EPUB package document is missing")


def _metadata_value(root: ElementTree.Element, name: str) -> str | None:
    for element in root.iter():
        if _local_name(element.tag) == name and element.text and element.text.strip():
            return element.text.strip()
    return None


def _reading_progression(root: ElementTree.Element) -> str:
    for element in root.iter():
        if _local_name(element.tag) == "spine":
            return (
                "rtl"
                if element.attrib.get("page-progression-direction") == "rtl"
                else "ltr"
            )
    return "ltr"


def _toc_from_nav(
    archive: zipfile.ZipFile,
    entries: dict[str, zipfile.ZipInfo],
    integrity_hrefs: frozenset[str],
    nav_href: str | None,
    known_hrefs: frozenset[str],
) -> tuple[PublicationTocEntry, ...]:
    if nav_href is None:
        return ()
    nav_key = _entry_key(nav_href)
    nav_info = entries.get(nav_key)
    if nav_info is None:
        return ()
    _markup, root = parse_safe_markup_root(
        _read_archive_resource(
            archive,
            nav_info,
            required=False,
            integrity_failed=nav_key in integrity_hrefs,
            parser_budget=(
                ReaderSafetyRuleId.REFLOWABLE_MARKUP_MAX_BYTES,
                MAX_MARKUP_RESOURCE_BYTES,
            ),
        )
    )
    if _local_name(root.tag) != "html":
        return ()
    return _chapter_xml_projection(root, nav_key, known_hrefs, 1)


def _chapter_xml_projection(
    root: ElementTree.Element,
    document_path: str,
    known_hrefs: frozenset[str],
    format_id: int,
) -> tuple[PublicationTocEntry, ...]:
    def target(element: ElementTree.Element) -> str | None:
        raw = element.attrib.get("href") or element.attrib.get("src")
        if not raw:
            return None
        try:
            href = _canonical_href(
                posixpath.dirname(document_path),
                posixpath.basename(document_path) + raw if raw.startswith("#") else raw,
            )
        except (PublicationCorruptError, PublicationResourceNotFoundError, ValueError):
            return None
        return href if _entry_key(href) in known_hrefs else None

    return (
        ChapterCore.load()
        .parse_xml(
            format_id,
            tuple(xml_chapter_events(root, target)),
        )
        .table_of_contents()
    )


def _toc_from_ncx(
    archive: zipfile.ZipFile,
    entries: dict[str, zipfile.ZipInfo],
    integrity_hrefs: frozenset[str],
    ncx_href: str | None,
    known_hrefs: frozenset[str],
) -> tuple[PublicationTocEntry, ...]:
    if ncx_href is None:
        return ()
    ncx_key = _entry_key(ncx_href)
    ncx_info = entries.get(ncx_key)
    if ncx_info is None:
        return ()
    root = _xml_root(
        _read_archive_resource(
            archive,
            ncx_info,
            required=False,
            integrity_failed=ncx_key in integrity_hrefs,
            parser_budget=(
                ReaderSafetyRuleId.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES,
                MAX_XML_CONTROL_DOCUMENT_BYTES,
            ),
        )
    )
    return _chapter_xml_projection(root, ncx_key, known_hrefs, 2)


def _index_epub(
    source_path_value: str,
    source_size: int,
    source_mtime_ns: int,
    fallback_title: str,
    fallback_author: str | None,
) -> _IndexedEpub:
    source_path = Path(source_path_value)
    try:
        with zipfile.ZipFile(source_path) as archive:
            validated = _validated_entries(archive)
            entries = validated.entries
            integrity_hrefs = validated.integrity_hrefs
            opf_path = _container_opf_path(archive, entries, integrity_hrefs)
            try:
                opf_root = _xml_root(
                    _read_archive_resource(
                        archive,
                        entries[opf_path],
                        required=True,
                        integrity_failed=opf_path in integrity_hrefs,
                        parser_budget=(
                            ReaderSafetyRuleId.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES,
                            MAX_XML_CONTROL_DOCUMENT_BYTES,
                        ),
                    )
                )
            except PublicationMarkupError as error:
                raise PublicationStructureError(
                    "EPUB package document is invalid"
                ) from error
            opf_base = posixpath.dirname(opf_path)
            manifest_by_id: dict[str, tuple[str, str, str]] = {}
            nav_href: str | None = None
            ncx_hrefs_by_id: dict[str, str] = {}
            for element in opf_root.iter():
                if _local_name(element.tag) != "item":
                    continue
                item_id = element.attrib.get("id")
                raw_href = element.attrib.get("href")
                if not item_id or not raw_href:
                    continue
                try:
                    href = _canonical_href(opf_base, raw_href)
                    key = _entry_key(href)
                except (
                    PublicationCorruptError,
                    PublicationResourceNotFoundError,
                    ValueError,
                ):
                    # An optional manifest item cannot be addressed safely.  It
                    # is omitted from the in-memory publication; an itemref
                    # that requires it is reported as a missing required item
                    # below.
                    continue
                if key not in entries:
                    continue
                media_type = (
                    element.attrib.get("media-type")
                    or mimetypes.guess_type(key)[0]
                    or "application/octet-stream"
                )
                manifest_by_id[item_id] = (
                    href,
                    media_type,
                    element.attrib.get("properties", ""),
                )
                if (
                    nav_href is None
                    and "nav" in element.attrib.get("properties", "").split()
                ):
                    nav_href = href
                if media_type == "application/x-dtbncx+xml":
                    ncx_hrefs_by_id[item_id] = href
            spine = next(
                (
                    element
                    for element in opf_root.iter()
                    if _local_name(element.tag) == "spine"
                ),
                None,
            )
            declared_ncx = (
                manifest_by_id.get(spine.attrib.get("toc", ""))
                if spine is not None
                else None
            )
            ncx_href = (
                declared_ncx[0]
                if declared_ncx is not None
                else next(iter(ncx_hrefs_by_id.values()), None)
            )
            reading_order: list[PublicationLink] = []
            reading_ids: set[str] = set()
            for element in opf_root.iter():
                if _local_name(element.tag) != "itemref":
                    continue
                item_id = element.attrib.get("idref", "")
                manifest_item = manifest_by_id.get(item_id)
                if manifest_item is None:
                    raise publication_integrity_failure(
                        ReaderSafetyRuleId.REFLOWABLE_REQUIRED_READING_ORDER_MARKUP,
                        "EPUB spine references a missing manifest item",
                    )
                reading_ids.add(item_id)
                reading_order.append(
                    PublicationLink(href=manifest_item[0], media_type=manifest_item[1])
                )
            if not reading_order:
                raise publication_integrity_failure(
                    ReaderSafetyRuleId.REFLOWABLE_REQUIRED_READING_ORDER_MARKUP,
                    "EPUB reading order is empty",
                )
            required_hrefs = frozenset(_entry_key(link.href) for link in reading_order)
            if required_hrefs & integrity_hrefs:
                raise publication_integrity_failure(
                    ReaderSafetyRuleId.EPUB_RESOURCE_INTEGRITY,
                    "required EPUB reading-order resource has conflicting archive entries",
                )
            resources = tuple(
                PublicationLink(
                    href=href,
                    media_type=media_type,
                    rel=("contents",)
                    if "nav" in properties.split() or href == ncx_href
                    else (),
                )
                for item_id, (href, media_type, properties) in manifest_by_id.items()
                if item_id not in reading_ids
            )
            known_hrefs = frozenset(
                _entry_key(href)
                for href, _media, _properties in manifest_by_id.values()
            )
            try:
                toc = _toc_from_nav(
                    archive, entries, integrity_hrefs, nav_href, known_hrefs
                )
            except (
                PublicationMarkupError,
                PublicationStructureError,
                PublicationResourceBlockedError,
            ):
                toc = ()
            if not toc:
                try:
                    toc = _toc_from_ncx(
                        archive, entries, integrity_hrefs, ncx_href, known_hrefs
                    )
                except (
                    PublicationMarkupError,
                    PublicationStructureError,
                    PublicationResourceBlockedError,
                ):
                    toc = ()
            publication = NormalizedPublication(
                identifier=f"urn:shuku:volume:{source_path.name}",
                title=_metadata_value(opf_root, "title") or fallback_title,
                author=_metadata_value(opf_root, "creator") or fallback_author,
                language=_metadata_value(opf_root, "language"),
                reading_progression=_reading_progression(opf_root),
                revision=PublicationRevision(
                    source_size_bytes=source_size,
                    source_mtime_ms=source_mtime_ns // 1_000_000,
                    parser=EPUB_PARSER_IDENTIFIER,
                    normalization=EPUB_NORMALIZATION_IDENTIFIER,
                ),
                reading_order=tuple(reading_order),
                resources=resources,
                toc=toc,
            )
            media_types = {
                _entry_key(link.href): link.media_type
                for link in (*publication.reading_order, *publication.resources)
            }
            return _IndexedEpub(
                source_path=source_path,
                source_mtime=source_path.stat().st_mtime,
                publication=publication,
                entries_by_href={key: info.filename for key, info in entries.items()},
                media_types_by_href=media_types,
                required_hrefs=required_hrefs,
                integrity_hrefs=integrity_hrefs,
            )
    except (
        EOFError,
        NotImplementedError,
        RuntimeError,
        ValueError,
        zipfile.BadZipFile,
    ) as error:
        raise PublicationStructureError("EPUB archive is invalid") from error
    except OSError as error:
        raise PublicationReadError("EPUB archive cannot be read") from error


class EpubPublicationAdapter(PublicationAdapter):
    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root
        self._cache: PublicationSnapshotCache[_IndexedEpub] = PublicationSnapshotCache()

    def open(self, source: PublicationSource) -> NormalizedPublication:
        return self._index(source).publication

    def read_resource(
        self,
        source: PublicationSource,
        href: str,
    ) -> PublicationResource:
        indexed = self._index(source)
        try:
            key = _entry_key(href)
        except (PublicationResourceNotFoundError, ValueError) as error:
            raise PublicationResourceNotFoundError from error
        archive_name = indexed.entries_by_href.get(key)
        if archive_name is None or key not in indexed.media_types_by_href:
            raise PublicationResourceNotFoundError
        media_type = indexed.media_types_by_href[key].split(";", 1)[0].strip().lower()
        is_markup = key in indexed.required_hrefs or media_type in {
            "application/xhtml+xml",
            "text/html",
            "image/svg+xml",
        }
        try:
            with zipfile.ZipFile(indexed.source_path) as archive:
                size_limit = (
                    MAX_MARKUP_RESOURCE_BYTES
                    if is_markup or media_type == "text/css"
                    else MAX_SINGLE_RESOURCE_BYTES
                )
                info = archive.getinfo(archive_name)
                if info.file_size > size_limit:
                    if size_limit == MAX_MARKUP_RESOURCE_BYTES:
                        raise publication_parser_limit(
                            ReaderSafetyRuleId.REFLOWABLE_MARKUP_MAX_BYTES,
                            "Publication markup exceeds the byte limit",
                        )
                    raise publication_resource_limit(
                        ReaderSafetyRuleId.COMMON_BINARY_RESOURCE_MAX_BYTES,
                        "Publication resource exceeds the byte limit",
                    )
                content = _read_archive_resource(
                    archive,
                    info,
                    required=key in indexed.required_hrefs,
                    integrity_failed=key in indexed.integrity_hrefs,
                )
        except (
            EOFError,
            KeyError,
            NotImplementedError,
            OSError,
            RuntimeError,
            ValueError,
            zipfile.BadZipFile,
        ) as error:
            raise PublicationReadError("EPUB resource cannot be read") from error
        try:
            if is_markup:
                content = sanitize_markup_resource(content)
            elif media_type == "text/css":
                content = sanitize_css_resource(content)
        except PublicationMarkupError as error:
            if key in indexed.required_hrefs:
                raise publication_integrity_failure(
                    ReaderSafetyRuleId.REFLOWABLE_REQUIRED_READING_ORDER_MARKUP,
                    "required EPUB content cannot be decoded or parsed",
                ) from error
            raise publication_integrity_failure(
                ReaderSafetyRuleId.REFLOWABLE_OPTIONAL_RESOURCE_FAILURE,
                "optional EPUB text resource cannot be decoded or parsed",
                optional=True,
            ) from error
        return PublicationResource(
            href=href,
            media_type=indexed.media_types_by_href[key],
            content=content,
            source_mtime=indexed.source_mtime,
        )

    def _index(self, source: PublicationSource) -> _IndexedEpub:
        if source.source_format != "epub":
            raise PublicationUnsupportedError(source.source_format)
        path = resolve_publication_source(
            source.path,
            select_publication_source_root(source.library_root, self._storage_root),
        )
        stat_result = path.stat()
        if stat_result.st_size > MAX_EPUB_SOURCE_BYTES:
            raise publication_resource_limit(
                ReaderSafetyRuleId.COMMON_ORIGINAL_MAX_BYTES,
                "EPUB source exceeds the size limit",
            )
        key = (
            str(path),
            stat_result.st_size,
            stat_result.st_mtime_ns,
            source.title,
            source.author,
        )
        return self._cache.get(
            key, lambda: _index_epub(*key), MAX_ARCHIVE_ENTRIES * 2048
        )

    def close(self) -> None:
        self._cache.close()
