from __future__ import annotations

import copy
import posixpath
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urldefrag, urlsplit

from lxml import etree, html


EPUB_NORMALIZER_VERSION = "shuku-epub-normalizer/1"

NORMALIZE_SECTION_BYTES = 1 * 1024 * 1024
NORMALIZE_SECTION_ELEMENTS = 10_000
NORMALIZE_SECTION_IMAGES = 100

TARGET_SECTION_BYTES = 768 * 1024
TARGET_SECTION_ELEMENTS = 7_500
TARGET_SECTION_IMAGES = 75

XHTML_NAMESPACE = "http://www.w3.org/1999/xhtml"
EPUB_NAMESPACE = "http://www.idpf.org/2007/ops"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"

URL_ATTRIBUTE_NAMES = {"href", "src", "poster", "data", "xlink:href"}
CONTENT_MEDIA_TYPES = {"application/xhtml+xml", "text/html"}
CSS_URL_PATTERN = re.compile(r"url\(\s*(['\"]?)([^)'\"]+)\1\s*\)", re.IGNORECASE)


class EpubNormalizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class EpubSectionMetrics:
    item_id: str
    href: str
    archive_path: str
    size_bytes: int
    element_count: int
    image_count: int
    strict_xhtml: bool

    def exceeds_limits(self) -> bool:
        return (
            self.size_bytes > NORMALIZE_SECTION_BYTES
            or self.element_count > NORMALIZE_SECTION_ELEMENTS
            or self.image_count > NORMALIZE_SECTION_IMAGES
        )


@dataclass(frozen=True)
class EpubInspection:
    rootfile: str
    spine_count: int
    archive_size_bytes: int
    archive_uncompressed_bytes: int
    sections: tuple[EpubSectionMetrics, ...]
    reasons: tuple[str, ...]

    @property
    def requires_normalization(self) -> bool:
        return bool(self.reasons)

    def metrics(self) -> dict[str, object]:
        return {
            "spineCount": self.spine_count,
            "archiveSizeBytes": self.archive_size_bytes,
            "archiveUncompressedBytes": self.archive_uncompressed_bytes,
            "maxSectionBytes": max((section.size_bytes for section in self.sections), default=0),
            "maxSectionElements": max((section.element_count for section in self.sections), default=0),
            "maxSectionImages": max((section.image_count for section in self.sections), default=0),
            "sections": [asdict(section) for section in self.sections],
        }


@dataclass(frozen=True)
class EpubNormalizationResult:
    applied: bool
    reasons: tuple[str, ...]
    before: EpubInspection
    after: EpubInspection

    def options(self) -> dict[str, object]:
        return {
            "normalizerVersion": EPUB_NORMALIZER_VERSION,
            "normalizationApplied": self.applied,
            "normalizationReasons": list(self.reasons),
            "normalizationBefore": self.before.metrics(),
            "normalizationAfter": self.after.metrics(),
        }


@dataclass
class _Package:
    opf_path: str
    root: etree._Element
    manifest: etree._Element
    spine: etree._Element
    manifest_items: dict[str, etree._Element]
    spine_refs: list[etree._Element]


@dataclass(frozen=True)
class _ChunkStats:
    size_bytes: int = 0
    elements: int = 0
    images: int = 0

    def plus(self, other: _ChunkStats) -> _ChunkStats:
        return _ChunkStats(
            self.size_bytes + other.size_bytes,
            self.elements + other.elements,
            self.images + other.images,
        )

    def exceeds_target(self) -> bool:
        return (
            self.size_bytes > TARGET_SECTION_BYTES
            or self.elements > TARGET_SECTION_ELEMENTS
            or self.images > TARGET_SECTION_IMAGES
        )

    def exceeds_hard_limit(self) -> bool:
        return (
            self.size_bytes > NORMALIZE_SECTION_BYTES
            or self.elements > NORMALIZE_SECTION_ELEMENTS
            or self.images > NORMALIZE_SECTION_IMAGES
        )

    def reached_preferred_boundary_floor(self) -> bool:
        return (
            self.size_bytes >= TARGET_SECTION_BYTES // 4
            or self.elements >= TARGET_SECTION_ELEMENTS // 4
            or self.images >= TARGET_SECTION_IMAGES // 4
        )


