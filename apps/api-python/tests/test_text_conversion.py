from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest
from sqlalchemy import text

from app.core.auth import hash_password
from app.models.auth import User
from app.services.download_executor import assert_allowed_extension
from app.services.epub_normalizer import EPUB_NORMALIZER_VERSION
from app.services.text_conversion import ConversionFailure, convert_to_epub, detect_txt_encoding, source_format, validate_epub
from app.worker.importer import ImportOptions, import_managed_book
from app.worker.persistent_import_queue import claim_next_import_task, recover_stale_import_tasks
from tests.test_worker_importer import create_worker_tables


def write_valid_epub(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?><package><manifest><item id="c1" href="one.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c1"/></spine></package>',
        )
        archive.writestr("OEBPS/one.xhtml", "<html><body>converted</body></html>")


def insert_import_task(db, task_id: str, source: Path, *, status: str = "PENDING", retryable: bool = False) -> None:
    db.execute(
        text(
            "INSERT INTO ImportTask (id, origin, status, originalName, sourcePath, progress, duplicate, duration, retryable, attempts, createdAt, updatedAt) "
            "VALUES (:id, 'MANUAL', :status, :name, :path, 0, 0, 0, :retryable, 0, '2026-07-18 10:00:00', '2026-07-18 10:00:00')"
        ),
        {"id": task_id, "status": status, "name": source.name, "path": str(source), "retryable": retryable},
    )
    db.commit()


class SuccessfulRunner:
    def __init__(self) -> None:
        self.conversion_calls = 0

    def __call__(self, args, **_kwargs):
        if "-v" in args:
            return subprocess.CompletedProcess(args, 0, "mobitool build: test\nlibmobi: 0.12\n", "")
        self.conversion_calls += 1
        output_dir = Path(args[args.index("-o") + 1])
        write_valid_epub(output_dir / f"{Path(args[-1]).stem}.epub")
        return subprocess.CompletedProcess(args, 0, "converted", "")


def test_text_format_detection_and_txt_encoding(tmp_path):
    assert source_format(tmp_path / "book.mobi") == "MOBI"
    assert source_format(tmp_path / "book.azw3") == "AZW3"
    assert source_format(tmp_path / "book.fb2") == "FB2"
    assert source_format(tmp_path / "book.pdf") is None

    utf8 = tmp_path / "utf8.txt"
    utf8.write_text("第一章\n内容", encoding="utf-8")
    gb18030 = tmp_path / "gb18030.txt"
    gb18030.write_bytes("第一章\n内容".encode("gb18030"))
    assert detect_txt_encoding(utf8) == "utf-8"
    assert detect_txt_encoding(gb18030) == "gb18030"


@pytest.mark.parametrize("extension", ["mobi", "azw", "azw3", "prc", "fb2", "txt"])
def test_download_entry_accepts_all_convertible_text_formats(extension):
    assert_allowed_extension(f"novel.{extension}")


def test_conversion_validates_output_and_reuses_versioned_cache(db_session, test_settings, tmp_path):
    create_worker_tables(db_session)
    source = tmp_path / "novel.azw3"
    source.write_bytes(b"fake azw3 source")
    insert_import_task(db_session, "task-1", source)
    runner = SuccessfulRunner()

    first = convert_to_epub(db_session, test_settings, "task-1", source, runner=runner)
    assert first.cached is False
    assert first.source_format == "AZW3"
    assert validate_epub(first.output_path)["spineCount"] == 1

    insert_import_task(db_session, "task-2", source)
    second = convert_to_epub(db_session, test_settings, "task-2", source, runner=runner)
    assert second.cached is True
    assert second.output_path == first.output_path
    assert runner.conversion_calls == 1
    conversion = db_session.execute(text("SELECT status, converterVersion FROM BookConversionTask WHERE importTaskId = 'task-2'")).mappings().one()
    assert conversion["status"] == "COMPLETED"
    assert "mobitool" in conversion["converterVersion"]
    assert EPUB_NORMALIZER_VERSION in conversion["converterVersion"]
    normalization = db_session.execute(
        text("SELECT optionsJson FROM BookConversionTask WHERE importTaskId = 'task-2'")
    ).scalar_one()
    assert '"normalizerVersion": "shuku-epub-normalizer/1"' in normalization
    assert '"normalizationApplied": true' in normalization


