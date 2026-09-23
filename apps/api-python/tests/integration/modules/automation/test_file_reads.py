import hashlib
import os
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZipFile

import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from app.bootstrap.automation import (
    build_automation_catalog,
    build_automation_settings,
    build_grant_manager,
)
from app.models import Library, LibrarySourceNode
from app.models.organize import MetadataWritebackPreparation
from app.modules.automation.application.settings import AutomationServiceSettings
from app.modules.automation.domain.access import AutomationAccessError, Scope
from app.modules.library.public import SourceAccessError
from app.modules.metadata.application.opf import serialize_opf_metadata
from app.modules.metadata.public import PublicationMetadata, StandardMetadataError
from tests.integration.modules.automation.test_metadata_patches import setup_metadata


def file_access(db, tmp_path):
    access = setup_metadata(db)
    access = replace(
        access,
        permissions=replace(
            access.permissions, scopes=access.permissions.scopes | {Scope.SYSTEM_READ}
        ),
    )
    grant = build_grant_manager(db).create(
        user_id=access.user_id, name="file metadata", permissions=access.permissions
    )
    access = replace(access, grant_id=grant.grant.id)
    build_automation_settings(db).update(
        access.user_id,
        AutomationServiceSettings(
            enabled=True,
            enabled_scopes=access.permissions.scopes,
            public_base_url="http://localhost",
        ),
    )
    root = tmp_path / "library"
    (root / "allowed").mkdir(parents=True)
    db.get(Library, "test-library").root_path = str(root)
    db.commit()
    return access, root


def add_file(db, node_id, relative, *, parent="allowed-node", kind="REGULAR_FILE"):
    db.add(
        LibrarySourceNode(
            id=node_id,
            library_id="test-library",
            parent_id=parent,
            parent_physical_kind="DIRECTORY" if parent else None,
            relative_path=relative,
            path_key="v1:" + hashlib.sha256(relative.encode()).hexdigest(),
            name=relative.rsplit("/", 1)[-1],
            physical_kind=kind,
            observed_size_bytes=0 if kind == "REGULAR_FILE" else None,
            observed_mtime_ns=0,
            observed_at=datetime.now(UTC),
        )
    )
    db.commit()


def opf(title="文件标题"):
    return serialize_opf_metadata(
        PublicationMetadata(title=title, authors=("作者",), description="简介")
    )


def test_source_browse_is_scoped_and_paginated_without_filesystem_mutation(
    db_session, tmp_path
):
    access, root = file_access(db_session, tmp_path)
    add_file(db_session, "a", "allowed/a.epub")
    add_file(db_session, "b", "allowed/b.epub")
    catalog = build_automation_catalog(db_session)
    first = catalog.list_source_nodes(access, "test-library", "allowed-node", 1, 1)
    second = catalog.list_source_nodes(access, "test-library", "allowed-node", 2, 1)
    assert first["total"] == second["total"] == 2
    assert first["nodes"][0]["node_id"] != second["nodes"][0]["node_id"]
    assert str(root) not in str(first)
    with pytest.raises(SourceAccessError, match="RESOURCE_NOT_FOUND"):
        catalog.list_source_nodes(access, "private-library", None, 1, 20)
    with pytest.raises(SourceAccessError, match="RESOURCE_NOT_FOUND"):
        catalog.list_source_nodes(access, "test-library", "secret-node", 1, 20)
    assert list((root / "allowed").iterdir()) == []