def _local_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.rsplit("}", 1)[-1].lower()


def _attribute_local_name(value: str) -> str:
    if value.startswith("{"):
        namespace, _, local = value[1:].partition("}")
        if namespace == XLINK_NAMESPACE:
            return f"xlink:{local.lower()}"
        return local.lower()
    return value.lower()


def _xml_parser(*, recover: bool = False) -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=recover,
        remove_comments=False,
        huge_tree=True,
    )


def _parse_xml(data: bytes, label: str) -> etree._Element:
    try:
        return etree.fromstring(data, parser=_xml_parser())
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise EpubNormalizationError(f"{label} XML 结构无效：{exc}") from exc


def _recover_html(data: bytes, label: str) -> etree._Element:
    try:
        document = html.document_fromstring(
            data,
            parser=html.HTMLParser(
                encoding="utf-8",
                recover=True,
                no_network=True,
                remove_comments=False,
                huge_tree=True,
            ),
        )
    except (etree.ParserError, etree.XMLSyntaxError, ValueError) as exc:
        raise EpubNormalizationError(f"{label} HTML 无法恢复：{exc}") from exc
    if document.find("body") is None:
        raise EpubNormalizationError(f"{label} 缺少可恢复的 body")
    return document


def _safe_archive_names(archive: zipfile.ZipFile) -> set[str]:
    infos = archive.infolist()
    names = [info.filename for info in infos]
    if not infos or infos[0].filename != "mimetype" or infos[0].compress_type != zipfile.ZIP_STORED:
        raise EpubNormalizationError("EPUB mimetype 必须是首个未压缩条目")
    try:
        mimetype = archive.read("mimetype").decode("ascii", errors="strict").strip()
    except (KeyError, UnicodeError) as exc:
        raise EpubNormalizationError("EPUB 缺少有效 mimetype") from exc
    if mimetype != "application/epub+zip":
        raise EpubNormalizationError("EPUB mimetype 无效")
    if len(names) != len(set(names)):
        raise EpubNormalizationError("EPUB 包含重复路径")
    for name in names:
        path = PurePosixPath(name)
        if name.startswith("/") or "\\" in name or ".." in path.parts:
            raise EpubNormalizationError(f"EPUB 包含不安全路径：{name}")
        if archive.getinfo(name).flag_bits & 1:
            raise EpubNormalizationError(f"EPUB 包含加密条目：{name}")
    crc_error = archive.testzip()
    if crc_error:
        raise EpubNormalizationError(f"EPUB CRC 校验失败：{crc_error}")
    return set(names)


def _resolve_archive_path(base_file: str, href: str) -> tuple[str, str, str] | None:
    value = href.strip()
    if not value:
        return base_file, "", ""
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or value.startswith("//"):
        return None
    decoded_path = unquote(parsed.path)
    fragment = unquote(parsed.fragment)
    if decoded_path:
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(base_file), decoded_path))
    else:
        resolved = base_file
    if resolved.startswith("/") or resolved == ".." or resolved.startswith("../"):
        raise EpubNormalizationError(f"EPUB 引用越过归档根目录：{href}")
    return resolved, fragment, parsed.query


def _relative_href(source_path: str, target_path: str, fragment: str = "", query: str = "") -> str:
    if source_path == target_path and fragment and not query:
        return "#" + quote(fragment, safe="!$&'()*+,;=:@/?")
    relative = posixpath.relpath(target_path, posixpath.dirname(source_path) or ".")
    result = quote(relative, safe="/~!$&'()*+,;=:@")
    if query:
        result += f"?{query}"
    if fragment:
        result += "#" + quote(fragment, safe="!$&'()*+,;=:@/?")
    return result


def _first_child(root: etree._Element, name: str) -> etree._Element | None:
    return next((node for node in root.iter() if _local_name(node.tag) == name), None)


