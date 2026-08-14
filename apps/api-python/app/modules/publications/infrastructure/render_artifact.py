"""Build deterministic, disposable EPUB render artifacts from original publications."""

from __future__ import annotations

import hashlib
import json
import posixpath
import zipfile
from io import BytesIO
from urllib.parse import unquote, urlsplit
from xml.sax.saxutils import escape, quoteattr

from app.modules.publications.application.ports import (
    PublicationAdapter,
    PublicationSource,
)
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationLink,
    PublicationResourceNotFoundError,
    PublicationStructureError,
    PublicationTocEntry,
)
from app.modules.publications.domain.rendering import (
    RENDER_ARTIFACT_MEDIA_TYPE,
    RENDER_ARTIFACT_SCHEMA_VERSION,
    RENDER_NORMALIZATION_IDENTIFIER,
    PreparedPublicationRenderArtifact,
)
from app.modules.publications.infrastructure.render_markup import (
    canonicalize_markup,
    unreadable_markup,
)

RENDER_ARTIFACT_PARSER_IDENTIFIER = "shuku-render-artifact:1"
_MIMETYPE = b"application/epub+zip"
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_MARKUP_MEDIA_TYPES = frozenset({"application/xhtml+xml", "text/html"})


def _archive_path(href: str) -> str:
    split = urlsplit(href)
    if split.scheme or split.netloc or split.query:
        raise PublicationStructureError("render resource href must be local")
    decoded = unquote(split.path)
    normalized = posixpath.normpath(decoded)
    if (
        not normalized
        or normalized in {".", ".."}
        or normalized.startswith(("../", "/"))
        or "\\" in normalized
    ):
        raise PublicationStructureError("render resource href escapes its artifact")
    return normalized


def _href_without_fragment(href: str) -> str:
    split = urlsplit(href)
    return split.path


def _navigation_markup(entries: tuple[PublicationTocEntry, ...]) -> bytes:
    def ordered_list(values: tuple[PublicationTocEntry, ...]) -> str:
        items = []
        for value in values:
            nested = ordered_list(value.children) if value.children else ""
            items.append(
                f"<li><a href={quoteattr('../' + value.href)}>"
                f"{escape(value.title)}</a>{nested}</li>"
            )
        return "<ol>" + "".join(items) + "</ol>"

    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head>'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'"/>'
        "<title>Table of Contents</title></head><body>"
        '<nav epub:type="toc">'
        f"{ordered_list(entries)}"
        "</nav></body></html>"
    ).encode()


def _package_markup(
    publication: NormalizedPublication,
    links: tuple[PublicationLink, ...],
) -> bytes:
    item_ids = {
        _href_without_fragment(link.href): f"resource-{index:06d}"
        for index, link in enumerate(links, start=1)
    }
    manifest = [
        (
            '<item id="shuku-nav" href="nav.xhtml" '
            'media-type="application/xhtml+xml" properties="nav"/>'
        )
    ]
    for link in links:
        href = _href_without_fragment(link.href)
        media_type = (
            "application/xhtml+xml"
            if link.media_type in _MARKUP_MEDIA_TYPES
            else link.media_type
        )
        manifest.append(
            f"<item id={quoteattr(item_ids[href])} href={quoteattr('../' + href)} "
            f"media-type={quoteattr(media_type)}/>"
        )
    spine = "".join(
        f"<itemref idref={quoteattr(item_ids[_href_without_fragment(link.href)])}/>"
        for link in publication.reading_order
    )
    progression = (
        ' page-progression-direction="rtl"'
        if publication.reading_progression == "rtl"
        else ""
    )
    language = publication.language or "und"
    author = (
        f"<dc:creator>{escape(publication.author)}</dc:creator>"
        if publication.author
        else ""
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="publication-id"><metadata '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:identifier id="publication-id">{escape(publication.identifier)}</dc:identifier>'
        f"<dc:title>{escape(publication.title)}</dc:title>{author}"
        f"<dc:language>{escape(language)}</dc:language>"
        '<meta property="dcterms:modified">1980-01-01T00:00:00Z</meta>'
        f"</metadata><manifest>{''.join(manifest)}</manifest>"
        f"<spine{progression}>{spine}</spine></package>"
    ).encode()