def test_txt_is_converted_internally_with_detected_chapters(db_session, test_settings, tmp_path):
    create_worker_tables(db_session)
    source = tmp_path / "中文小说.txt"
    source.write_text(
        "序章\n\n这是序章第一段。\n这是序章第二段。\n\n第一章 初见\n\n第一章内容。\n\n第二章 重逢\n\n第二章内容。",
        encoding="utf-8",
    )
    insert_import_task(db_session, "task-txt", source)

    def external_runner_must_not_run(_args, **_kwargs):
        raise AssertionError("TXT conversion must not invoke libmobi")

    artifact = convert_to_epub(db_session, test_settings, "task-txt", source, runner=external_runner_must_not_run)

    assert artifact.converter == "shuku-internal"
    assert artifact.converter_version == "shuku-internal-epub/2"
    assert validate_epub(artifact.output_path)["spineCount"] >= 3
    conversion = db_session.execute(
        text("SELECT converter, optionsJson FROM BookConversionTask WHERE importTaskId = 'task-txt'")
    ).mappings().one()
    assert conversion["converter"] == "shuku-internal"
    assert '"chapterCount": 3' in conversion["optionsJson"]
    with zipfile.ZipFile(artifact.output_path) as archive:
        opf_name = next(name for name in archive.namelist() if name.endswith(".opf"))
        package = ElementTree.fromstring(archive.read(opf_name))
        spine_idrefs = [node.attrib.get("idref") for node in package.iter() if node.tag.endswith("itemref")]
        assert "nav" not in spine_idrefs
        chapters = [name for name in archive.namelist() if "/chapters/" in name and name.endswith(".xhtml")]
        chapter_html = archive.read(chapters[0]).decode("utf-8")
        assert 'href="../styles/main.css"' in chapter_html
        assert "<p>这是序章第一段。</p>" in chapter_html
        assert "<p>这是序章第二段。</p>" in chapter_html
        assert "<br" not in chapter_html


def test_epub_validation_rejects_missing_document_resources(tmp_path):
    epub_path = tmp_path / "broken-reference.epub"
    with zipfile.ZipFile(epub_path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?><package><manifest><item id="c1" href="one.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c1"/></spine></package>',
        )
        archive.writestr(
            "OEBPS/one.xhtml",
            '<html><head><link href="missing.css" rel="stylesheet"/></head><body>converted</body></html>',
        )

    with pytest.raises(ConversionFailure, match="文档引用不存在"):
        validate_epub(epub_path)


def test_fb2_is_converted_internally_with_metadata_and_image(db_session, test_settings, tmp_path):
    create_worker_tables(db_session)
    source = tmp_path / "sample.fb2"
    source.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">
  <description><title-info><genre>fiction</genre><author><first-name>测试</first-name><last-name>作者</last-name></author>
    <book-title>FB2 测试书</book-title><lang>zh-CN</lang><coverpage><image l:href="#cover"/></coverpage>
  </title-info></description>
  <body><section><title><p>第一章</p></title><p>正文<emphasis>重点</emphasis><a l:href="#note-1">注释</a></p><image l:href="#cover"/></section></body>
  <body name="notes"><section id="note-1"><title><p>注释</p></title><p>跨章节注释内容。</p></section></body>
  <binary id="cover" content-type="image/png">iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=</binary>