def _load_package(archive: zipfile.ZipFile, names: set[str]) -> _Package:
    if "META-INF/container.xml" not in names:
        raise EpubNormalizationError("EPUB 缺少 META-INF/container.xml")
    container = _parse_xml(archive.read("META-INF/container.xml"), "container.xml")
    rootfile = next(
        (node.get("full-path") for node in container.iter() if _local_name(node.tag) == "rootfile"),
        None,
    )
    if not rootfile or rootfile not in names:
        raise EpubNormalizationError("EPUB 缺少有效 OPF rootfile")
    root = _parse_xml(archive.read(rootfile), rootfile)
    manifest = _first_child(root, "manifest")
    spine = _first_child(root, "spine")
    if manifest is None or spine is None:
        raise EpubNormalizationError("EPUB OPF 缺少 manifest 或 spine")
    manifest_items = {
        str(node.get("id")): node
        for node in manifest
        if _local_name(node.tag) == "item" and node.get("id")
    }
    spine_refs = [node for node in spine if _local_name(node.tag) == "itemref"]
    if not spine_refs:
        raise EpubNormalizationError("EPUB 不包含可阅读 spine")
    return _Package(rootfile, root, manifest, spine, manifest_items, spine_refs)


def _manifest_archive_path(package: _Package, item: etree._Element) -> str:
    href = item.get("href") or ""
    resolved = _resolve_archive_path(package.opf_path, href)
    if resolved is None:
        raise EpubNormalizationError(f"manifest 不允许远程资源：{href}")
    return resolved[0]


def _content_manifest_items(package: _Package) -> dict[str, etree._Element]:
    result: dict[str, etree._Element] = {}
    for item in package.manifest_items.values():
        if (item.get("media-type") or "").lower() in CONTENT_MEDIA_TYPES:
            result[_manifest_archive_path(package, item)] = item
    return result


def _document_stats(document: etree._Element, size_bytes: int) -> _ChunkStats:
    elements = 0
    images = 0
    for node in document.iter():
        if not isinstance(node.tag, str):
            continue
        elements += 1
        if _local_name(node.tag) == "img":
            images += 1
    return _ChunkStats(size_bytes, elements, images)


def _strict_xhtml(data: bytes) -> bool:
    try:
        root = etree.fromstring(data, parser=_xml_parser())
        return root.tag == f"{{{XHTML_NAMESPACE}}}html"
    except (etree.XMLSyntaxError, ValueError):
        return False


def _anchor_catalog(documents: dict[str, etree._Element]) -> dict[tuple[str, str], etree._Element]:
    anchors: dict[tuple[str, str], etree._Element] = {}
    for path, document in documents.items():
        seen: set[str] = set()
        for node in document.iter():
            values = {
                value
                for value in ((node.get("id") or "").strip(), (node.get("name") or "").strip())
                if value
            }
            for value in values:
                if value in seen:
                    raise EpubNormalizationError(f"EPUB 章节存在重复锚点：{path}#{value}")
                seen.add(value)
                anchors[(path, value)] = node
    return anchors


def _iter_url_attributes(document: etree._Element):
    for node in document.iter():
        for attribute, value in node.attrib.items():
            if _attribute_local_name(attribute) in URL_ATTRIBUTE_NAMES:
                yield node, attribute, value


def _validate_href(
    *,
    source_path: str,
    href: str,
    names: set[str],
    anchors: dict[tuple[str, str], etree._Element],
) -> None:
    resolved = _resolve_archive_path(source_path, href)
    if resolved is None:
        return
    target_path, fragment, _query = resolved
    if target_path not in names:
        raise EpubNormalizationError(f"EPUB 引用的资源不存在：{source_path} -> {href}")
    if fragment and (target_path, fragment) not in anchors:
        raise EpubNormalizationError(f"EPUB 引用的锚点不存在：{source_path} -> {href}")