def _zip_info(name: str, *, stored: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _artifact_bytes(resources: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        archive.writestr(_zip_info("mimetype", stored=True), _MIMETYPE)
        for name in sorted(resources):
            archive.writestr(_zip_info(name), resources[name])
    return output.getvalue()


def build_render_artifact(
    *,
    source: PublicationSource,
    adapter: PublicationAdapter,
) -> PreparedPublicationRenderArtifact:
    publication = adapter.open(source)
    if not publication.reading_order:
        raise PublicationStructureError("render publication reading order is empty")

    ordered_links: list[PublicationLink] = []
    seen_paths: set[str] = set()
    for link in (*publication.reading_order, *publication.resources):
        path = _archive_path(link.href)
        if path in seen_paths or "contents" in link.rel:
            continue
        seen_paths.add(path)
        ordered_links.append(link)

    resources: dict[str, bytes] = {
        "META-INF/container.xml": (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
            b'version="1.0"><rootfiles><rootfile full-path="_shuku/package.opf" '
            b'media-type="application/oebps-package+xml"/></rootfiles></container>'
        ),
        "_shuku/nav.xhtml": _navigation_markup(publication.toc),
    }
    unreadable: list[str] = []
    recovered_count = 0
    included_links: list[PublicationLink] = []
    reading_paths = {_archive_path(link.href) for link in publication.reading_order}
    reading_links = list(publication.reading_order)
    reading_index = {
        _archive_path(link.href): index for index, link in enumerate(reading_links)
    }

    def error_markup(link: PublicationLink, path: str) -> bytes:
        index = reading_index[path]
        directory = posixpath.dirname(path) or "."
        previous_href = (
            posixpath.relpath(_archive_path(reading_links[index - 1].href), directory)
            if index > 0
            else None
        )
        next_href = (
            posixpath.relpath(_archive_path(reading_links[index + 1].href), directory)
            if index + 1 < len(reading_links)
            else None
        )
        return unreadable_markup(
            href=link.href,
            previous_href=previous_href,
            next_href=next_href,
            contents_href=posixpath.relpath("_shuku/nav.xhtml", directory),
        )

    for link in ordered_links:
        path = _archive_path(link.href)
        try:
            resource = adapter.read_resource(source, link.href)
        except PublicationResourceNotFoundError:
            if path not in reading_paths:
                continue
            resources[path] = error_markup(link, path)
            unreadable.append(link.href)
            included_links.append(
                PublicationLink(
                    link.href, "application/xhtml+xml", link.title, link.rel
                )
            )
            continue
        if link.media_type in _MARKUP_MEDIA_TYPES:
            rendered = canonicalize_markup(resource.content, href=link.href)
            resources[path] = (
                error_markup(link, path)
                if rendered.unreadable and path in reading_index
                else rendered.content
            )
            recovered_count += int(rendered.recovered)
            if rendered.unreadable:
                unreadable.append(link.href)
            included_links.append(
                PublicationLink(
                    link.href, "application/xhtml+xml", link.title, link.rel
                )
            )
        else:
            resources[path] = resource.content
            included_links.append(link)

    metadata = {
        "normalization": RENDER_NORMALIZATION_IDENTIFIER,
        "originalFileHash": publication.fingerprint.original_file_hash,
        "parser": publication.fingerprint.parser,
        "recoveredResourceCount": recovered_count,
        "schemaVersion": RENDER_ARTIFACT_SCHEMA_VERSION,
        "sourceFormat": source.source_format,
        "unreadableResources": [
            {"code": "RESOURCE_UNREADABLE", "href": href} for href in unreadable
        ],
    }
    resources["META-INF/shuku-render.json"] = json.dumps(
        metadata,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    resources["_shuku/package.opf"] = _package_markup(
        publication,
        tuple(included_links),
    )
    content = _artifact_bytes(resources)
    return PreparedPublicationRenderArtifact(
        content=content,
        content_hash=f"sha256:{hashlib.sha256(content).hexdigest()}",
        size_bytes=len(content),
        original_file_hash=publication.fingerprint.original_file_hash,
        source_parser=publication.fingerprint.parser,
        normalization=RENDER_NORMALIZATION_IDENTIFIER,
        unreadable_hrefs=tuple(unreadable),
        recovered_resource_count=recovered_count,
    )


__all__ = [
    "RENDER_ARTIFACT_MEDIA_TYPE",
    "RENDER_ARTIFACT_PARSER_IDENTIFIER",
    "ConfiguredPublicationRenderArtifactBuilder",
    "build_render_artifact",
]


class ConfiguredPublicationRenderArtifactBuilder:
    def __init__(self, adapter: PublicationAdapter) -> None:
        self._adapter = adapter

    def build(self, source: PublicationSource) -> PreparedPublicationRenderArtifact:
        return build_render_artifact(source=source, adapter=self._adapter)
