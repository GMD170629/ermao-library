from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO

from app.modules.publications.application.ports import PublicationSource
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationFingerprint,
    PublicationLink,
    PublicationResource,
    PublicationTocEntry,
)
from app.modules.publications.infrastructure.render_artifact import (
    build_render_artifact,
)


class FakePublicationAdapter:
    def __init__(self) -> None:
        self.publication = NormalizedPublication(
            identifier="urn:test:render",
            title="Render fixture",
            author="Author",
            language="en",
            reading_progression="ltr",
            fingerprint=PublicationFingerprint(
                original_file_hash="sha256:" + "a" * 64,
                parser="fixture-parser:1",
                normalization="fixture-source:1",
            ),
            reading_order=(
                PublicationLink("Text/one.xhtml", "application/xhtml+xml"),
                PublicationLink("Text/two.xhtml", "application/xhtml+xml"),
            ),
            resources=(PublicationLink("Images/cover.jpg", "image/jpeg"),),
            toc=(PublicationTocEntry("Text/one.xhtml#one", "One"),),
        )
        self.resources = {
            "Text/one.xhtml": PublicationResource(
                href="Text/one.xhtml",
                media_type="application/xhtml+xml",
                content=b'<html xmlns="http://www.w3.org/1999/xhtml"><head></head><body><h1 id="one">One</h1></body></html>',
                source_mtime=1,
            ),
            "Text/two.xhtml": PublicationResource(
                href="Text/two.xhtml",
                media_type="application/xhtml+xml",
                content=b'<html><head></head><body><p><img src="../Images/cover.jpg"></p></body></html>',
                source_mtime=1,
            ),
            "Images/cover.jpg": PublicationResource(
                href="Images/cover.jpg",
                media_type="image/jpeg",
                content=b"jpeg",
                source_mtime=1,
            ),
        }

    def open(self, source: PublicationSource) -> NormalizedPublication:
        return self.publication

    def read_resource(
        self, source: PublicationSource, href: str
    ) -> PublicationResource:
        return self.resources[href]


def test_render_artifact_is_deterministic_and_embeds_recovery_metadata() -> None:
    source = PublicationSource(
        volume_id="volume",
        file_id="file",
        source_format="epub",
        path="unused.epub",
        full_hash="a" * 64,
        title="Render fixture",
        author="Author",
    )
    adapter = FakePublicationAdapter()

    first = build_render_artifact(source=source, adapter=adapter)
    second = build_render_artifact(source=source, adapter=adapter)

    assert first == second
    assert first.content_hash == "sha256:" + hashlib.sha256(first.content).hexdigest()
    assert first.recovered_resource_count == 1
    with zipfile.ZipFile(BytesIO(first.content)) as archive:
        assert archive.namelist()[0] == "mimetype"
        assert archive.read("mimetype") == b"application/epub+zip"
        metadata = json.loads(archive.read("META-INF/shuku-render.json"))
        assert metadata["originalFileHash"] == "sha256:" + "a" * 64
        assert metadata["recoveredResourceCount"] == 1
        assert metadata["unreadableResources"] == []
        assert b"Content-Security-Policy" in archive.read("Text/one.xhtml")
        assert b'<img src="../Images/cover.jpg"' in archive.read("Text/two.xhtml")


def test_unrecoverable_page_keeps_its_href_and_exposes_safe_navigation() -> None:
    source = PublicationSource(
        volume_id="volume",
        file_id="file",
        source_format="epub",
        path="unused.epub",
        full_hash="a" * 64,
        title="Render fixture",
        author="Author",
    )
    adapter = FakePublicationAdapter()
    adapter.resources["Text/two.xhtml"] = PublicationResource(
        href="Text/two.xhtml",
        media_type="application/xhtml+xml",
        content=b"\x00",
        source_mtime=1,
    )

    artifact = build_render_artifact(source=source, adapter=adapter)

    assert artifact.unreadable_hrefs == ("Text/two.xhtml",)
    with zipfile.ZipFile(BytesIO(artifact.content)) as archive:
        page = archive.read("Text/two.xhtml")
        metadata = json.loads(archive.read("META-INF/shuku-render.json"))
    assert b'data-shuku-resource-error="RESOURCE_UNREADABLE"' in page
    assert b'rel="prev" href="one.xhtml"' in page
    assert b'rel="contents" href="../_shuku/nav.xhtml"' in page
    assert b'rel="next"' not in page
    assert metadata["unreadableResources"] == [
        {"code": "RESOURCE_UNREADABLE", "href": "Text/two.xhtml"}
    ]