def _validate_references(
    archive: zipfile.ZipFile,
    names: set[str],
    package: _Package,
    documents: dict[str, etree._Element],
) -> None:
    anchors = _anchor_catalog(documents)
    for path, document in documents.items():
        for _node, _attribute, href in _iter_url_attributes(document):
            _validate_href(source_path=path, href=href, names=names, anchors=anchors)

    for item in package.manifest_items.values():
        target = _manifest_archive_path(package, item)
        if target not in names:
            raise EpubNormalizationError(f"manifest 资源不存在：{item.get('href') or ''}")

    for node in package.root.iter():
        if _local_name(node.tag) == "reference" and node.get("href"):
            _validate_href(
                source_path=package.opf_path,
                href=str(node.get("href")),
                names=names,
                anchors=anchors,
            )

    for item in package.manifest_items.values():
        media_type = (item.get("media-type") or "").lower()
        if media_type != "application/x-dtbncx+xml":
            continue
        ncx_path = _manifest_archive_path(package, item)
        ncx = _parse_xml(archive.read(ncx_path), ncx_path)
        for node in ncx.iter():
            if _local_name(node.tag) == "content" and node.get("src"):
                _validate_href(
                    source_path=ncx_path,
                    href=str(node.get("src")),
                    names=names,
                    anchors=anchors,
                )

    for item in package.manifest_items.values():
        if (item.get("media-type") or "").lower() != "text/css":
            continue
        css_path = _manifest_archive_path(package, item)
        try:
            css = archive.read(css_path).decode("utf-8", errors="replace")
        except KeyError as exc:
            raise EpubNormalizationError(f"CSS 资源不存在：{css_path}") from exc
        for match in CSS_URL_PATTERN.finditer(css):
            value = match.group(2).strip()
            if value.startswith(("data:", "#")):
                continue
            _validate_href(source_path=css_path, href=value, names=names, anchors=anchors)


def _inspect_open_archive(
    archive: zipfile.ZipFile,
    source: Path,
) -> tuple[EpubInspection, _Package, set[str], dict[str, etree._Element]]:
    names = _safe_archive_names(archive)
    package = _load_package(archive, names)
    content_items = _content_manifest_items(package)
    documents: dict[str, etree._Element] = {}
    for path in content_items:
        if path not in names:
            raise EpubNormalizationError(f"正文资源不存在：{path}")
        documents[path] = _recover_html(archive.read(path), path)
    _validate_references(archive, names, package, documents)

    sections: list[EpubSectionMetrics] = []
    reasons: list[str] = []
    for itemref in package.spine_refs:
        item_id = itemref.get("idref") or ""
        item = package.manifest_items.get(item_id)
        if item is None:
            raise EpubNormalizationError(f"spine 引用了未知 manifest item：{item_id}")
        path = _manifest_archive_path(package, item)
        if path not in documents:
            raise EpubNormalizationError(f"spine 引用了非 HTML 正文：{item.get('href') or item_id}")
        data = archive.read(path)
        stats = _document_stats(documents[path], len(data))
        strict = _strict_xhtml(data)
        section = EpubSectionMetrics(
            item_id=item_id,
            href=item.get("href") or path,
            archive_path=path,
            size_bytes=len(data),
            element_count=stats.elements,
            image_count=stats.images,
            strict_xhtml=strict,
        )
        sections.append(section)
        if not strict:
            reasons.append(f"invalid-xhtml:{path}")
        if section.size_bytes > NORMALIZE_SECTION_BYTES:
            reasons.append(f"section-bytes:{path}")
        if section.element_count > NORMALIZE_SECTION_ELEMENTS:
            reasons.append(f"section-elements:{path}")
        if section.image_count > NORMALIZE_SECTION_IMAGES:
            reasons.append(f"section-images:{path}")
    inspection = EpubInspection(
        rootfile=package.opf_path,
        spine_count=len(sections),
        archive_size_bytes=source.stat().st_size,
        archive_uncompressed_bytes=sum(info.file_size for info in archive.infolist()),
        sections=tuple(sections),
        reasons=tuple(dict.fromkeys(reasons)),
    )
    return inspection, package, names, documents