</FictionBook>""",
        encoding="utf-8",
    )
    insert_import_task(db_session, "task-fb2", source)

    artifact = convert_to_epub(db_session, test_settings, "task-fb2", source)

    assert artifact.converter == "shuku-internal"
    assert validate_epub(artifact.output_path)["spineCount"] >= 1
    with zipfile.ZipFile(artifact.output_path) as archive:
        names = archive.namelist()
        assert any(name.endswith(".png") for name in names)
        opf = archive.read(next(name for name in names if name.endswith(".opf"))).decode("utf-8")
        assert "FB2 测试书" in opf
        chapter_html = "\n".join(archive.read(name).decode("utf-8") for name in names if "/chapters/" in name)
        assert "chapter-0002.xhtml#note-1" in chapter_html


def test_importer_converts_text_ebook_then_records_provenance(db_session, test_settings, tmp_path, monkeypatch):
    create_worker_tables(db_session)
    source = tmp_path / "[转换小说][测试作者].azw3"
    source.write_bytes(b"fake azw3 source")
    runner = SuccessfulRunner()
    monkeypatch.setattr("app.services.text_conversion._command_runner", runner)

    result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=source, origin="MANUAL", original_name=source.name),
    )

    assert result.format == "epub"
    assert result.type == "ebook"
    assert source.exists()
    library_file = db_session.execute(text("SELECT path FROM LibraryFile")).scalar_one()
    assert library_file.endswith(".epub")
    provenance = db_session.execute(text("SELECT rawJson FROM LibraryMetadata WHERE source = 'conversion'")).scalar_one()
    assert '"sourceFormat": "AZW3"' in provenance
    assert '"targetFormat": "EPUB"' in provenance
    assert '"converter": "libmobi"' in provenance


@pytest.mark.parametrize(
    ("stderr", "expected_code", "retryable"),
    [
        ("This book is locked by DRM encryption", "DRM_PROTECTED", False),
        ("converter crashed unexpectedly", "CONVERSION_FAILED", True),
    ],
)
def test_conversion_records_actionable_failures(db_session, test_settings, tmp_path, stderr, expected_code, retryable):
    create_worker_tables(db_session)
    source = tmp_path / "novel.mobi"
    source.write_bytes(b"fake mobi source")
    insert_import_task(db_session, "task-failed", source)

    def failed_runner(args, **_kwargs):
        if "-v" in args:
            return subprocess.CompletedProcess(args, 0, "mobitool build: test\nlibmobi: 0.12", "")
        return subprocess.CompletedProcess(args, 1, "", stderr)

    with pytest.raises(ConversionFailure) as raised:
        convert_to_epub(db_session, test_settings, "task-failed", source, runner=failed_runner)

    assert raised.value.code == expected_code
    task = db_session.execute(text("SELECT errorCode, retryable FROM ImportTask WHERE id = 'task-failed'")).mappings().one()
    conversion = db_session.execute(text("SELECT status, errorCode, retryable FROM BookConversionTask WHERE importTaskId = 'task-failed'")).mappings().one()
    assert task["errorCode"] == expected_code
    assert bool(task["retryable"]) is retryable
    assert conversion["status"] == "FAILED"
    assert conversion["errorCode"] == expected_code


def test_missing_converter_is_retryable_and_keeps_source(db_session, test_settings, tmp_path):
    create_worker_tables(db_session)
    source = tmp_path / "novel.mobi"
    source.write_bytes(b"fake mobi source")
    insert_import_task(db_session, "task-missing-converter", source)

    def unavailable_runner(_args, **_kwargs):
        raise FileNotFoundError("mobitool")

    with pytest.raises(ConversionFailure) as raised:
        convert_to_epub(db_session, test_settings, "task-missing-converter", source, runner=unavailable_runner)

    assert raised.value.code == "CONVERTER_UNAVAILABLE"
    assert raised.value.retryable is True
    assert source.read_bytes() == b"fake mobi source"


def test_libmobi_success_without_output_still_classifies_drm(db_session, test_settings, tmp_path):
    create_worker_tables(db_session)
    source = tmp_path / "protected.azw3"
    source.write_bytes(b"fake protected source")
    insert_import_task(db_session, "task-drm-no-output", source)

    def drm_runner(args, **_kwargs):
        if "-v" in args:
            return subprocess.CompletedProcess(args, 0, "mobitool build: test\nlibmobi: 0.12", "")
        return subprocess.CompletedProcess(args, 0, "Document is encrypted", "")

    with pytest.raises(ConversionFailure) as raised:
        convert_to_epub(db_session, test_settings, "task-drm-no-output", source, runner=drm_runner)

    assert raised.value.code == "DRM_PROTECTED"
    assert raised.value.retryable is False


def test_invalid_epub_output_is_rejected_without_publishing_partial_file(db_session, test_settings, tmp_path):
    create_worker_tables(db_session)
    source = tmp_path / "novel.prc"
    source.write_bytes(b"fake prc source")
    insert_import_task(db_session, "task-invalid-output", source)

    def invalid_output_runner(args, **_kwargs):
        if "-v" in args:
            return subprocess.CompletedProcess(args, 0, "mobitool build: test\nlibmobi: 0.12", "")
        output_dir = Path(args[args.index("-o") + 1])
        (output_dir / f"{Path(args[-1]).stem}.epub").write_bytes(b"not an epub")
        return subprocess.CompletedProcess(args, 0, "converted", "")

    with pytest.raises(ConversionFailure) as raised:
        convert_to_epub(db_session, test_settings, "task-invalid-output", source, runner=invalid_output_runner)

    assert raised.value.code == "INVALID_EPUB_OUTPUT"
    conversion = db_session.execute(text("SELECT outputPath, status FROM BookConversionTask WHERE importTaskId = 'task-invalid-output'")).mappings().one()
    assert conversion["status"] == "FAILED"
    assert conversion["outputPath"] is None
    assert list(test_settings.conversion_root.rglob("*.epub")) == []


def test_libmobi_normalization_failure_is_retryable_and_never_publishes_raw_epub(
    db_session,
    test_settings,
    tmp_path,
):
    create_worker_tables(db_session)
    source = tmp_path / "duplicate-anchors.mobi"
    source.write_bytes(b"fake mobi source")
    insert_import_task(db_session, "task-normalization-failed", source)

    def duplicate_anchor_runner(args, **_kwargs):
        if "-v" in args:
            return subprocess.CompletedProcess(args, 0, "mobitool build: test\nlibmobi: 0.12", "")
        output_dir = Path(args[args.index("-o") + 1])
        output = output_dir / f"{Path(args[-1]).stem}.epub"
        write_valid_epub(output)
        with zipfile.ZipFile(output) as original:
            entries = [(info, original.read(info.filename)) for info in original.infolist()]
        with zipfile.ZipFile(output, "w") as rewritten:
            for info, data in entries:
                if info.filename == "OEBPS/one.xhtml":
                    data = b'<html><body><a id="duplicate"></a><a id="duplicate"></a></body></html>'
                rewritten.writestr(info, data)
        return subprocess.CompletedProcess(args, 0, "converted", "")

    with pytest.raises(ConversionFailure) as raised:
        convert_to_epub(
            db_session,
            test_settings,
            "task-normalization-failed",
            source,
            runner=duplicate_anchor_runner,
        )

    assert raised.value.code == "EPUB_NORMALIZATION_FAILED"
    assert raised.value.retryable is True
    assert source.read_bytes() == b"fake mobi source"
    assert list(test_settings.conversion_root.rglob("*.epub")) == []
    conversion = db_session.execute(
        text(
            "SELECT status, errorCode, retryable, outputPath FROM BookConversionTask "
            "WHERE importTaskId = 'task-normalization-failed'"
        )
    ).mappings().one()
    assert conversion["status"] == "FAILED"
    assert conversion["errorCode"] == "EPUB_NORMALIZATION_FAILED"
    assert bool(conversion["retryable"]) is True
    assert conversion["outputPath"] is None


def test_direct_user_epub_import_bypasses_libmobi_normalizer(
    db_session,
    test_settings,
    tmp_path,
    monkeypatch,
):
    create_worker_tables(db_session)
    source = tmp_path / "[用户EPUB][测试作者].epub"
    write_valid_epub(source)

    def normalizer_must_not_run(_path):
        raise AssertionError("Direct EPUB imports must not invoke the libmobi normalizer")

    monkeypatch.setattr("app.services.text_conversion.inspect_libmobi_epub", normalizer_must_not_run)

    result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=source, origin="MANUAL", original_name=source.name),
    )

    assert result.format == "epub"
    assert db_session.execute(text("SELECT COUNT(*) FROM BookConversionTask")).scalar_one() == 0


def test_single_import_worker_recovers_interrupted_task_without_waiting_for_lease(db_session, test_settings, tmp_path):
    create_worker_tables(db_session)
    source = tmp_path / "queued.epub"
    source.write_bytes(b"queued")
    insert_import_task(db_session, "task-stale", source, status="PARSING")
    db_session.execute(
        text(
            "UPDATE ImportTask SET leaseOwner = 'old-worker', leaseExpiresAt = 9999999999999 "
            "WHERE id = 'task-stale'"
        )
    )
    db_session.commit()

    assert recover_stale_import_tasks(db_session) == 1
    claimed = claim_next_import_task(db_session, "worker-new", 900)
    assert claimed is not None
    assert claimed["id"] == "task-stale"
    assert claimed["status"] == "PARSING"
    assert claimed["attempts"] == 1
    assert claim_next_import_task(db_session, "worker-other", 900) is None


def test_persistent_queue_claims_by_created_timestamp_then_id(db_session, tmp_path):
    create_worker_tables(db_session)
    timestamp = 1784731371000
    for task_id in ("task-c", "task-a", "task-b"):
        source = tmp_path / f"{task_id}.epub"
        source.write_bytes(task_id.encode())
        insert_import_task(db_session, task_id, source)
        db_session.execute(
            text("UPDATE ImportTask SET createdAt = :created_at, updatedAt = :created_at WHERE id = :id"),
            {"created_at": timestamp, "id": task_id},
        )
        db_session.commit()

    claimed_ids = []
    for index in range(3):
        claimed = claim_next_import_task(db_session, f"worker-{index}", 900)
        assert claimed is not None
        claimed_ids.append(claimed["id"])

    assert claimed_ids == ["task-a", "task-b", "task-c"]


def test_azw3_upload_is_queued_and_retry_endpoint_resets_recoverable_failure(client, db_session, test_settings, tmp_path):
    create_worker_tables(db_session)
    test_settings.resolved_monitor_root.mkdir(parents=True, exist_ok=True)
    user = User(email="conversion@example.com", name="管理员", password_hash=hash_password("starshipnas"), role="admin")
    db_session.add(user)
    db_session.commit()
    assert client.post("/api/auth/login", json={"email": user.email, "password": "starshipnas"}).status_code == 200

    upload_dir = test_settings.resolved_monitor_root / "uploads"
    upload_dir.mkdir()
    response = client.post(
        "/api/works/import",
        data={"targetPath": str(upload_dir)},
        files={"file": ("novel.azw3", b"fake azw3 source", "application/octet-stream")},
    )
    assert response.status_code == 200
    assert response.json()["data"]["queued"] == 1
    task = db_session.execute(text("SELECT * FROM ImportTask WHERE originalName = 'novel.azw3'")).mappings().one()
    db_session.execute(
        text("UPDATE ImportTask SET status = 'FAILED', retryable = 1, errorCode = 'CONVERSION_TIMEOUT', errorSummary = 'timeout' WHERE id = :id"),
        {"id": task["id"]},
    )
    db_session.commit()

    retried = client.post(f"/api/import-tasks/{task['id']}/retry")
    assert retried.status_code == 200
    assert retried.json()["data"]["task"]["status"] == "PENDING"
    assert retried.json()["data"]["task"]["errorCode"] is None
    rejected = client.post(f"/api/import-tasks/{task['id']}/retry")
    assert rejected.status_code == 400