def test_opf_read_is_pure_and_ambiguous_sidecars_need_selection(db_session, tmp_path):
    access, root = file_access(db_session, tmp_path)
    first = root / "allowed/metadata.opf"
    first.write_bytes(opf())
    catalog = build_automation_catalog(db_session)
    initial = {
        str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    result = catalog.read_file_metadata(access, "allowed-node", "sidecar", None)
    assert result["metadata"]["title"] == "文件标题"
    assert result["relative_path"] == "allowed/metadata.opf"
    assert len(result["file_revision"]) == 64
    assert "title" in result["writable_fields"]
    assert "cover" not in result["writable_fields"]
    assert {
        str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()
    } == initial
    assert list(db_session.scalars(select(MetadataWritebackPreparation))) == []
    (root / "allowed/allowed.opf").write_bytes(opf("第二来源"))
    with pytest.raises(StandardMetadataError, match="AMBIGUOUS_SIDECAR"):
        catalog.read_file_metadata(access, "allowed-node", "sidecar", None)
    assert (
        catalog.read_file_metadata(
            access, "allowed-node", "sidecar", "allowed/allowed.opf"
        )["metadata"]["title"]
        == "第二来源"
    )
    with pytest.raises(StandardMetadataError, match="INVALID_SIDECAR_TARGET"):
        catalog.read_file_metadata(access, "allowed-node", "sidecar", "../secret.opf")


def test_missing_requested_sidecar_keeps_the_filesystem_cause(db_session, tmp_path):
    import errno

    access, _root = file_access(db_session, tmp_path)
    catalog = build_automation_catalog(db_session)
    with pytest.raises(StandardMetadataError, match="METADATA_NOT_FOUND") as failure:
        catalog.read_file_metadata(
            access, "allowed-node", "sidecar", "allowed/metadata.opf"
        )
    assert isinstance(failure.value.__cause__, FileNotFoundError)
    assert failure.value.__cause__.errno == errno.ENOENT


def test_embedded_epub_comic_pdf_read_without_extracting(db_session, tmp_path):
    access, root = file_access(db_session, tmp_path)
    epub = root / "allowed/book.epub"
    with ZipFile(epub, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OPS/content.opf"/></rootfiles></container>',
        )
        archive.writestr("OPS/content.opf", opf())
        archive.writestr("OPS/chapter.xhtml", "Original chapter")
    comic = root / "allowed/book.cbz"
    with ZipFile(comic, "w") as archive:
        archive.writestr(
            "ComicInfo.xml",
            "<ComicInfo><Title>漫画</Title><Writer>作者</Writer></ComicInfo>",
        )
        archive.writestr("page.jpg", b"original page")
    pdf = root / "allowed/book.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/Title": "PDF 标题", "/Author": "作者"})
    writer.xmp_metadata = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<rdf:RDF><rdf:Description rdf:about="">'
        '<dc:description><rdf:Alt><rdf:li xml:lang="x-default">XMP 简介'
        '</rdf:li></rdf:Alt></dc:description>'
        '<dc:subject><rdf:Bag><rdf:li>幻想\\冒险-成长</rdf:li></rdf:Bag></dc:subject>'
        '<dc:language><rdf:Bag><rdf:li>zh-CN</rdf:li></rdf:Bag></dc:language>'
        '</rdf:Description></rdf:RDF></x:xmpmeta>'
    ).encode()
    output = BytesIO()
    writer.write(output)
    pdf.write_bytes(output.getvalue())
    initial = {str(path): path.read_bytes() for path in (epub, comic, pdf)}
    catalog = build_automation_catalog(db_session)
    for index, (path, title) in enumerate(
        ((epub, "文件标题"), (comic, "漫画"), (pdf, "PDF 标题"))
    ):
        node_id = f"file-{index}"
        add_file(db_session, node_id, str(path.relative_to(root)))
        result = catalog.read_file_metadata(access, node_id, "embedded", None)
        assert result["metadata"]["title"] == title
        if path == pdf:
            assert result["metadata"]["description"] == "XMP 简介"
            assert result["metadata"]["subjects"] == ("幻想", "冒险", "成长")
            assert result["metadata"]["language"] == "zh-CN"
        assert path.read_bytes() == initial[str(path)]
    assert len(list((root / "allowed").iterdir())) == 3