def inspect_libmobi_epub(path: str | Path) -> EpubInspection:
    source = Path(path)
    try:
        with zipfile.ZipFile(source) as archive:
            inspection, _package, _names, _documents = _inspect_open_archive(archive, source)
            return inspection
    except EpubNormalizationError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise EpubNormalizationError(f"EPUB 检查失败：{exc}") from exc


def validate_normalized_epub(path: str | Path) -> EpubInspection:
    inspection = inspect_libmobi_epub(path)
    if inspection.reasons:
        raise EpubNormalizationError(f"标准化 EPUB 仍未满足约束：{', '.join(inspection.reasons)}")
    return inspection


def _normalize_private_markup(document: etree._Element) -> None:
    for node in document.iter():
        if not isinstance(node.tag, str):
            continue
        tag = node.tag.lower()
        if tag == "mbp:pagebreak":
            node.tag = "span"
            node.set("data-shuku-pagebreak", "true")
            node.set("aria-hidden", "true")
        elif ":" in node.tag and not node.tag.startswith("{"):
            raise EpubNormalizationError(f"无法安全处理私有标签：{node.tag}")

        for attribute in list(node.attrib):
            if attribute.startswith("{") or ":" not in attribute:
                continue
            prefix, _, local = attribute.partition(":")
            value = node.attrib.pop(attribute)
            if prefix == "epub":
                node.set(f"{{{EPUB_NAMESPACE}}}{local}", value)
            elif prefix == "xlink":
                node.set(f"{{{XLINK_NAMESPACE}}}{local}", value)
            elif prefix == "xml":
                node.set(f"{{{XML_NAMESPACE}}}{local}", value)
            elif prefix == "mbp":
                node.set(f"data-mbp-{local}", value)
            else:
                raise EpubNormalizationError(f"无法安全处理私有属性：{attribute}")


def _element_stats(element: etree._Element) -> _ChunkStats:
    return _document_stats(element, len(etree.tostring(element, encoding="utf-8", method="xml")))


def _contains_anchor(element: etree._Element, anchors: set[str]) -> bool:
    if not anchors:
        return False
    return any(
        value in anchors
        for node in element.iter()
        for value in ((node.get("id") or "").strip(), (node.get("name") or "").strip())
        if value
    )


def _split_body_children(body: etree._Element, preferred_anchors: set[str]) -> list[list[etree._Element]]:
    children = list(body)
    if not children:
        return [[]]
    chunks: list[list[etree._Element]] = []
    current: list[etree._Element] = []
    current_stats = _ChunkStats()
    for child in children:
        child_stats = _element_stats(child)
        if child_stats.exceeds_hard_limit():
            raise EpubNormalizationError("正文包含无法在不破坏结构的前提下拆分的超大节点")
        preferred = child.get("data-shuku-pagebreak") == "true" or _contains_anchor(child, preferred_anchors)
        if current and preferred and current_stats.reached_preferred_boundary_floor():
            chunks.append(current)
            current = []
            current_stats = _ChunkStats()
        candidate = current_stats.plus(child_stats)
        if current and candidate.exceeds_target():
            chunks.append(current)
            current = []
            current_stats = _ChunkStats()
        current.append(child)
        current_stats = current_stats.plus(child_stats)
    if current:
        chunks.append(current)
    return chunks


def _safe_head_copy(head: etree._Element | None, *, first: bool) -> etree._Element:
    result = etree.Element(f"{{{XHTML_NAMESPACE}}}head")
    if head is None:
        etree.SubElement(result, f"{{{XHTML_NAMESPACE}}}title").text = ""
        return result
    result.text = head.text
    for child in head:
        name = _local_name(child.tag)
        if first or name in {"title", "meta", "link", "style"}:
            copied = copy.deepcopy(child)
            if not first:
                for node in copied.iter():
                    node.attrib.pop("id", None)
                    node.attrib.pop("name", None)
            result.append(copied)
    if not any(_local_name(child.tag) == "title" for child in result):
        etree.SubElement(result, f"{{{XHTML_NAMESPACE}}}title").text = ""
    return result


def _build_chunk_document(
    source_document: etree._Element,
    children: list[etree._Element],
    *,
    first: bool,
    body_text: str | None,
) -> etree._Element:
    root = etree.Element(
        f"{{{XHTML_NAMESPACE}}}html",
        nsmap={None: XHTML_NAMESPACE, "epub": EPUB_NAMESPACE, "xlink": XLINK_NAMESPACE},
    )
    for attribute, value in source_document.attrib.items():
        if attribute not in {"xmlns", "xmlns:epub", "xmlns:xlink"}:
            root.set(attribute, value)
    head = source_document.find("head")
    root.append(_safe_head_copy(head, first=first))
    body = etree.SubElement(root, f"{{{XHTML_NAMESPACE}}}body")
    original_body = source_document.find("body")
    if original_body is not None:
        for attribute, value in original_body.attrib.items():
            body.set(attribute, value)
    body.text = body_text if first else None
    for child in children:
        body.append(copy.deepcopy(child))
    _normalize_private_markup(root)
    return root


def _serialized_xhtml(document: etree._Element) -> bytes:
    return etree.tostring(
        document,
        encoding="utf-8",
        xml_declaration=True,
        method="xml",
    )


def _hard_limit_document_chunks(
    source_document: etree._Element,
    chunks: list[list[etree._Element]],
) -> list[list[etree._Element]]:
    result: list[list[etree._Element]] = []
    pending = list(chunks)
    while pending:
        chunk = pending.pop(0)
        probe = _build_chunk_document(source_document, chunk, first=not result, body_text=None)
        stats = _document_stats(probe, len(_serialized_xhtml(probe)))
        if not stats.exceeds_hard_limit():
            result.append(chunk)
            continue
        if len(chunk) <= 1:
            raise EpubNormalizationError("拆章后仍存在无法安全拆分的超大章节")
        midpoint = len(chunk) // 2
        pending.insert(0, chunk[midpoint:])
        pending.insert(0, chunk[:midpoint])
    return result


def _new_chunk_path(original: str, index: int, occupied: set[str]) -> str:
    directory = posixpath.dirname(original)
    stem = PurePosixPath(original).stem
    candidate_index = index
    while True:
        name = f"{stem}-shuku-{candidate_index:04d}.xhtml"
        candidate = posixpath.join(directory, name) if directory else name
        if candidate not in occupied:
            occupied.add(candidate)
            return candidate
        candidate_index += 1


def _navigation_anchors(
    archive: zipfile.ZipFile,
    package: _Package,
    target_path: str,
) -> set[str]:
    result: set[str] = set()
    for item in package.manifest_items.values():
        media_type = (item.get("media-type") or "").lower()
        if media_type != "application/x-dtbncx+xml":
            continue
        ncx_path = _manifest_archive_path(package, item)
        ncx = _parse_xml(archive.read(ncx_path), ncx_path)
        for node in ncx.iter():
            if _local_name(node.tag) != "content" or not node.get("src"):
                continue
            resolved = _resolve_archive_path(ncx_path, str(node.get("src")))
            if resolved and resolved[0] == target_path and resolved[1]:
                result.add(resolved[1])
    for node in package.root.iter():
        if _local_name(node.tag) != "reference" or not node.get("href"):
            continue
        resolved = _resolve_archive_path(package.opf_path, str(node.get("href")))
        if resolved and resolved[0] == target_path and resolved[1]:
            result.add(resolved[1])
    return result


def _rewrite_url(
    href: str,
    *,
    source_origin: str,
    source_output: str,
    document_map: dict[str, list[str]],
    anchor_map: dict[tuple[str, str], str],
) -> str:
    resolved = _resolve_archive_path(source_origin, href)
    if resolved is None:
        return href
    target_path, fragment, query = resolved
    if fragment:
        mapped = anchor_map.get((target_path, fragment))
        if mapped is None:
            return href
        return _relative_href(source_output, mapped, fragment, query)
    mapped_documents = document_map.get(target_path)
    if not mapped_documents:
        return href
    return _relative_href(source_output, mapped_documents[0], "", query)