def test_pdf_file_read_keeps_info_when_xmp_is_invalid(db_session, tmp_path):
    access, root = file_access(db_session, tmp_path)
    path = root / "allowed/bad-xmp.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/Title": "Info 标题", "/Author": "Info 作者"})
    writer.xmp_metadata = b"<rdf:RDF>"
    writer.write(path)
    original = path.read_bytes()
    add_file(db_session, "bad-xmp", "allowed/bad-xmp.pdf")

    result = build_automation_catalog(db_session).read_file_metadata(
        access, "bad-xmp", "embedded", None
    )

    assert result["metadata"]["title"] == "Info 标题"
    assert result["metadata"]["authors"] == ("Info 作者",)
    assert result["writable_fields"] == ()
    assert path.read_bytes() == original


def test_file_and_parent_symlinks_never_read_outside_the_root(db_session, tmp_path):
    access, root = file_access(db_session, tmp_path)
    external = tmp_path / "outside"
    external.mkdir()
    (external / "metadata.opf").write_bytes(opf("Secret"))
    (root / "allowed/metadata.opf").symlink_to(external / "metadata.opf")
    catalog = build_automation_catalog(db_session)
    with pytest.raises(SourceAccessError, match="SOURCE_UNAVAILABLE"):
        catalog.read_file_metadata(access, "allowed-node", "sidecar", None)
    (root / "allowed/metadata.opf").unlink()
    (root / "allowed").rmdir()
    (root / "allowed").symlink_to(external, target_is_directory=True)
    with pytest.raises(SourceAccessError, match="SOURCE_UNAVAILABLE"):
        catalog.read_file_metadata(access, "allowed-node", "sidecar", None)
    with pytest.raises(AutomationAccessError, match="RESOURCE_NOT_FOUND"):
        catalog.read_file_metadata(access, "secret-node", "sidecar", None)


def test_file_change_during_inspection_rejected(db_session, tmp_path, monkeypatch):
    from app.modules.metadata.infrastructure import standard_files

    access, root = file_access(db_session, tmp_path)
    source = root / "allowed/metadata.opf"
    source.write_bytes(opf())
    original = standard_files.parse_opf_metadata

    def concurrent_change(content):
        result = original(content)
        source.write_bytes(opf("Changed during read"))
        os.utime(source, ns=(1, 2))
        return result

    monkeypatch.setattr(standard_files, "parse_opf_metadata", concurrent_change)
    with pytest.raises(StandardMetadataError, match="SOURCE_CHANGED"):
        build_automation_catalog(db_session).read_file_metadata(
            access, "allowed-node", "sidecar", None
        )


@pytest.mark.parametrize("extension", ["mp3", "m4a", "m4b", "flac"])
def test_real_audio_metadata_read_is_bounded_and_preserves_bytes(
    db_session, tmp_path, extension
):
    import subprocess

    access, root = file_access(db_session, tmp_path)
    path = root / "allowed" / f"track.{extension}"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=22050:cl=mono",
            "-t",
            "0.1",
            "-metadata",
            "title=音轨",
            "-metadata",
            "artist=作者",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    before = path.read_bytes()
    add_file(db_session, "audio", f"allowed/track.{extension}")
    observation = build_automation_catalog(db_session).read_file_metadata(
        access, "audio", "embedded", None
    )
    assert observation["metadata"]["title"] == "音轨"
    assert observation["metadata"]["authors"] == ("作者",)
    assert path.read_bytes() == before


def test_invalid_relative_path_never_opens_a_file(tmp_path, monkeypatch):
    from app.modules.library.infrastructure.source_file_access import open_library_file

    def forbidden_open(*args, **kwargs):
        pytest.fail("invalid path reached os.open")

    monkeypatch.setattr(os, "open", forbidden_open)
    for path in ("../outside", "/absolute", "C:/drive", "a/../b", "a\\b", "a//b"):
        with (
            pytest.raises(SourceAccessError, match="INVALID_RELATIVE_PATH"),
            open_library_file(tmp_path, path),
        ):
            pytest.fail("invalid path was accepted")