def _rewrite_document_urls(
    document: etree._Element,
    *,
    source_origin: str,
    source_output: str,
    document_map: dict[str, list[str]],
    anchor_map: dict[tuple[str, str], str],
) -> bool:
    changed = False
    for node, attribute, href in _iter_url_attributes(document):
        rewritten = _rewrite_url(
            href,
            source_origin=source_origin,
            source_output=source_output,
            document_map=document_map,
            anchor_map=anchor_map,
        )
        if rewritten != href:
            node.set(attribute, rewritten)
            changed = True
    return changed


def _element_namespace_tag(parent: etree._Element, local: str) -> str:
    if isinstance(parent.tag, str) and parent.tag.startswith("{"):
        namespace = parent.tag[1:].partition("}")[0]
        return f"{{{namespace}}}{local}"
    return local


def _insert_split_manifest_and_spine(
    package: _Package,
    section: EpubSectionMetrics,
    chunk_paths: list[str],
) -> None:
    if len(chunk_paths) <= 1:
        return
    original_item = package.manifest_items[section.item_id]
    original_ref = next(ref for ref in package.spine_refs if ref.get("idref") == section.item_id)
    used_ids = set(package.manifest_items)
    previous_item = original_item
    previous_ref = original_ref
    for index, chunk_path in enumerate(chunk_paths[1:], start=2):
        candidate = f"{section.item_id}-shuku-{index:04d}"
        suffix = index
        while candidate in used_ids:
            suffix += 1
            candidate = f"{section.item_id}-shuku-{suffix:04d}"
        used_ids.add(candidate)
        item = etree.Element(_element_namespace_tag(package.manifest, "item"))
        item.set("id", candidate)
        item.set("href", _relative_href(package.opf_path, chunk_path))
        item.set("media-type", "application/xhtml+xml")
        previous_item.addnext(item)
        previous_item = item
        package.manifest_items[candidate] = item

        itemref = copy.deepcopy(original_ref)
        itemref.set("idref", candidate)
        previous_ref.addnext(itemref)
        previous_ref = itemref


def _write_repacked_epub(
    source: Path,
    target: Path,
    replacements: dict[str, bytes],
    additions: dict[str, bytes],
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w") as output:
        mimetype = original.read("mimetype")
        output.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
        for info in original.infolist():
            if info.filename == "mimetype":
                continue
            data = replacements.get(info.filename)
            if data is None:
                data = original.read(info.filename)
            cloned = copy.copy(info)
            cloned.flag_bits &= ~1
            output.writestr(cloned, data)
        for path, data in additions.items():
            output.writestr(path, data, compress_type=zipfile.ZIP_DEFLATED)


def normalize_libmobi_epub(
    source_path: str | Path,
    target_path: str | Path,
    inspection: EpubInspection | None = None,
) -> EpubNormalizationResult:
    source = Path(source_path)
    target = Path(target_path)
    before = inspection or inspect_libmobi_epub(source)
    if not before.requires_normalization:
        shutil.copyfile(source, target)
        return EpubNormalizationResult(False, (), before, before)

    try:
        with zipfile.ZipFile(source) as archive:
            current, package, names, documents = _inspect_open_archive(archive, source)
            if current.reasons != before.reasons:
                before = current
            original_anchor_keys = set(_anchor_catalog(documents))
            section_by_path = {section.archive_path: section for section in before.sections}
            normalize_paths = {
                section.archive_path
                for section in before.sections
                if not section.strict_xhtml or section.exceeds_limits()
            }
            occupied = set(names)
            document_map = {path: [path] for path in documents}
            output_documents: dict[str, etree._Element] = {}
            output_origins: dict[str, str] = {}

            for path in normalize_paths:
                source_document = documents[path]
                _normalize_private_markup(source_document)
                body = source_document.find("body")
                if body is None:
                    raise EpubNormalizationError(f"正文缺少 body：{path}")
                preferred_anchors = _navigation_anchors(archive, package, path)
                raw_chunks = _split_body_children(body, preferred_anchors)
                chunks = _hard_limit_document_chunks(source_document, raw_chunks)
                chunk_paths = [path]
                for index in range(2, len(chunks) + 1):
                    chunk_paths.append(_new_chunk_path(path, index, occupied))
                document_map[path] = chunk_paths
                for index, (chunk, output_path) in enumerate(zip(chunks, chunk_paths, strict=True)):
                    output_documents[output_path] = _build_chunk_document(
                        source_document,
                        chunk,
                        first=index == 0,
                        body_text=body.text,
                    )
                    output_origins[output_path] = path

            anchor_map: dict[tuple[str, str], str] = {}
            for old_path, output_paths in document_map.items():
                if old_path not in normalize_paths:
                    for key in original_anchor_keys:
                        if key[0] == old_path:
                            anchor_map[key] = old_path
                    continue
                for output_path in output_paths:
                    document = output_documents[output_path]
                    for node in document.iter():
                        values = {
                            value
                            for value in ((node.get("id") or "").strip(), (node.get("name") or "").strip())
                            if value
                        }
                        for value in values:
                            key = (old_path, value)
                            if key in anchor_map:
                                raise EpubNormalizationError(f"拆章后出现重复锚点：{old_path}#{value}")
                            anchor_map[key] = output_path
            if set(anchor_map) != original_anchor_keys:
                missing = sorted(original_anchor_keys - set(anchor_map))[:10]
                raise EpubNormalizationError(f"标准化导致锚点丢失：{missing}")

            replacements: dict[str, bytes] = {}
            additions: dict[str, bytes] = {}
            for output_path, document in output_documents.items():
                origin = output_origins[output_path]
                _rewrite_document_urls(
                    document,
                    source_origin=origin,
                    source_output=output_path,
                    document_map=document_map,
                    anchor_map=anchor_map,
                )
                data = _serialized_xhtml(document)
                if output_path in names:
                    replacements[output_path] = data
                else:
                    additions[output_path] = data

            for path, document in documents.items():
                if path in normalize_paths:
                    continue
                strict_document = _parse_xml(archive.read(path), path)
                if _rewrite_document_urls(
                    strict_document,
                    source_origin=path,
                    source_output=path,
                    document_map=document_map,
                    anchor_map=anchor_map,
                ):
                    replacements[path] = _serialized_xhtml(strict_document)

            for section in before.sections:
                chunk_paths = document_map.get(section.archive_path, [section.archive_path])
                _insert_split_manifest_and_spine(package, section, chunk_paths)

            for node in package.root.iter():
                if _local_name(node.tag) != "reference" or not node.get("href"):
                    continue
                original = str(node.get("href"))
                rewritten = _rewrite_url(
                    original,
                    source_origin=package.opf_path,
                    source_output=package.opf_path,
                    document_map=document_map,
                    anchor_map=anchor_map,
                )
                if rewritten != original:
                    node.set("href", rewritten)

            for item in list(package.manifest_items.values()):
                if (item.get("media-type") or "").lower() != "application/x-dtbncx+xml":
                    continue
                ncx_path = _manifest_archive_path(package, item)
                ncx = _parse_xml(archive.read(ncx_path), ncx_path)
                changed = False
                for node in ncx.iter():
                    if _local_name(node.tag) != "content" or not node.get("src"):
                        continue
                    original = str(node.get("src"))
                    rewritten = _rewrite_url(
                        original,
                        source_origin=ncx_path,
                        source_output=ncx_path,
                        document_map=document_map,
                        anchor_map=anchor_map,
                    )
                    if rewritten != original:
                        node.set("src", rewritten)
                        changed = True
                if changed:
                    replacements[ncx_path] = etree.tostring(
                        ncx,
                        encoding="utf-8",
                        xml_declaration=True,
                        method="xml",
                    )

            replacements[package.opf_path] = etree.tostring(
                package.root,
                encoding="utf-8",
                xml_declaration=True,
                method="xml",
            )
            _write_repacked_epub(source, target, replacements, additions)

        after = validate_normalized_epub(target)
        return EpubNormalizationResult(True, before.reasons, before, after)
    except Exception:
        target.unlink(missing_ok=True)
        raise
