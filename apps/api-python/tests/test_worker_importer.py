import hashlib
import json
import zipfile
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from sqlalchemy import func, select, text

from app import models as _models  # noqa: F401
from app.bootstrap.imports import (
    fail_claimed_import_task,
    import_managed_book,
    process_import_task,
)
from app.db.base import Base
from app.models.import_pipeline import BookConversionTask, ImportTask
from app.models.library import (
    Library,
    LibraryFile,
    LibraryMediaVersion,
    LibraryMetadata,
    LibraryReadingUnit,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.models.organize import OrganizePolicy
from app.models.settings import SystemEvent
from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ImportOptions,
    ImportTaskDTO,
)
from app.modules.imports.application.import_comic import parse_comic_volume_from_name
from app.modules.imports.application.import_epub import parse_epub_metadata
from app.modules.imports.application.import_support import (
    _work_merge_key,
    parse_series_volume_info,
)
from app.modules.imports.application.transactions import (
    normalized_import_source_key,
    stable_import_resource_id,
)
from app.modules.imports.infrastructure.orchestration_services import (
    SessionImportOrchestrationServices,
)
from app.modules.imports.infrastructure.pdf_inspection import inspect_pdf
from app.modules.imports.infrastructure.task_mapper import import_task_dto_from_row
from app.modules.library.domain.version_identity import IMPLICIT_VERSION_SOURCE_KEY
from app.services.default_cover import DEFAULT_COVER_ASSET_PATH
from app.services.import_preferences import (
    SUPPORTED_IMPORT_EXTENSIONS,
    load_raw_import_preferences_projection,
    prepare_import_preferences,
)
from app.worker.path_security import (
    PathSecurityError,
    PathSecurityService,
)
from app.worker.watcher import (
    LibraryConfig,
    WatchState,
    WorkerManager,
    import_watched_file,
    library_config,
    scan_directory_with_logging,
    should_ignore_file,
)


def _options(**kwargs) -> ImportOptions:
    kwargs.setdefault("library_id", "test-library")
    return ImportOptions(**kwargs)


def create_worker_tables(db):
    Base.metadata.create_all(bind=db.get_bind())
    db.commit()


def add_library(db, root_path: Path, *, folder_id: str = "folder-1") -> None:
    db.add(
        Library(
            organization_mode="FLAT",
            id=folder_id,
            name=root_path.name,
            root_path=str(root_path),
            enabled=True,
        )
    )
    db.commit()


def create_metadata_provider_tables(db):
    db.execute(
        text(
            """CREATE TABLE IF NOT EXISTS MetadataSuggestion (
                id TEXT PRIMARY KEY, jobId TEXT, field TEXT, currentValue TEXT, suggestedValue TEXT,
                source TEXT, confidence REAL, reason TEXT, status TEXT, createdAt TEXT, updatedAt TEXT
            )"""
        )
    )
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS SystemSetting (`key` TEXT PRIMARY KEY, `value` TEXT, `createdAt` TEXT, `updatedAt` TEXT)"
        )
    )
    db.commit()


def set_system_setting(db, key: str, value: str):
    db.execute(
        text(
            "INSERT INTO SystemSetting (`key`, `value`, `createdAt`, `updatedAt`) VALUES (:key, :value, 'now', 'now')"
        ),
        {"key": key, "value": value},
    )
    db.commit()


def serve_import_metadata_gateways():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def json_response(self, payload):
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            requests.append({"method": "GET", "path": self.path})
            if self.path.startswith("/v2/book/search") or self.path.startswith(
                "/v2/book/isbn/"
            ):
                self.json_response({"books": []})
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("content-length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            requests.append({"method": "POST", "path": self.path, "body": body})
            if self.path == "/v0/search/subjects":
                self.json_response(
                    {
                        "data": [
                            {
                                "id": 99,
                                "name": "Starship Novel",
                                "name_cn": "目录测试",
                                "summary": "Bangumi fallback description",
                                "date": "2024-04-01",
                                "tags": [{"name": "科幻"}, {"name": "小说"}],
                                "infobox": [
                                    {"key": "作者", "value": "Bangumi 作者"},
                                    {"key": "出版社", "value": "Bangumi 出版社"},
                                    {"key": "册数", "value": "2"},
                                ],
                            }
                        ]
                    }
                )
                return
            self.send_response(404)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.requests = requests
    return server


def _count(db, table):
    return db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()


def write_epub_fixture(path: Path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?><container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0"?><package><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:title>目录测试</dc:title><dc:creator>测试作者</dc:creator><dc:subject>fiction</dc:subject>
            </metadata><manifest>
            <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
            <item id="c1" href="one.xhtml" media-type="application/xhtml+xml"/>
            <item id="c2" href="two.xhtml" media-type="application/xhtml+xml"/>
            <item id="cover" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>
            </manifest><spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>""",
        )
        archive.writestr(
            "OEBPS/nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"
            xmlns:epub="http://www.idpf.org/2007/ops"><head><title>目录</title>
            </head><body><nav epub:type="toc"><ol>
            <li><a href="one.xhtml">第一节</a></li>
            <li><a href="two.xhtml">第二节</a></li>
            </ol></nav></body></html>""",
        )
        archive.writestr(
            "OEBPS/one.xhtml",
            "<html><head><title>第一节</title></head>"
            "<body><h1>fallback</h1></body></html>",
        )
        archive.writestr(
            "OEBPS/two.xhtml",
            "<html><head><title>第二节</title></head>"
            "<body><h1>fallback</h1></body></html>",
        )
        archive.writestr("OEBPS/cover.jpg", b"fake-jpeg")


def write_epub_cover_reference_fixture(
    path: Path, cover_href: str, cover_entry: str | None = None
):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?><container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            f"""<?xml version="1.0"?><package><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:title>可选封面测试</dc:title><dc:creator>测试作者</dc:creator>
            </metadata><manifest>
            <item id="c1" href="one.xhtml" media-type="application/xhtml+xml"/>
            <item id="cover" href="{cover_href}" media-type="image/jpeg" properties="cover-image"/>
            </manifest><spine><itemref idref="c1"/></spine></package>""",
        )
        archive.writestr(
            "OEBPS/one.xhtml",
            "<html><head><title>正文</title></head><body><h1>正文</h1></body></html>",
        )
        if cover_entry:
            archive.writestr(cover_entry, b"optional-cover")


def write_epub_metadata_fixture(
    path: Path,
    title: str,
    author: str,
    identifiers: list[str] | None = None,
    *,
    description: str | None = None,
    subjects: tuple[str, ...] = (),
):
    identifier_xml = "\n".join(
        f"<dc:identifier>{identifier}</dc:identifier>"
        for identifier in identifiers or []
    )
    description_xml = (
        f"<dc:description>{description}</dc:description>" if description else ""
    )
    subject_xml = "\n".join(
        f"<dc:subject>{subject}</dc:subject>" for subject in subjects
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?><container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            f"""<?xml version="1.0"?><package><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            {identifier_xml}<dc:title>{title}</dc:title><dc:creator>{author}</dc:creator>
            {description_xml}{subject_xml}
            </metadata><manifest>
            <item id="c1" href="one.xhtml" media-type="application/xhtml+xml"/>
            </manifest><spine><itemref idref="c1"/></spine></package>""",
        )
        archive.writestr("OEBPS/one.xhtml", "<html><body><h1>正文</h1></body></html>")


def write_epub_nav_fixture(path: Path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?><container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0"?><package><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:title>目录选择测试</dc:title><dc:creator>测试作者</dc:creator><dc:identifier>urn:isbn:9787111111115</dc:identifier>
            <dc:language>zh-CN</dc:language><dc:publisher>测试出版社</dc:publisher><dc:subject>悬疑</dc:subject><dc:subject>推理</dc:subject>
            <meta name="cover" content="cover"/>
            </metadata><manifest>
            <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
            <item id="cover" href="cover.jpg" media-type="image/jpeg"/>
            <item id="c1" href="chapters/one.xhtml" media-type="application/xhtml+xml"/>
            <item id="c2" href="chapters/two.xhtml" media-type="application/xhtml+xml"/>
            </manifest><spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>""",
        )
        archive.writestr(
            "OEBPS/nav.xhtml",
            """<html><body>
            <nav epub:type="landmarks"><ol><li><a href="cover.xhtml">封面</a></li></ol></nav>
            <nav epub:type="toc"><ol><li><a href="chapters/one.xhtml">第一节</a></li><li><a href="chapters/two.xhtml#p2">第二节</a></li></ol></nav>
            </body></html>""",
        )
        archive.writestr(
            "OEBPS/chapters/one.xhtml",
            "<html><body><h1>fallback one</h1></body></html>",
        )
        archive.writestr(
            "OEBPS/chapters/two.xhtml",
            "<html><body><h1>fallback two</h1></body></html>",
        )
        archive.writestr("OEBPS/cover.jpg", b"fake-jpeg")


def write_epub_ncx_fixture(path: Path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?><container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0"?><package><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:title>NCX 目录测试</dc:title><dc:creator>测试作者</dc:creator>
            </metadata><manifest>
            <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
            <item id="c1" href="Text/chapter01.xhtml" media-type="application/xhtml+xml"/>
            <item id="c2" href="Text/chapter02.xhtml" media-type="application/xhtml+xml"/>
            </manifest><spine toc="ncx"><itemref idref="c1"/><itemref idref="c2"/></spine></package>""",
        )
        archive.writestr(
            "OEBPS/toc.ncx",
            """<?xml version="1.0" encoding="UTF-8"?><ncx><navMap>
            <navPoint><navLabel><text>序幕 苏格兰</text></navLabel><content src="Text/chapter01.xhtml#start"/></navPoint>
            <navPoint><navLabel><text>食人树</text></navLabel><content src="Text/chapter02.xhtml"/></navPoint>
            </navMap></ncx>""",
        )
        archive.writestr(
            "OEBPS/Text/chapter01.xhtml",
            "<html><body><h1>不应优先使用</h1></body></html>",
        )
        archive.writestr(
            "OEBPS/Text/chapter02.xhtml",
            "<html><body><h1>不应优先使用</h1></body></html>",
        )


def write_epub_without_toc_fixture(path: Path, one_body: str, two_body: str):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?><container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0"?><package><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:title>无目录测试</dc:title><dc:creator>测试作者</dc:creator>
            </metadata><manifest>
            <item id="c1" href="one.xhtml" media-type="application/xhtml+xml"/>
            <item id="c2" href="two.xhtml" media-type="application/xhtml+xml"/>
            </manifest><spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>""",
        )
        archive.writestr("OEBPS/one.xhtml", f"<html><body>{one_body}</body></html>")
        archive.writestr("OEBPS/two.xhtml", f"<html><body>{two_body}</body></html>")


def write_comic_fixture(path: Path, volume: int = 1, cover_bytes: bytes = b"one"):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "ComicInfo.xml",
            f"""<ComicInfo><Title>第{volume}卷</Title><Series>星舰漫画</Series><Volume>{volume}</Volume><Writer>画师</Writer><Publisher>星舰出版社</Publisher><Summary>漫画简介</Summary><Tags>manga,space</Tags><Pages><Page Image="0" Type="FrontCover"/></Pages></ComicInfo>""",
        )
        archive.writestr("001.jpg", cover_bytes)
        archive.writestr("002.jpg", b"two")


def write_pdf_fixture(path: Path):
    path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >> endobj\n"
        b"trailer << /Root 1 0 R >>\n%%EOF\n"
    )


def write_text_pdf_fixture(path: Path, text_value: str) -> None:
    encoded_text = (
        text_value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    )
    content = f"BT /F1 12 Tf 20 100 Td ({encoded_text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        (
            b"<< /Length "
            + str(len(content)).encode("ascii")
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode("ascii"))
        payload.extend(body)
        payload.extend(b"\nendobj\n")
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        (
            f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(payload)


def write_pdf_metadata_fixture(
    path: Path,
    *,
    title: str = "星舰手册",
    author: str = "作者甲",
):
    info = (
        f"/Title ({title}) /Author ({author}) "
        "/Subject (PDF 简介) /Keywords (space,manual,science)"
    )
    path.write_bytes(
        (
            "%PDF-1.4\n"
            "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
            "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
            "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >> endobj\n"
            f"4 0 obj << {info} >> endobj\n"
            "trailer << /Root 1 0 R /Info 4 0 R >>\n%%EOF\n"
        ).encode()
    )


def test_path_security_accepts_any_visible_absolute_directory(tmp_path):
    library = tmp_path / "outside-former-monitor-root" / "library"
    library.mkdir(parents=True)
    service = PathSecurityService()

    validation = service.validate_library_root(str(library))

    assert validation.real_path == library.resolve()


def test_path_security_rejects_relative_paths():
    service = PathSecurityService()
    with pytest.raises(PathSecurityError) as error:
        service.validate_library_root("books")
    assert error.value.code == "NOT_ABSOLUTE"


def test_work_merge_key_uses_only_normalized_work_title():
    expected = "斯泰尔斯庄园奇案午夜文库"
    assert _work_merge_key("斯泰尔斯庄园奇案 (午夜文库)") == expected


def test_import_epub_creates_library_records(db_session, test_settings, tmp_path):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    epub = tmp_path / "book.epub"
    write_epub_fixture(epub)

    result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=epub, origin="MANUAL", original_name="book.epub"),
    )

    assert result.import_status == "completed"
    assert result.type == "ebook"
    assert result.total_units == 0
    assert _count(db_session, "LibraryWork") == 1
    assert _count(db_session, "LibraryVersion") == 1
    assert _count(db_session, "LibraryMediaVersion") == 1
    assert _count(db_session, "LibraryReadingUnit") == 0
    assert (
        db_session.execute(text("SELECT chapterCount FROM LibraryVolume")).scalar()
        is None
    )
    assert _count(db_session, "ImportTask") == 1
    assert _count(db_session, "OrganizeJob") == 0
    assert (
        db_session.execute(text("SELECT organizeStatus FROM LibraryWork")).scalar()
        == "UNASSESSED"
    )
    assert _count(db_session, "MetadataLookupTask") == 0
    assert "epub" in {
        row[0] for row in db_session.execute(text("SELECT name FROM LibraryFacet"))
    }
    assert _count(db_session, "LibraryWorkFacet") >= 1

    events = (
        db_session.execute(
            text(
                "SELECT action, targetType, targetId, metadata FROM SystemEvent ORDER BY createdAt"
            )
        )
        .mappings()
        .all()
    )
    assert [event["action"] for event in events] == [
        "import.started",
        "identity.regex.completed",
        "import.completed",
    ]
    identity_event = events[1]
    identity_metadata = json.loads(identity_event["metadata"])
    assert identity_event["targetType"] == "importTask"
    assert identity_event["targetId"]
    assert identity_metadata["recognitionMethod"] == "regex"
    assert identity_metadata["title"] == "book"
    assert identity_metadata["author"] == "未知作者"


def test_import_retry_reuses_hidden_partial_volume_and_file(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    epub = tmp_path / "partial-retry.epub"
    write_epub_fixture(epub)
    stat = epub.stat()
    task_id = "partial-task"
    source_path = str(epub.resolve())
    normalized_source = normalized_import_source_key(source_path)
    resource_key = (
        f"epub:{hashlib.sha256(source_path.encode('utf-8')).hexdigest()[:24]}"
    )
    volume_id = stable_import_resource_id(
        task_id,
        "volume",
        f"{normalized_source}|{resource_key}",
    )
    work_id = stable_import_resource_id(
        task_id,
        "work",
        f"{normalized_source}|primary",
    )
    media_version_id = stable_import_resource_id(
        task_id,
        "media-version",
        f"{normalized_source}|{work_id}|EBOOK",
    )
    version_id = stable_import_resource_id(
        task_id,
        "version",
        f"{normalized_source}|{work_id}|{IMPLICIT_VERSION_SOURCE_KEY}",
    )
    file_id = stable_import_resource_id(
        task_id,
        "file",
        f"{normalized_source}|{source_path}",
    )
    db_session.add(
        ImportTask(
            id=task_id,
            origin="MANUAL",
            status="FAILED",
            source_path=source_path,
            retryable=True,
        )
    )
    db_session.add(
        LibraryWork(
            library_id="test-library",
            id=work_id,
            title="Sample",
            normalized_title="sample",
            author="Author",
            normalized_author="author",
            tags="[]",
            merge_key=_work_merge_key("Sample"),
        )
    )
    db_session.flush()
    db_session.add(
        LibraryVersion(
            id=version_id,
            work_id=work_id,
            source_key=IMPLICIT_VERSION_SOURCE_KEY,
        )
    )
    db_session.add(
        LibraryMediaVersion(
            id=media_version_id,
            work_id=work_id,
            media_kind="EBOOK",
        )
    )
    db_session.flush()
    db_session.add(
        LibraryVolume(
            id=volume_id,
            version_id=version_id,
            title="Sample",
            format="EPUB",
            resource_key=resource_key,
            import_status="PARSING",
        )
    )
    db_session.flush()
    db_session.add(
        LibraryFile(
            id=file_id,
            volume_id=volume_id,
            path=source_path,
            file_path_hash=hashlib.sha256(source_path.encode()).hexdigest(),
            mtime_ms=int(stat.st_mtime * 1000),
            kind="EPUB",
            mime_type="application/epub+zip",
            size_bytes=stat.st_size,
            sort_order=0,
        )
    )
    db_session.commit()

    result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=epub,
            origin="MANUAL",
            original_name=epub.name,
            import_task_id=task_id,
        ),
    )
    db_session.commit()

    stored_file = db_session.get(LibraryFile, file_id)
    completed_volume = db_session.get(LibraryVolume, result.volume_id)
    files_for_path = db_session.scalars(
        select(LibraryFile).where(LibraryFile.path == str(epub.resolve()))
    ).all()

    assert result.duplicate is False
    assert result.volume_id == volume_id
    assert stored_file is not None and stored_file.volume_id == result.volume_id
    assert completed_volume is not None
    assert completed_volume.import_status == "COMPLETED"
    assert len(files_for_path) == 1
    assert db_session.scalar(select(func.count()).select_from(LibraryVolume)) == 1
    assert db_session.scalar(select(func.count()).select_from(LibraryWork)) == 1
    assert db_session.scalar(select(func.count()).select_from(LibraryMediaVersion)) == 1
    assert db_session.scalar(select(func.count()).select_from(LibraryVersion)) == 1


def test_import_records_ai_identity_and_result(
    db_session, test_settings, tmp_path, monkeypatch
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    epub = tmp_path / "ai-book.epub"
    write_epub_metadata_fixture(epub, "", "")

    monkeypatch.setattr(
        SessionImportOrchestrationServices,
        "recognize_filename_identity",
        lambda *_args, **_kwargs: BookIdentityDTO(
            title="AI 识别书名",
            author="AI 识别作者",
            volume_index=None,
            source="ai",
            confidence=0.96,
            logical_path="ai-book.epub",
        ),
    )

    result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=epub, origin="MANUAL", original_name=epub.name),
    )

    assert result.title == "AI 识别书名"
    event = (
        db_session.execute(
            text(
                "SELECT message, metadata FROM SystemEvent WHERE action = 'identity.ai.completed'"
            )
        )
        .mappings()
        .one()
    )
    metadata = json.loads(event["metadata"])
    assert "AI 识别书名" in event["message"]
    assert metadata["title"] == "AI 识别书名"
    assert metadata["author"] == "AI 识别作者"
    assert metadata["confidence"] == 0.96


def test_import_records_path_identity_cache_hit(
    db_session, test_settings, tmp_path, monkeypatch
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    epub = tmp_path / "cached-book.epub"
    write_epub_metadata_fixture(epub, "", "")

    monkeypatch.setattr(
        SessionImportOrchestrationServices,
        "recognize_filename_identity",
        lambda *_args, **_kwargs: BookIdentityDTO(
            title="缓存书名",
            author="缓存作者",
            volume_index=None,
            source="ai",
            confidence=0.95,
            logical_path="cached-book.epub",
            cache_hit=True,
        ),
    )

    result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=epub, origin="MANUAL", original_name=epub.name),
    )

    assert result.title == "缓存书名"
    events = (
        db_session.execute(
            text("SELECT action, metadata FROM SystemEvent ORDER BY createdAt")
        )
        .mappings()
        .all()
    )
    assert [event["action"] for event in events] == [
        "import.started",
        "identity.cache.hit",
        "import.completed",
    ]
    assert json.loads(events[1]["metadata"])["cacheHit"] is True
    raw_metadata = db_session.execute(
        text("SELECT rawJson FROM LibraryMetadata WHERE source = 'identity_ai'")
    ).scalar()
    assert json.loads(raw_metadata)["cacheHit"] is True


def test_import_records_ai_failure_and_regex_fallback(
    db_session, test_settings, tmp_path, monkeypatch
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    epub = tmp_path / "[回退书名][回退作者].epub"
    write_epub_fixture(epub)

    monkeypatch.setattr(
        SessionImportOrchestrationServices,
        "recognize_filename_identity",
        lambda *_args, **_kwargs: BookIdentityDTO(
            title="回退书名",
            author="回退作者",
            volume_index=None,
            source="regex",
            confidence=0.96,
            logical_path=epub.name,
            fallback_reason="AI identity recognition failed: gateway timeout",
        ),
    )

    import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=epub, origin="MANUAL", original_name=epub.name),
    )

    events = (
        db_session.execute(
            text("SELECT action, level FROM SystemEvent ORDER BY createdAt")
        )
        .mappings()
        .all()
    )
    assert [event["action"] for event in events] == [
        "import.started",
        "identity.ai.failed",
        "identity.regex.completed",
        "import.completed",
    ]
    assert events[1]["level"] == "warning"


def test_structural_parse_failure_rolls_back_all_library_records(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    broken = tmp_path / "[损坏图书][测试作者].epub"
    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")

    with pytest.raises(Exception) as captured:
        import_managed_book(
            db_session,
            test_settings,
            _options(
                source_file_path=broken, origin="MANUAL", original_name=broken.name
            ),
        )

    assert _count(db_session, "LibraryWork") == 0
    assert _count(db_session, "LibraryMediaVersion") == 0
    assert _count(db_session, "LibraryVolume") == 0
    assert _count(db_session, "LibraryFile") == 0
    assert _count(db_session, "LibraryReadingUnit") == 0
    task_row = dict(
        db_session.execute(text("SELECT * FROM ImportTask")).mappings().one()
    )
    assert task_row["status"] == "PARSING"
    assert fail_claimed_import_task(
        db_session,
        import_task_dto_from_row(task_row),
        captured.value,
    )
    task = (
        db_session.execute(text("SELECT status, errorSummary FROM ImportTask"))
        .mappings()
        .one()
    )
    assert task["status"] == "FAILED"
    assert task["errorSummary"]
    failed_event = (
        db_session.execute(
            text(
                "SELECT level, metadata FROM SystemEvent WHERE action = 'import.failed'"
            )
        )
        .mappings()
        .one()
    )
    assert failed_event["level"] == "error"
    assert json.loads(failed_event["metadata"])["error"]


def test_deleted_source_fails_and_finishes_claimed_import_task(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    source = tmp_path / "deleted-before-import.epub"
    source.write_bytes(b"queued")
    task = ImportTaskDTO(
        id="deleted-source-task",
        origin="WATCH",
        status="PARSING",
        original_name=source.name,
        source_path=str(source),
        library_id="test-library",
    )
    db_session.execute(
        text(
            "INSERT INTO ImportTask "
            "(id, origin, status, originalName, sourcePath, progress, duplicate, duration, retryable, attempts, "
            "leaseOwner, leaseExpiresAt, message, createdAt, updatedAt) "
            "VALUES (:id, :origin, :status, :original_name, :source_path, 0, 0, 0, 0, 1, "
            "'worker-old', 9999999999999, '正在准备导入', 1, 1)"
        ),
        {
            "id": task.id,
            "origin": task.origin,
            "status": task.status,
            "original_name": task.original_name,
            "source_path": task.source_path,
        },
    )
    db_session.commit()
    source.unlink()

    with pytest.raises(FileNotFoundError, match="导入源已不存在") as captured:
        process_import_task(db_session, test_settings, task)
    assert fail_claimed_import_task(db_session, task, captured.value)

    stored = (
        db_session.execute(
            text(
                "SELECT status, progress, errorCode, retryable, message, errorSummary, "
                "leaseOwner, leaseExpiresAt, finishedAt FROM ImportTask WHERE id = :id"
            ),
            {"id": task.id},
        )
        .mappings()
        .one()
    )
    assert stored["status"] == "FAILED"
    assert stored["progress"] == 100
    assert stored["errorCode"] == "SOURCE_NOT_FOUND"
    assert bool(stored["retryable"]) is False
    assert stored["message"] == "导入源文件或目录不存在，任务已结束"
    assert "deleted-before-import.epub" in stored["errorSummary"]
    assert stored["leaseOwner"] is None
    assert stored["leaseExpiresAt"] is None
    assert stored["finishedAt"] is not None


def test_worker_fallback_forces_unhandled_claimed_task_to_terminal_failure(
    db_session, tmp_path
):
    create_worker_tables(db_session)
    missing_source = tmp_path / "worker-crashed.epub"
    task = ImportTaskDTO(
        id="worker-fallback-task",
        origin="WATCH",
        status="PARSING",
        source_path=str(missing_source),
        library_id="test-library",
    )
    db_session.execute(
        text(
            "INSERT INTO ImportTask "
            "(id, origin, status, originalName, sourcePath, progress, duplicate, duration, retryable, attempts, "
            "leaseOwner, leaseExpiresAt, message, createdAt, updatedAt) "
            "VALUES (:id, 'WATCH', 'PARSING', 'worker-crashed.epub', :source_path, 5, 0, 0, 0, 1, "
            "'worker-old', 9999999999999, '正在准备导入', 1, 1)"
        ),
        {"id": task.id, "source_path": task.source_path},
    )
    db_session.commit()

    assert (
        fail_claimed_import_task(
            db_session, task, RuntimeError("unexpected worker failure")
        )
        is True
    )

    stored = (
        db_session.execute(
            text(
                "SELECT status, progress, errorCode, retryable, leaseOwner, leaseExpiresAt, finishedAt "
                "FROM ImportTask WHERE id = :id"
            ),
            {"id": task.id},
        )
        .mappings()
        .one()
    )
    assert stored["status"] == "FAILED"
    assert stored["progress"] == 100
    assert stored["errorCode"] == "SOURCE_NOT_FOUND"
    assert bool(stored["retryable"]) is False
    assert stored["leaseOwner"] is None
    assert stored["leaseExpiresAt"] is None
    assert stored["finishedAt"] is not None


def test_watch_epub_prefers_embedded_opf_when_filename_conflicts(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)
    source_name = "斯泰尔斯庄园奇案_阿加莎·克里 - (英)阿加莎·克里斯蒂.epub"
    epub = tmp_path / source_name
    write_epub_metadata_fixture(
        epub,
        "岛田庄司精选作品合集共14册（日本推理小说之神，新本格派导师岛田庄司）",
        "岛田庄司",
    )

    result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=epub,
            origin="WATCH",
            original_name=source_name,
            library_id="folder-1",
        ),
    )

    assert result.duplicate is False
    work = (
        db_session.execute(text("SELECT title, author FROM LibraryWork"))
        .mappings()
        .first()
    )
    assert work["title"].startswith("岛田庄司精选作品合集共14册")
    assert work["author"] == "岛田庄司"
    raw = json.loads(
        db_session.execute(
            text("SELECT rawJson FROM LibraryMetadata WHERE source = 'epub_opf'")
        ).scalar()
    )
    assert raw["dc:title"][0].startswith("岛田庄司精选作品合集共14册")


def test_epub_import_applies_embedded_description_to_work(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)
    epub = tmp_path / "黑暗物质三部曲 - 菲利普·普尔曼.epub"
    write_epub_metadata_fixture(
        epub,
        "黑暗物质三部曲",
        "菲利普·普尔曼",
        description="写回到 EPUB OPF 的作品简介",
        subjects=("奇幻", "冒险"),
    )

    result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=epub,
            origin="WATCH",
            original_name=epub.name,
            library_id="folder-1",
        ),
    )

    work = db_session.get(LibraryWork, result.work_id)
    volume = db_session.get(LibraryVolume, result.volume_id)

    assert work is not None and volume is not None
    assert work.description == "写回到 EPUB OPF 的作品简介"
    assert volume.description == "写回到 EPUB OPF 的作品简介"
    assert json.loads(work.tags) == ["epub", "奇幻", "冒险"]

    work.description = None
    work.tags = json.dumps(["epub"], ensure_ascii=False)
    db_session.commit()
    second_epub = tmp_path / "黑暗物质三部曲 - 菲利普·普尔曼（重导入）.epub"
    write_epub_metadata_fixture(
        second_epub,
        "黑暗物质三部曲",
        "菲利普·普尔曼",
        description="写回到 EPUB OPF 的作品简介",
        subjects=("奇幻", "冒险"),
    )

    repeated = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=second_epub,
            origin="WATCH",
            original_name=second_epub.name,
            library_id="folder-1",
        ),
    )
    db_session.refresh(work)

    assert repeated.work_id == result.work_id
    assert work.description == "写回到 EPUB OPF 的作品简介"
    assert json.loads(work.tags) == ["epub", "奇幻", "冒险"]


def test_watch_epub_uses_opf_when_sanitized_filename_identity_is_incomplete(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)
    source_name = "白夜行_(东野圭吾)_(z-library.sk_1lib.sk_z-lib.sk).epub"
    epub = tmp_path / source_name
    write_epub_metadata_fixture(epub, "白夜行", "(日)东野圭吾")

    result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=epub,
            origin="WATCH",
            original_name=source_name,
            library_id="folder-1",
        ),
    )

    assert result.duplicate is False
    work = (
        db_session.execute(text("SELECT title, author FROM LibraryWork"))
        .mappings()
        .one()
    )
    assert dict(work) == {"title": "白夜行", "author": "(日)东野圭吾"}
    identity_raw = json.loads(
        db_session.execute(
            text(
                "SELECT rawJson FROM LibraryMetadata WHERE source = 'identity_epub_opf'"
            )
        ).scalar_one()
    )
    assert identity_raw["selectionReason"] == "resolved_local_metadata"
    assert [item["source"] for item in identity_raw["evidence"]] == ["regex"]


def test_sidecar_opf_overrides_embedded_metadata_and_is_echoed_on_import_task(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    epub = tmp_path / "sidecar-book.epub"
    write_epub_fixture(epub)
    epub.with_suffix(".opf").write_text(
        """<package xmlns:dc="http://purl.org/dc/elements/1.1/"
        xmlns:opf="http://www.idpf.org/2007/opf"><metadata>
        <dc:title>旁车标题</dc:title><dc:creator>作者甲</dc:creator><dc:creator>作者乙</dc:creator>
        <dc:description>旁车简介</dc:description><dc:subject>科幻</dc:subject>
        <dc:language>zh-CN</dc:language><dc:publisher>旁车出版社</dc:publisher>
        <dc:date>2024-03-02</dc:date><dc:identifier opf:scheme="ISBN">978-7-0000-0000-1</dc:identifier>
        <meta name="calibre:series" content="旁车系列"/><meta name="calibre:series_index" content="2"/>
        </metadata><manifest/><spine/></package>"""
    )

    result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=epub,
            origin="MANUAL",
            original_name=epub.name,
            requested_title="用户标题",
        ),
    )

    work = db_session.get(LibraryWork, result.work_id)
    volume = db_session.get(LibraryVolume, result.volume_id)
    task = db_session.scalar(
        select(ImportTask).where(ImportTask.volume_id == result.volume_id)
    )
    sidecar_record = db_session.scalar(
        select(LibraryMetadata).where(
            LibraryMetadata.volume_id == result.volume_id,
            LibraryMetadata.source == "sidecar_opf",
        )
    )
    assert work is not None and volume is not None and task is not None
    assert work.title == "用户标题"
    assert work.author == "作者甲 / 作者乙"
    assert work.description == "旁车简介"
    assert work.series_name == "旁车系列"
    assert work.series_index == 2
    assert volume.publisher == "旁车出版社"
    assert volume.language == "zh-CN"
    assert volume.isbn == "978-7-0000-0000-1"
    assert task.recognized_metadata is not None
    assert task.recognized_metadata["title"] == "用户标题"
    assert task.recognized_metadata["volumeTitle"] == "旁车标题"
    assert task.recognized_metadata["author"] == "作者甲 / 作者乙"
    assert task.recognized_metadata["source"] == "REQUESTED"
    assert sidecar_record is not None
    evidence = json.loads(sidecar_record.raw_json)
    assert evidence["sourceKind"] == "FILE"
    assert evidence["fieldSources"]["title"] == "FILE"


def test_path_priority_resolves_once_before_work_and_volume_decisions(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)
    db_session.add(
        OrganizePolicy(
            id="default",
            local_metadata_priority_json='["PATH","EMBEDDED","SIDECAR_OPF"]',
        )
    )
    db_session.commit()

    epub = tmp_path / "路径优先作品-Vol.09.epub"
    write_epub_metadata_fixture(
        epub,
        "内嵌错误作品 Vol.8",
        "内嵌补充作者",
        description="内嵌来源补充的简介",
    )
    epub.with_suffix(".opf").write_text(
        """<package xmlns:dc="http://purl.org/dc/elements/1.1/">
        <metadata><dc:title>OPF错误作品 Vol.2</dc:title>
        <dc:creator>OPF错误作者</dc:creator>
        <dc:publisher>OPF补充出版社</dc:publisher>
        <dc:language>zh-CN</dc:language></metadata><manifest/><spine/></package>""",
        encoding="utf-8",
    )

    result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=epub,
            origin="WATCH",
            original_name=epub.name,
            library_id="folder-1",
        ),
    )

    work = db_session.get(LibraryWork, result.work_id)
    volume = db_session.get(LibraryVolume, result.volume_id)
    task = db_session.scalar(
        select(ImportTask).where(ImportTask.volume_id == result.volume_id)
    )
    assert work is not None and volume is not None and task is not None
    assert (work.title, work.author, work.description) == (
        "路径优先作品",
        "内嵌补充作者",
        "内嵌来源补充的简介",
    )
    assert (volume.title, volume.volume_index) == ("路径优先作品-Vol.09", 9)
    assert (volume.publisher, volume.language) == ("OPF补充出版社", "zh-CN")
    assert task.recognized_metadata is not None
    assert task.recognized_metadata["source"] == "PATH"
    assert task.recognized_metadata["volumeTitle"] == "路径优先作品-Vol.09"
    field_sources = task.recognized_metadata["fieldSources"]
    assert field_sources["title"] == "PATH"
    assert field_sources["author"] == "EMBEDDED"
    assert field_sources["description"] == "EMBEDDED"
    assert field_sources["volumeIndex"] == "PATH"
    assert field_sources["language"] == "SIDECAR_OPF"
    assert field_sources["publisher"] == "SIDECAR_OPF"


def test_watched_import_creates_work_in_library(
    db_session, test_settings, tmp_path, monkeypatch
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    db_session.execute(
        text(
            """INSERT INTO Library (
                id, name, rootPath, organizationMode, enabled, ignoreHidden, minFileSizeBytes, createdAt, updatedAt
            ) VALUES (
                'folder-1', '测试目录', :root_path, 'FLAT', 1, 1, 1, 'now', 'now'
            )"""
        ),
        {"root_path": str(tmp_path)},
    )
    db_session.commit()
    epub = tmp_path / "[星海列车][林川].epub"
    write_epub_metadata_fixture(epub, "星海列车", "林川")
    folder = LibraryConfig(
        id="folder-1",
        root_path=str(tmp_path),
        min_file_size_bytes=1,
    )
    monkeypatch.setenv("MONITOR_FILE_STABLE_DELAY_MS", "0")

    import_watched_file(db_session, test_settings, epub, folder)
    pending = import_task_dto_from_row(
        dict(
            db_session.execute(
                text("SELECT * FROM ImportTask WHERE status = 'PENDING'")
            )
            .mappings()
            .one()
        )
    )
    process_import_task(db_session, test_settings, pending)
    works = (
        db_session.execute(text("SELECT id, libraryId FROM LibraryWork"))
        .mappings()
        .all()
    )
    assert len(works) == 1
    assert works[0]["libraryId"] == "folder-1"
    assert epub.exists()


def test_parse_series_volume_info_from_real_watch_layout():
    path = Path(
        "/monitor/[辣妹因为惩罚游戏才向我这个边缘人告白，但显然是真心爱上我了][結石][Vol.01-Vol.10]/辣妹因为惩罚游戏才向我这个边缘人告白，但显然是真心爱上我了 10.epub"
    )

    parsed = parse_series_volume_info(path, path.name, "WATCH")

    assert parsed is not None
    assert (
        parsed.series_name
        == "辣妹因为惩罚游戏才向我这个边缘人告白，但显然是真心爱上我了"
    )
    assert parsed.author == "結石"
    assert parsed.series_index == 10
    assert parsed.title == "第 10 卷"


def test_parse_series_volume_info_from_bracketed_folder_and_volume_filename():
    path = Path(
        "/books/comic/[DRAWING 最強漫畫家利用繪畫技能在異世界開無雙 ！][金光铉]/Vol.09.epub"
    )

    parsed = parse_series_volume_info(path, path.name, "WATCH")

    assert parsed is not None
    assert parsed.series_name == "DRAWING 最強漫畫家利用繪畫技能在異世界開無雙 ！"
    assert parsed.author == "金光铉"
    assert parsed.series_index == 9
    assert parsed.title == "第 9 卷"


@pytest.mark.parametrize(
    ("path", "expected_title", "expected_author", "expected_volume"),
    [
        (
            Path(
                "/monitor/comic/[柊裕一][鹰峰同学请穿上衣服][東立][Zero有水印][8未]/"
                "鹰峰同学请穿上衣服 [柊裕一][东立][扫图][繁中] Vol.05.zip"
            ),
            "鹰峰同学请穿上衣服",
            "柊裕一",
            5,
        ),
        (
            Path(
                "/monitor/comic/[山本崇一朗][擅长捉弄的高木同学（境外版）][bili][Vol.01-Vol.20][完结]/"
                "擅长捉弄的高木同学（境外版） Vol.08.zip"
            ),
            "擅长捉弄的高木同学（境外版）",
            "山本崇一朗",
            8,
        ),
        (
            Path(
                "/monitor/comic/[Chainsaw Man][电锯人][藤本タツキ][Vol.01-Vol.11]/VOL11.zip"
            ),
            "电锯人",
            "藤本タツキ",
            11,
        ),
    ],
)
def test_parse_series_volume_info_supports_author_first_tagged_directories(
    path, expected_title, expected_author, expected_volume
):
    parsed = parse_series_volume_info(path, path.name, "WATCH")

    assert parsed is not None
    assert parsed.series_name == expected_title
    assert parsed.author == expected_author
    assert parsed.series_index == expected_volume
    assert parsed.title == f"第 {expected_volume} 卷"


def test_watch_epub_import_keeps_duplicate_volume_numbers_from_distinct_files(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)
    series_dir = (
        tmp_path
        / "[辣妹因为惩罚游戏才向我这个边缘人告白，但显然是真心爱上我了][結石][Vol.01-Vol.10]"
    )
    series_dir.mkdir()
    first = (
        series_dir
        / "辣妹因为惩罚游戏才向我这个边缘人告白，但显然是真心爱上我了 01.epub"
    )
    tenth = (
        series_dir
        / "辣妹因为惩罚游戏才向我这个边缘人告白，但显然是真心爱上我了 10.epub"
    )
    duplicate_tenth = (
        series_dir
        / "辣妹因为惩罚游戏才向我这个边缘人告白，但显然是真心爱上我了 10 copy.epub"
    )
    write_epub_metadata_fixture(first, "第 1 卷", "封面作者")
    write_epub_metadata_fixture(tenth, "第 10 卷", "封面作者")
    write_epub_metadata_fixture(duplicate_tenth, "第 10 卷", "封面作者")

    first_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=first,
            origin="WATCH",
            original_name=first.name,
            library_id="folder-1",
        ),
    )
    tenth_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=tenth,
            origin="WATCH",
            original_name=tenth.name,
            library_id="folder-1",
        ),
    )
    duplicate_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=duplicate_tenth,
            origin="WATCH",
            original_name=tenth.name,
            library_id="folder-1",
        ),
    )

    assert first_result.work_id == tenth_result.work_id == duplicate_result.work_id
    assert first_result.media_version_id == tenth_result.media_version_id
    assert duplicate_result.media_version_id == first_result.media_version_id
    assert first_result.volume_id != tenth_result.volume_id
    assert duplicate_result.volume_id != tenth_result.volume_id
    assert duplicate_result.duplicate is False
    assert _count(db_session, "LibraryWork") == 1
    assert _count(db_session, "LibraryMediaVersion") == 1
    assert _count(db_session, "LibraryVolume") == 3
    assert _count(db_session, "LibraryFile") == 3
    work = (
        db_session.execute(text("SELECT title, author FROM LibraryWork"))
        .mappings()
        .first()
    )
    assert work["title"] == "辣妹因为惩罚游戏才向我这个边缘人告白，但显然是真心爱上我了"
    assert work["author"] == "封面作者"
    first_volume = (
        db_session.execute(
            text("SELECT chapterCount, sizeBytes FROM LibraryVolume WHERE id = :id"),
            {"id": first_result.volume_id},
        )
        .mappings()
        .first()
    )
    assert first_volume["chapterCount"] is None
    assert first_volume["sizeBytes"] > 0
    volumes = (
        db_session.execute(
            text(
                "SELECT title, volumeIndex, sortOrder, chapterCount FROM LibraryVolume volume JOIN LibraryVersion version ON version.id = volume.versionId WHERE version.workId = :id ORDER BY volume.sortOrder"
            ),
            {"id": first_result.work_id},
        )
        .mappings()
        .all()
    )
    assert [dict(volume) for volume in volumes] == [
        {
            "title": "第 1 卷",
            "volumeIndex": 1,
            "sortOrder": 1000,
            "chapterCount": None,
        },
        {
            "title": "第 10 卷",
            "volumeIndex": 10,
            "sortOrder": 10000,
            "chapterCount": None,
        },
        {
            "title": "第 10 卷",
            "volumeIndex": 10,
            "sortOrder": 10001,
            "chapterCount": None,
        },
    ]


def test_pdf_and_comic_imports_keep_duplicate_volume_numbers(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)

    pdf_dir = tmp_path / "同一作品"
    pdf_dir.mkdir()
    first_pdf = pdf_dir / "同一作品 Vol.01 A.pdf"
    second_pdf = pdf_dir / "同一作品 Vol.01 B.pdf"
    write_pdf_metadata_fixture(first_pdf, title="同一作品", author="作者甲")
    write_pdf_metadata_fixture(second_pdf, title="同一作品", author="作者乙")
    first_pdf_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=first_pdf,
            origin="WATCH",
            original_name=first_pdf.name,
            library_id="folder-1",
        ),
    )
    second_pdf_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=second_pdf,
            origin="WATCH",
            original_name=second_pdf.name,
            library_id="folder-1",
        ),
    )

    comic_dir = tmp_path / "星舰漫画"
    comic_dir.mkdir()
    first_comic = comic_dir / "星舰漫画 Vol.01 A.cbz"
    second_comic = comic_dir / "星舰漫画 Vol.01 B.cbz"
    write_comic_fixture(first_comic, volume=1, cover_bytes=b"first-cover")
    write_comic_fixture(second_comic, volume=1, cover_bytes=b"second-cover")
    first_comic_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=first_comic,
            origin="WATCH",
            original_name=first_comic.name,
            library_id="folder-1",
        ),
    )
    second_comic_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=second_comic,
            origin="WATCH",
            original_name=second_comic.name,
            library_id="folder-1",
        ),
    )

    for first_result, second_result in (
        (first_pdf_result, second_pdf_result),
        (first_comic_result, second_comic_result),
    ):
        assert first_result.work_id == second_result.work_id
        assert first_result.media_version_id == second_result.media_version_id
        assert first_result.volume_id != second_result.volume_id
        volumes = list(
            db_session.scalars(
                select(LibraryVolume)
                .join(LibraryVersion, LibraryVersion.id == LibraryVolume.version_id)
                .where(LibraryVersion.work_id == first_result.work_id)
                .order_by(LibraryVolume.sort_order)
            )
        )
        assert [volume.volume_index for volume in volumes] == [1, 1]
        assert [volume.sort_order for volume in volumes] == [1000, 1001]


def test_explicit_series_directory_groups_all_volumes_by_folder(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    series_title = "失格纹的最强贤者～世界最强的贤者为了变得更强而转生了~"
    series_author = "进行诸岛×風花風花×肝匠&馮昊"
    series_dir = (
        tmp_path / f"[{series_title}][{series_author}][Vol.01-Vol.33][未完][bili]"
    )
    series_dir.mkdir()
    volume_26 = series_dir / f"{series_title} Vol.26.zip"
    volume_30 = series_dir / f"{series_title} Vol.30.zip"
    write_comic_fixture(volume_26, volume=26)
    write_comic_fixture(volume_30, volume=30)
    first = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=volume_26, origin="WATCH", original_name=volume_26.name
        ),
    )
    second = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=volume_30, origin="WATCH", original_name=volume_30.name
        ),
    )

    assert first.work_id == second.work_id
    assert first.media_version_id == second.media_version_id
    first_volume = db_session.get(LibraryVolume, first.volume_id)
    second_volume = db_session.get(LibraryVolume, second.volume_id)
    assert first_volume is not None
    assert second_volume is not None
    assert first_volume.cover_path != second_volume.cover_path
    assert Path(str(first_volume.cover_path)).parent.name == first.volume_id
    assert Path(str(second_volume.cover_path)).parent.name == second.volume_id
    assert db_session.execute(
        text("SELECT volumeIndex FROM LibraryVolume ORDER BY volumeIndex")
    ).scalars().all() == [26, 30]
    assert (
        db_session.execute(text("SELECT COUNT(*) FROM MetadataLookupTask")).scalar()
        == 0
    )


def test_numeric_comic_fallback_groups_parenthesized_volumes(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)
    series_dir = (
        tmp_path / "[FX戦士久留美][ですにゃん×荒酸だいすき][角川][Vol.01-Vol.05][未完]"
    )
    series_dir.mkdir()
    first = series_dir / "FX戦士久留美 (1).zip"
    second = series_dir / "FX戦士久留美 (2).zip"
    write_comic_fixture(first, volume=1)
    write_comic_fixture(second, volume=2)

    first_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=first,
            origin="WATCH",
            original_name=first.name,
            library_id="folder-1",
        ),
    )
    second_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=second,
            origin="WATCH",
            original_name=second.name,
            library_id="folder-1",
        ),
    )

    assert first_result.work_id == second_result.work_id
    assert first_result.media_version_id == second_result.media_version_id
    assert db_session.execute(
        text("SELECT volumeIndex FROM LibraryVolume ORDER BY volumeIndex")
    ).scalars().all() == [1, 2]


def test_author_first_tagged_directory_imports_later_file_as_new_volume(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    series_title = "鹰峰同学请穿上衣服"
    series_author = "柊裕一"
    series_dir = tmp_path / f"[{series_author}][{series_title}][東立][Zero有水印][8未]"
    series_dir.mkdir()
    volume_8 = (
        series_dir / f"{series_title} [{series_author}][东立][扫图][繁中] Vol.08.zip"
    )
    volume_5 = (
        series_dir / f"{series_title} [{series_author}][东立][扫图][繁中] Vol.05.zip"
    )
    write_comic_fixture(volume_8, volume=8)
    write_comic_fixture(volume_5, volume=5)
    first = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=volume_8, origin="WATCH", original_name=volume_8.name
        ),
    )
    second = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=volume_5, origin="WATCH", original_name=volume_5.name
        ),
    )

    assert first.work_id == second.work_id
    assert first.media_version_id == second.media_version_id
    assert db_session.execute(
        text("SELECT volumeIndex FROM LibraryVolume ORDER BY volumeIndex")
    ).scalars().all() == [5, 8]


def test_filename_alias_groups_later_volume_by_same_directory(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    series_title = "超自然武装当哒当"
    series_author = "龍幸伸"
    series_dir = tmp_path / f"[{series_author}][{series_title}][未完][东立][BW电子版]"
    series_dir.mkdir()
    volume_14 = series_dir / "膽大黨 Vol.14.zip"
    volume_16 = series_dir / "膽大黨 Vol.16.zip"
    write_comic_fixture(volume_14, volume=14)
    write_comic_fixture(volume_16, volume=16)
    first = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=volume_14, origin="WATCH", original_name=volume_14.name
        ),
    )
    second = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=volume_16, origin="WATCH", original_name=volume_16.name
        ),
    )

    assert first.work_id == second.work_id
    assert first.media_version_id == second.media_version_id
    assert db_session.execute(
        text("SELECT volumeIndex FROM LibraryVolume ORDER BY volumeIndex")
    ).scalars().all() == [14, 16]


def test_explicit_volumes_in_ambiguous_collection_still_group_by_folder(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    collection_dir = tmp_path / "[合集][扫描][未完]"
    collection_dir.mkdir()
    first_file = collection_dir / "作品甲 Vol.01.zip"
    second_file = collection_dir / "作品乙 Vol.01.zip"
    write_comic_fixture(first_file, volume=1)
    write_comic_fixture(second_file, volume=1)
    first = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=first_file, origin="WATCH", original_name=first_file.name
        ),
    )
    second = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=second_file, origin="WATCH", original_name=second_file.name
        ),
    )

    assert first.work_id == second.work_id
    assert _count(db_session, "LibraryWork") == 1


def test_identical_embedded_metadata_groups_files_despite_different_paths(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    author_dir = tmp_path / "作者xxx"
    author_dir.mkdir()
    first_file = author_dir / "a.epub"
    second_file = author_dir / "b.epub"
    write_epub_fixture(first_file)
    write_epub_fixture(second_file)
    first = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=first_file, origin="WATCH", original_name=first_file.name
        ),
    )
    second = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=second_file, origin="WATCH", original_name=second_file.name
        ),
    )

    assert first.work_id == second.work_id
    assert first.media_version_id == second.media_version_id
    first_volume = db_session.get(LibraryVolume, first.volume_id)
    second_volume = db_session.get(LibraryVolume, second.volume_id)
    assert first_volume is not None
    assert second_volume is not None
    assert first_volume.cover_path != second_volume.cover_path
    assert Path(str(first_volume.cover_path)).parent.name == first.volume_id
    assert Path(str(second_volume.cover_path)).parent.name == second.volume_id
    assert db_session.execute(
        text("SELECT title FROM LibraryWork ORDER BY title")
    ).scalars().all() == ["目录测试"]
    assert (
        db_session.execute(text("SELECT COUNT(*) FROM MetadataLookupTask")).scalar()
        == 0
    )


def test_watch_epub_import_uses_bracketed_folder_for_volume_filename(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)
    series_dir = tmp_path / "[DRAWING 最強漫畫家利用繪畫技能在異世界開無雙 ！][金光铉]"
    series_dir.mkdir()
    epub = series_dir / "Vol.09.epub"
    write_epub_metadata_fixture(epub, "Vol.09", "封面作者")

    result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=epub,
            origin="WATCH",
            original_name=epub.name,
            library_id="folder-1",
        ),
    )

    assert result.duplicate is False
    assert result.volume_id is not None
    work = (
        db_session.execute(text("SELECT title, author FROM LibraryWork"))
        .mappings()
        .first()
    )
    assert work["title"] == "DRAWING 最強漫畫家利用繪畫技能在異世界開無雙 ！"
    assert work["author"] == "封面作者"
    volume = (
        db_session.execute(
            text("SELECT title, volumeIndex, sortOrder FROM LibraryVolume")
        )
        .mappings()
        .first()
    )
    assert dict(volume) == {"title": "Vol.09", "volumeIndex": 9, "sortOrder": 9000}
    raw = json.loads(
        db_session.execute(text("SELECT rawJson FROM LibraryMetadata")).scalar()
    )
    assert raw["sourceSeriesTitle"] == "DRAWING 最強漫畫家利用繪畫技能在異世界開無雙 ！"
    assert raw["sourceSeriesAuthor"] == "封面作者"
    assert raw["sourceVolumeIndex"] == 9
    assert raw["sourceVolumeTitle"] == "Vol.09"


def test_import_epub_groups_same_work_title_across_directories(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    first_dir = tmp_path / "version-a"
    second_dir = tmp_path / "version-b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "[斯泰尔斯庄园奇案][阿加莎·克里斯蒂].epub"
    second = second_dir / "[斯泰尔斯庄园奇案][阿加莎·克里斯蒂].epub"
    write_epub_metadata_fixture(
        first, "斯泰尔斯庄园奇案", "阿加莎·克里斯蒂", ["B00T238N28"]
    )
    write_epub_metadata_fixture(
        second, "斯泰尔斯庄园奇案", "阿加莎·克里斯蒂", ["B00DIFFERENT"]
    )

    first_result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=first, origin="MANUAL", original_name=first.name),
    )
    second_result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=second, origin="MANUAL", original_name=second.name),
    )

    assert first_result.duplicate is False
    assert second_result.duplicate is False
    assert first_result.work_id == second_result.work_id
    assert _count(db_session, "LibraryWork") == 1
    assert _count(db_session, "LibraryMediaVersion") == 1
    assert _count(db_session, "LibraryFile") == 2


def test_embedded_metadata_prevents_directory_from_forcing_cross_format_grouping(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    work_dir = tmp_path / "[跨格式作品][作者甲]"
    work_dir.mkdir()
    epub = work_dir / "跨格式作品.epub"
    pdf = work_dir / "跨格式作品.pdf"
    comic = work_dir / "跨格式作品.cbz"
    write_epub_metadata_fixture(epub, "错误 EPUB 标题", "错误作者")
    write_pdf_fixture(pdf)
    write_comic_fixture(comic)

    epub_result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=epub, origin="MANUAL", original_name=epub.name),
    )
    pdf_result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=pdf, origin="MANUAL", original_name=pdf.name),
    )
    comic_result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=comic, origin="MANUAL", original_name=comic.name),
    )

    assert len({epub_result.work_id, pdf_result.work_id, comic_result.work_id}) == 3
    assert (
        len(
            {
                epub_result.media_version_id,
                pdf_result.media_version_id,
                comic_result.media_version_id,
            }
        )
        == 3
    )
    assert (
        len({epub_result.volume_id, pdf_result.volume_id, comic_result.volume_id}) == 3
    )
    assert _count(db_session, "LibraryWork") == 3
    assert set(
        db_session.execute(text("SELECT format FROM LibraryVolume")).scalars()
    ) == {"EPUB", "PDF", "CBZ"}
    assert set(
        db_session.execute(text("SELECT mediaKind FROM LibraryMediaVersion")).scalars()
    ) == {"EBOOK", "COMIC"}


def test_pdf_series_volume_preserves_explicit_chinese_volume_index(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    series_dir = tmp_path / "[Series][Author]"
    series_dir.mkdir()
    pdf = series_dir / "Series \u7b2c01\u5377.pdf"
    write_pdf_fixture(pdf)

    result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=pdf, origin="WATCH", original_name=pdf.name),
    )

    volume = db_session.get(LibraryVolume, result.volume_id)
    assert volume is not None
    assert volume.title == "Series \u7b2c01\u5377"
    assert volume.volume_index == 1
    assert volume.sort_order == 1000


def test_watched_pdf_volumes_do_not_merge_when_embedded_authors_differ(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)
    series_dir = tmp_path / "same-series"
    series_dir.mkdir()
    first = series_dir / "星舰漫画 Vol.01.pdf"
    second = series_dir / "星舰漫画 Vol.02.pdf"
    write_pdf_metadata_fixture(first, title="internal-01", author="")
    write_pdf_metadata_fixture(second, title="internal-02", author="作者乙")

    first_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=first,
            origin="WATCH",
            original_name=first.name,
            library_id="folder-1",
        ),
    )
    second_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=second,
            origin="WATCH",
            original_name=second.name,
            library_id="folder-1",
        ),
    )

    assert first_result.work_id != second_result.work_id
    assert _count(db_session, "LibraryWork") == 2
    assert sorted(db_session.scalars(select(LibraryVolume.volume_index)).all()) == [
        1,
        2,
    ]


def test_watched_pdf_volumes_recognize_short_numbers_inside_titles(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)
    series_dir = tmp_path / "PDF格式-龙与猫之国.6卷"
    series_dir.mkdir()
    first = series_dir / "龙与猫之国.Vlo.1.册-穿越时空的木乃伊之眼.pdf"
    second = series_dir / "龙与猫之国.Vlo.2.册-鬼影迷城的百慕大航班.pdf"
    write_pdf_metadata_fixture(first)
    write_pdf_metadata_fixture(second)

    first_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=first,
            origin="WATCH",
            original_name=first.name,
            library_id="folder-1",
        ),
    )
    second_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=second,
            origin="WATCH",
            original_name=second.name,
            library_id="folder-1",
        ),
    )

    assert first_result.work_id == second_result.work_id
    assert first_result.media_version_id == second_result.media_version_id
    assert sorted(db_session.scalars(select(LibraryVolume.volume_index)).all()) == [
        1,
        2,
    ]
    first_volume = db_session.get(LibraryVolume, first_result.volume_id)
    second_volume = db_session.get(LibraryVolume, second_result.volume_id)
    assert first_volume is not None
    assert second_volume is not None
    assert first_volume.cover_path != second_volume.cover_path
    assert Path(str(first_volume.cover_path)).parent.name == first_result.volume_id
    assert Path(str(second_volume.cover_path)).parent.name == second_result.volume_id
    assert Path(str(first_volume.cover_path)).is_file()
    assert Path(str(second_volume.cover_path)).is_file()


def test_watched_cjk_marker_before_number_merges_by_directory_and_title(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)
    series_dir = tmp_path / "东京复仇者全彩31卷 PDF格式"
    series_dir.mkdir()
    first = series_dir / "[東京卍復仇者(全彩版)]卷01.pdf"
    second = series_dir / "[東京卍復仇者(全彩版)]卷02.pdf"
    write_pdf_metadata_fixture(first)
    write_pdf_metadata_fixture(second)

    first_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=first,
            origin="WATCH",
            original_name=first.name,
            library_id="folder-1",
        ),
    )
    second_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=second,
            origin="WATCH",
            original_name=second.name,
            library_id="folder-1",
        ),
    )

    assert first_result.work_id == second_result.work_id
    assert _count(db_session, "LibraryWork") == 1
    assert sorted(db_session.scalars(select(LibraryVolume.volume_index)).all()) == [
        1,
        2,
    ]


def test_watched_pdf_volumes_in_different_directories_do_not_merge(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)
    first_dir = tmp_path / "edition-a"
    second_dir = tmp_path / "edition-b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "同名漫画 Vol.01.pdf"
    second = second_dir / "同名漫画 Vol.02.pdf"
    write_pdf_metadata_fixture(first, title="internal-01", author="同一作者")
    write_pdf_metadata_fixture(second, title="internal-02", author="同一作者")

    first_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=first,
            origin="WATCH",
            original_name=first.name,
            library_id="folder-1",
        ),
    )
    second_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=second,
            origin="WATCH",
            original_name=second.name,
            library_id="folder-1",
        ),
    )

    assert first_result.work_id != second_result.work_id
    assert _count(db_session, "LibraryWork") == 2


def test_watched_pdf_files_with_same_title_ignore_different_authors(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)
    first = tmp_path / "同名作品一.pdf"
    second = tmp_path / "同名作品二.pdf"
    write_pdf_metadata_fixture(first, title="同名作品", author="作者甲")
    write_pdf_metadata_fixture(second, title="同名作品", author="作者乙")

    first_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=first,
            origin="WATCH",
            original_name=first.name,
            library_id="folder-1",
        ),
    )
    second_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=second,
            origin="WATCH",
            original_name=second.name,
            library_id="folder-1",
        ),
    )

    assert first_result.work_id == second_result.work_id
    assert _count(db_session, "LibraryWork") == 1
    assert _count(db_session, "LibraryFile") == 2


def test_import_reuses_legacy_work_by_title_and_replaces_old_merge_key(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    db_session.add(
        LibraryWork(
            library_id="test-library",
            id="legacy-work",
            title="同一作品",
            normalized_title="同一作品",
            author="旧作者",
            normalized_author="旧作者",
            tags="[]",
            merge_key="isbn:9787111111115",
        )
    )
    db_session.commit()
    source = tmp_path / "同一作品.pdf"
    write_pdf_metadata_fixture(source, title="同一作品", author="新作者")

    result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=source,
            origin="MANUAL",
            original_name=source.name,
        ),
    )

    work = db_session.get(LibraryWork, "legacy-work")
    assert result.work_id == "legacy-work"
    assert work is not None
    assert work.merge_key == "同一作品"


def test_watched_pdf_numeric_embedded_titles_remain_distinct(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)
    first = tmp_path / "作品2023全彩版.pdf"
    second = tmp_path / "作品2026全彩版.pdf"
    write_pdf_metadata_fixture(first, title="作品2023全彩版", author="作者甲")
    write_pdf_metadata_fixture(second, title="作品2026全彩版", author="作者乙")

    first_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=first,
            origin="WATCH",
            original_name=first.name,
            library_id="folder-1",
        ),
    )
    second_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=second,
            origin="WATCH",
            original_name=second.name,
            library_id="folder-1",
        ),
    )

    assert first_result.work_id != second_result.work_id
    assert _count(db_session, "LibraryWork") == 2


def test_watched_pdf_similar_embedded_titles_do_not_merge_by_directory(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)
    first = tmp_path / "abcdefghij.pdf"
    second = tmp_path / "abcdefgxyz.pdf"
    write_pdf_metadata_fixture(first, title="abcdefghij", author="Author A")
    write_pdf_metadata_fixture(second, title="abcdefgxyz", author="Author B")

    first_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=first,
            origin="WATCH",
            original_name=first.name,
            library_id="folder-1",
        ),
    )
    second_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=second,
            origin="WATCH",
            original_name=second.name,
            library_id="folder-1",
        ),
    )

    assert first_result.work_id != second_result.work_id
    assert _count(db_session, "LibraryWork") == 2


def test_watched_pdf_titles_below_threshold_do_not_merge(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)
    first = tmp_path / "abcdefghij.pdf"
    second = tmp_path / "abcdezzzzz.pdf"
    write_pdf_metadata_fixture(first, title="abcdefghij", author="Author A")
    write_pdf_metadata_fixture(second, title="abcdezzzzz", author="Author B")

    first_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=first,
            origin="WATCH",
            original_name=first.name,
            library_id="folder-1",
        ),
    )
    second_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=second,
            origin="WATCH",
            original_name=second.name,
            library_id="folder-1",
        ),
    )

    assert first_result.work_id != second_result.work_id
    assert _count(db_session, "LibraryWork") == 2


def test_watched_pdf_similar_titles_in_different_directories_do_not_merge(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    test_settings.resolved_storage_root.mkdir(parents=True)
    first_dir = tmp_path / "edition-a"
    second_dir = tmp_path / "edition-b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "abcdefghij.pdf"
    second = second_dir / "abcdefgxyz.pdf"
    write_pdf_metadata_fixture(first, title="abcdefghij", author="Author A")
    write_pdf_metadata_fixture(second, title="abcdefgxyz", author="Author B")

    first_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=first,
            origin="WATCH",
            original_name=first.name,
            library_id="folder-1",
        ),
    )
    second_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=second,
            origin="WATCH",
            original_name=second.name,
            library_id="folder-1",
        ),
    )

    assert first_result.work_id != second_result.work_id
    assert _count(db_session, "LibraryWork") == 2


def test_manual_pdf_files_with_same_title_ignore_different_authors(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    work_dir = tmp_path / "[同名作品][作者甲]"
    work_dir.mkdir()
    first = work_dir / "同名作品一.pdf"
    second = work_dir / "同名作品二.pdf"
    write_pdf_metadata_fixture(first, title="同名作品", author="作者甲")
    write_pdf_metadata_fixture(second, title="同名作品", author="作者乙")

    first_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=first,
            origin="MANUAL",
            original_name=first.name,
        ),
    )
    second_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=second,
            origin="MANUAL",
            original_name=second.name,
        ),
    )

    assert first_result.work_id == second_result.work_id
    assert _count(db_session, "LibraryWork") == 1
    assert _count(db_session, "LibraryFile") == 2


def test_manual_title_and_author_override_folder_identity(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    work_dir = tmp_path / "原目录作品"
    work_dir.mkdir()
    epub = work_dir / "原目录作品 Vol.01.epub"
    write_epub_fixture(epub)

    result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=epub,
            origin="MANUAL",
            original_name=epub.name,
            requested_title="用户指定作品",
            requested_author="用户指定作者",
        ),
    )

    assert result.title == "用户指定作品"
    work = (
        db_session.execute(text("SELECT title, author FROM LibraryWork"))
        .mappings()
        .one()
    )
    assert dict(work) == {"title": "用户指定作品", "author": "用户指定作者"}


def test_import_epub_leaves_metadata_queue_to_organizer_without_blocking_on_external_services(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    create_metadata_provider_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    gateway = serve_import_metadata_gateways()
    try:
        epub = tmp_path / "fallback.epub"
        write_epub_fixture(epub)

        result = import_managed_book(
            db_session,
            test_settings,
            _options(
                source_file_path=epub, origin="MANUAL", original_name="fallback.epub"
            ),
        )

        assert result.import_status == "completed"
        assert gateway.requests == []
        assert (
            db_session.execute(text("SELECT COUNT(*) FROM MetadataLookupTask")).scalar()
            == 0
        )
        assert (
            db_session.execute(text("SELECT COUNT(*) FROM OrganizeJob")).scalar() == 0
        )
        assert (
            db_session.execute(
                text("SELECT organizeStatus FROM LibraryWork WHERE id = :id"),
                {"id": result.work_id},
            ).scalar()
            == "UNASSESSED"
        )
        assert (
            db_session.execute(
                text("SELECT status FROM ImportTask ORDER BY createdAt DESC LIMIT 1")
            ).scalar()
            == "COMPLETED"
        )
    finally:
        gateway.shutdown()


def test_parse_epub_import_metadata_excludes_navigation(tmp_path):
    epub = tmp_path / "nav.epub"
    write_epub_nav_fixture(epub)

    metadata = parse_epub_metadata(epub)

    assert "chapters" not in metadata
    assert "chapterCount" not in metadata
    assert metadata["isbn"] == "9787111111115"
    assert metadata["publisher"] == "测试出版社"
    assert metadata["subjects"] == ["悬疑", "推理"]
    assert metadata["coverPath"] == "cover.jpg"
    assert metadata["rawMetadata"]["dc:subject"] == ["悬疑", "推理"]
    assert metadata["rawMetadata"]["meta"] == [{"name": "cover", "content": "cover"}]


def test_parse_epub_metadata_does_not_extract_isbn_from_uuid(tmp_path):
    epub = tmp_path / "uuid.epub"
    with zipfile.ZipFile(epub, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?><container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0"?><package><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:identifier>urn:uuid:273fd756-62f2-4858-8d67-99e08f24bba9</dc:identifier>
            <dc:identifier>B00T238N28</dc:identifier>
            <dc:title>斯泰尔斯庄园奇案 (午夜文库)</dc:title><dc:creator>阿加莎·克里斯蒂</dc:creator>
            </metadata><manifest>
            <item id="c1" href="one.xhtml" media-type="application/xhtml+xml"/>
            </manifest><spine><itemref idref="c1"/></spine></package>""",
        )
        archive.writestr("OEBPS/one.xhtml", "<html><body><h1>正文</h1></body></html>")

    metadata = parse_epub_metadata(epub)

    assert metadata["isbn"] is None
    assert metadata["identifier"] == "B00T238N28"


def test_import_epub_with_missing_declared_cover_persists_default_cover(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    epub = tmp_path / "missing-cover.epub"
    write_epub_cover_reference_fixture(epub, "Images/coverpage.jpg")
    previous_default = (
        test_settings.resolved_storage_root / "covers/default-book-cover-v1.png"
    )
    previous_default.parent.mkdir(parents=True)
    previous_default.write_bytes(b"previous generated default")

    result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=epub, origin="MANUAL", original_name=epub.name),
    )

    assert result.import_status == "completed"
    assert result.total_units == 0
    volume_resource = (
        db_session.execute(
            text("SELECT importStatus, coverPath, coverStatus FROM LibraryVolume")
        )
        .mappings()
        .one()
    )
    assert dict(volume_resource) == {
        "importStatus": "COMPLETED",
        "coverPath": "covers/default-book-cover-v1.png",
        "coverStatus": "DEFAULT",
    }
    assert (
        db_session.execute(text("SELECT coverPath FROM LibraryVolume")).scalar()
        == "covers/default-book-cover-v1.png"
    )
    work = (
        db_session.execute(text("SELECT coverPath, coverStatus FROM LibraryWork"))
        .mappings()
        .one()
    )
    assert dict(work) == {
        "coverPath": "covers/default-book-cover-v1.png",
        "coverStatus": "DEFAULT",
    }
    stored_default = test_settings.resolved_storage_root / volume_resource["coverPath"]
    assert stored_default.read_bytes() == DEFAULT_COVER_ASSET_PATH.read_bytes()


def test_import_epub_resolves_cover_path_case_and_url_encoding(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    epub = tmp_path / "case-insensitive-cover.epub"
    write_epub_cover_reference_fixture(
        epub, "images/cover%20page.jpg", "OEBPS/Images/Cover Page.JPG"
    )

    result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=epub, origin="MANUAL", original_name=epub.name),
    )

    assert result.import_status == "completed"
    edition = (
        db_session.execute(text("SELECT coverPath, coverStatus FROM LibraryVolume"))
        .mappings()
        .one()
    )
    assert edition["coverStatus"] == "READY"
    assert Path(edition["coverPath"]).read_bytes() == b"optional-cover"


def test_import_comic_persists_page_units_and_detects_duplicate(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    work_dir = tmp_path / "星舰漫画"
    work_dir.mkdir()
    comic = work_dir / "星舰漫画 Vol.1.zip"
    write_comic_fixture(comic)

    first = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=comic, origin="MANUAL", original_name=comic.name),
    )
    second = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=comic, origin="MANUAL", original_name=comic.name),
    )

    assert first.type == "comic"
    assert first.total_units == 2
    assert second.duplicate is True
    assert _count(db_session, "LibraryWork") == 1
    assert _count(db_session, "LibraryVersion") == 1
    assert _count(db_session, "LibraryVolume") == 1
    assert _count(db_session, "LibraryReadingUnit") == 2
    page_rows = db_session.execute(
        text(
            "SELECT href, sortOrder, metadataJson FROM LibraryReadingUnit ORDER BY sortOrder"
        )
    ).mappings()
    pages = list(page_rows)
    assert [page["href"] for page in pages] == ["001.jpg", "002.jpg"]
    assert [page["sortOrder"] for page in pages] == [1, 2]
    first_page_metadata = json.loads(pages[0]["metadataJson"])
    assert first_page_metadata["zipEntryName"] == "001.jpg"
    assert first_page_metadata["originalName"] == "001.jpg"
    assert first_page_metadata["pageInVolume"] == 1
    assert first_page_metadata["pageInSection"] == 1
    assert (
        db_session.execute(text("SELECT pageIndexVersion FROM LibraryFile")).scalar()
        == 1
    )
    work = (
        db_session.execute(
            text("SELECT title, author, description, tags FROM LibraryWork")
        )
        .mappings()
        .first()
    )
    assert work["title"] == "星舰漫画"
    assert work["author"] == "画师"
    assert work["description"] == "漫画简介"
    assert json.loads(work["tags"]) == ["comic", "manga", "space"]
    edition = (
        db_session.execute(
            text(
                "SELECT publisher, pageCount, coverPath, coverStatus FROM LibraryVolume"
            )
        )
        .mappings()
        .first()
    )
    assert edition["publisher"] == "星舰出版社"
    assert edition["pageCount"] == 2
    assert edition["coverPath"]
    assert Path(edition["coverPath"]).read_bytes() == b"one"
    assert edition["coverStatus"] == "READY"
    volume = (
        db_session.execute(text("SELECT title, volumeIndex FROM LibraryVolume"))
        .mappings()
        .first()
    )
    assert volume["title"] == "第1卷"
    assert volume["volumeIndex"] == 1
    raw_metadata = json.loads(
        db_session.execute(
            text("SELECT rawJson FROM LibraryMetadata WHERE source = 'comic_info'")
        ).scalar()
    )
    assert raw_metadata["comicInfo"]["Publisher"] == "星舰出版社"
    assert raw_metadata["comicInfo"]["Tags"] == "manga,space"
    assert (
        db_session.execute(text("SELECT COUNT(*) FROM MetadataLookupTask")).scalar()
        == 0
    )


def test_import_comic_updates_generated_work_cover_to_first_volume(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    volume_2 = tmp_path / "星舰漫画 Vol.2.zip"
    volume_1 = tmp_path / "星舰漫画 Vol.1.zip"
    write_comic_fixture(volume_2, volume=2, cover_bytes=b"volume-two-cover")
    write_comic_fixture(volume_1, volume=1, cover_bytes=b"volume-one-cover")

    first_import = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=volume_2, origin="MANUAL", original_name=volume_2.name
        ),
    )
    second_import = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=volume_1, origin="MANUAL", original_name=volume_1.name
        ),
    )

    assert first_import.work_id == second_import.work_id
    work_cover = db_session.execute(
        text("SELECT coverPath FROM LibraryWork WHERE id = :work_id"),
        {"work_id": first_import.work_id},
    ).scalar()
    assert work_cover is not None
    assert Path(work_cover).read_bytes() == b"volume-one-cover"
    assert (
        db_session.execute(
            text("SELECT volumeIndex FROM LibraryVolume WHERE coverPath = :cover_path"),
            {"cover_path": work_cover},
        ).scalar()
        == 1
    )


def test_import_pdf_creates_library_records(db_session, test_settings, tmp_path):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    pdf = tmp_path / "manual.pdf"
    write_pdf_fixture(pdf)

    result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=pdf, origin="MANUAL", original_name="Manual PDF.pdf"),
    )

    assert result.import_status == "completed"
    assert result.type == "ebook"
    assert result.format == "pdf"
    assert result.total_units == 1
    assert _count(db_session, "LibraryWork") == 1
    assert _count(db_session, "LibraryVersion") == 1
    edition = (
        db_session.execute(
            text("SELECT format, coverPath, coverStatus FROM LibraryVolume")
        )
        .mappings()
        .first()
    )
    assert edition["format"] == "PDF"
    assert edition["coverStatus"] == "READY"
    assert edition["coverPath"]
    assert Path(edition["coverPath"]).read_bytes().startswith(b"\xff\xd8")
    assert (
        db_session.execute(text("SELECT coverPath FROM LibraryWork")).scalar()
        == edition["coverPath"]
    )
    assert (
        db_session.execute(text("SELECT coverPath FROM LibraryVolume")).scalar()
        == edition["coverPath"]
    )
    assert (
        db_session.execute(text("SELECT mimeType FROM LibraryFile")).scalar()
        == "application/pdf"
    )
    raw_metadata = json.loads(
        db_session.execute(
            text("SELECT rawJson FROM LibraryMetadata WHERE source = 'pdf'")
        ).scalar()
    )
    assert raw_metadata["coverRenderedFromPage"] == 1
    assert raw_metadata["contentClassification"]["kind"] == "IMAGE_ONLY"
    work = (
        db_session.execute(text("SELECT tags, mergeKey FROM LibraryWork"))
        .mappings()
        .one()
    )
    assert (
        db_session.execute(text("SELECT mediaKind FROM LibraryMediaVersion")).scalar()
        == "EBOOK"
    )
    assert json.loads(work["tags"]) == ["pdf"]
    assert work["mergeKey"] == "manualpdf"
    assert (
        db_session.execute(text("SELECT mediaKind FROM LibraryMediaVersion")).scalar()
        == "EBOOK"
    )
    assert _count(db_session, "LibraryReadingUnit") == 1


def test_existing_pdf_rescan_repairs_legacy_shared_cover_path(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    pdf = tmp_path / "legacy-cover.pdf"
    write_pdf_fixture(pdf)

    imported = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=pdf, origin="WATCH", original_name=pdf.name),
    )
    volume = db_session.get(LibraryVolume, imported.volume_id)
    work = db_session.get(LibraryWork, imported.work_id)
    assert volume is not None
    assert work is not None
    legacy_cover = (
        test_settings.resolved_storage_root
        / "books"
        / imported.work_id
        / imported.media_version_id
        / "cover.jpg"
    )
    legacy_cover.parent.mkdir(parents=True, exist_ok=True)
    legacy_cover.write_bytes(Path(str(volume.cover_path)).read_bytes())
    volume.cover_path = str(legacy_cover)
    work.cover_path = str(legacy_cover)
    db_session.commit()

    rescanned = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=pdf, origin="WATCH", original_name=pdf.name),
    )

    db_session.refresh(volume)
    db_session.refresh(work)
    assert rescanned.duplicate is True
    assert volume.cover_path != str(legacy_cover)
    assert Path(str(volume.cover_path)).parent.name == imported.volume_id
    assert Path(str(volume.cover_path)).is_file()
    assert work.cover_path == volume.cover_path


def test_import_text_pdf_remains_ebook(db_session, test_settings, tmp_path):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    pdf = tmp_path / "text-manual.pdf"
    write_text_pdf_fixture(
        pdf,
        "A substantive paragraph with more than forty letters for classification.",
    )

    result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=pdf, origin="MANUAL", original_name=pdf.name),
    )

    assert result.type == "ebook"
    assert (
        db_session.execute(text("SELECT mediaKind FROM LibraryMediaVersion")).scalar()
        == "EBOOK"
    )
    assert (
        db_session.execute(text("SELECT mediaKind FROM LibraryMediaVersion")).scalar()
        == "EBOOK"
    )
    assert (
        db_session.execute(text("SELECT format FROM LibraryVolume")).scalar() == "PDF"
    )


def test_import_pdf_maps_subject_keywords_metadata(db_session, test_settings, tmp_path):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    pdf = tmp_path / "metadata.pdf"
    write_pdf_metadata_fixture(pdf)

    parsed = inspect_pdf(pdf, "fallback.pdf")
    assert parsed.title == "星舰手册"
    assert parsed.author == "作者甲"
    assert parsed.description == "PDF 简介"
    assert parsed.tags == ("space", "manual", "science")

    result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=pdf, origin="MANUAL", original_name="fallback.pdf"),
    )

    assert result.import_status == "completed"
    work = (
        db_session.execute(
            text("SELECT title, author, description, tags FROM LibraryWork")
        )
        .mappings()
        .first()
    )
    assert work["title"] == "星舰手册"
    assert work["author"] == "作者甲"
    assert work["description"] == "PDF 简介"
    assert json.loads(work["tags"]) == ["pdf", "space", "manual", "science"]
    edition = (
        db_session.execute(text("SELECT description FROM LibraryVolume"))
        .mappings()
        .first()
    )
    assert edition["description"] == "PDF 简介"
    raw_metadata = json.loads(
        db_session.execute(
            text("SELECT rawJson FROM LibraryMetadata WHERE source = 'pdf'")
        ).scalar()
    )
    assert raw_metadata["Subject"] == "PDF 简介"
    assert raw_metadata["Keywords"] == "space,manual,science"


def test_monitor_ignore_rules():
    folder = LibraryConfig(
        id="1", root_path="/tmp", ignore_patterns="*.tmp\nskip", min_file_size_bytes=1
    )
    assert should_ignore_file(Path("/tmp/.hidden/book.epub"), folder)
    assert should_ignore_file(Path("/tmp/book.tmp"), folder)
    assert should_ignore_file(Path("/tmp/readme.md"), folder)
    assert not should_ignore_file(Path("/tmp/readme.txt"), folder)
    assert not should_ignore_file(Path("/tmp/book.epub"), folder)


def test_library_config_preserves_zero_minimum_file_size():
    folder = library_config(
        {
            "id": "folder-zero",
            "rootPath": "/library",
            "shelfId": None,
            "ignoreHidden": True,
            "ignorePatterns": None,
            "minFileSizeBytes": 0,
        }
    )

    assert folder.min_file_size_bytes == 0
    assert not folder.stability_check_enabled


def test_global_import_preferences_filter_extensions_and_patterns(
    db_session,
):
    set_system_setting(
        db_session, "import.allowedExtensions", json.dumps([".epub", ".pdf", ".txt"])
    )
    set_system_setting(db_session, "import.stabilityCheck.enabled", "false")
    set_system_setting(db_session, "import.stabilityCheck.seconds", "999")
    set_system_setting(db_session, "import.ignorePatterns", json.dumps("*.tmp\n草稿*"))

    projection = load_raw_import_preferences_projection(db_session)
    db_session.close()
    preferences = prepare_import_preferences(projection, legacy_stable_delay_ms=None)
    assert preferences.allowed_extensions == (".epub", ".txt", ".pdf")
    assert not preferences.stability_check_enabled
    assert preferences.stability_check_seconds == 300

    folder = LibraryConfig(
        id="1",
        root_path="/tmp",
        min_file_size_bytes=1,
        global_ignore_patterns=preferences.ignore_patterns,
        allowed_extensions=preferences.allowed_extensions,
    )
    assert not should_ignore_file(Path("/tmp/book.epub"), folder)
    assert should_ignore_file(Path("/tmp/book.cbz"), folder)
    assert not should_ignore_file(Path("/tmp/book.txt"), folder)
    assert should_ignore_file(Path("/tmp/草稿版本.epub"), folder)


def test_missing_import_preferences_keep_every_supported_extension_enabled(db_session):
    projection = load_raw_import_preferences_projection(db_session)
    db_session.close()
    preferences = prepare_import_preferences(projection, legacy_stable_delay_ms=None)
    assert preferences.allowed_extensions == SUPPORTED_IMPORT_EXTENSIONS
    assert ".cbr" in preferences.allowed_extensions
    assert ".rar" in preferences.allowed_extensions
    assert not preferences.stability_check_enabled


def test_text_file_imports_preserve_source_format_for_legacy_origin(
    db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    source = tmp_path / "源格式文本.txt"
    source.write_text(
        "第一章\n这是一段用于验证源格式导入的正文。\n\n第二章\n入库后应当可以直接阅读。",
        encoding="utf-8",
    )

    raw_result = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=source, origin="MANUAL", original_name=source.name),
    )
    raw_volume = (
        db_session.execute(
            text(
                "SELECT format, hidden, chapterCount, versionId FROM LibraryVolume WHERE id = :id"
            ),
            {"id": raw_result.volume_id},
        )
        .mappings()
        .one()
    )
    raw_file = (
        db_session.execute(
            text("SELECT path, kind FROM LibraryFile WHERE volumeId = :id"),
            {"id": raw_result.volume_id},
        )
        .mappings()
        .one()
    )
    assert raw_volume["format"] == "TXT"
    assert not raw_volume["hidden"]
    assert raw_volume["chapterCount"] is None
    assert raw_volume["versionId"]
    assert raw_result.total_units == 0
    assert db_session.scalar(select(func.count()).select_from(LibraryReadingUnit)) == 0
    assert Path(raw_file["path"]) == source.resolve()
    assert raw_file["kind"] == "TXT"

    legacy_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=source,
            origin="DEFERRED_CONVERSION",
            original_name=source.name,
        ),
    )
    visible_volumes = (
        db_session.execute(
            text(
                "SELECT volume.id, volume.format, volume.hidden, volume.derivedFromVolumeId "
                "FROM LibraryVolume AS volume "
                "JOIN LibraryVersion AS version ON version.id = volume.versionId "
                "WHERE version.workId = :work_id ORDER BY volume.sortOrder, volume.createdAt"
            ),
            {"work_id": raw_result.work_id},
        )
        .mappings()
        .all()
    )
    assert legacy_result.work_id == raw_result.work_id
    assert [(row["format"], bool(row["hidden"])) for row in visible_volumes] == [
        ("TXT", False),
    ]
    assert legacy_result.volume_id == raw_result.volume_id
    assert source.exists()
    assert db_session.scalars(select(BookConversionTask)).all() == []

    retried_result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=source,
            origin="DEFERRED_CONVERSION",
            original_name=source.name,
        ),
    )
    assert retried_result.volume_id == raw_result.volume_id
    assert len(db_session.scalars(select(LibraryVolume)).all()) == 1
    assert len(db_session.scalars(select(BookConversionTask)).all()) == 0


@pytest.mark.parametrize(
    ("suffix", "source_format", "mime_type"),
    [
        ("mobi", "MOBI", "application/x-mobipocket-ebook"),
        ("azw", "AZW", "application/vnd.amazon.ebook"),
        ("azw3", "AZW3", "application/vnd.amazon.ebook"),
        ("prc", "PRC", "application/x-mobipocket-ebook"),
        ("fb2", "FB2", "application/x-fictionbook+xml"),
        ("txt", "TXT", "text/plain"),
    ],
)
def test_native_reflowable_sources_do_not_require_automatic_conversion(
    db_session,
    test_settings,
    tmp_path,
    suffix: str,
    source_format: str,
    mime_type: str,
) -> None:
    create_worker_tables(db_session)
    source = tmp_path / f"native-reader.{suffix}"
    source.write_bytes(b"native reflowable fixture")

    imported = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=source,
            origin="MANUAL",
            original_name=source.name,
        ),
    )

    volume = db_session.get(LibraryVolume, imported.volume_id)
    book_file = db_session.scalars(
        select(LibraryFile).where(LibraryFile.volume_id == imported.volume_id)
    ).one()
    metadata = db_session.scalars(
        select(LibraryMetadata).where(
            LibraryMetadata.volume_id == imported.volume_id,
            LibraryMetadata.source == "reflowable_source",
        )
    ).one()

    assert volume is not None
    assert volume.format == source_format
    assert volume.hidden is False
    assert volume.chapter_count is None
    assert imported.total_units == 0
    assert db_session.scalar(select(func.count()).select_from(LibraryReadingUnit)) == 0
    assert book_file.kind == source_format
    assert book_file.mime_type == mime_type
    assert json.loads(metadata.raw_json)["readable"] is True


def test_native_reflowable_folder_work_keeps_filename_as_volume_title(
    db_session, test_settings, tmp_path
) -> None:
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    work_dir = tmp_path / "吉林美术-哆啦A梦珍藏版1-45卷 MOBI格式"
    work_dir.mkdir()
    volume_43 = work_dir / "哆啦A梦珍藏版Vol_43卷.mobi"
    volume_2 = work_dir / "哆啦A梦珍藏版Vol_02卷.mobi"
    volume_43.write_bytes(b"not-a-real-mobi-43")
    volume_2.write_bytes(b"not-a-real-mobi-02")

    first = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=volume_43,
            origin="WATCH",
            original_name=volume_43.name,
            library_id="folder-1",
        ),
    )
    second = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=volume_2,
            origin="WATCH",
            original_name=volume_2.name,
            library_id="folder-1",
        ),
    )

    assert first.work_id == second.work_id
    work = db_session.get(LibraryWork, first.work_id)
    assert work is not None
    assert work.title == "吉林美术-哆啦A梦珍藏版1-45卷 MOBI格式"
    volumes = db_session.scalars(
        select(LibraryVolume)
        .join(LibraryVersion, LibraryVersion.id == LibraryVolume.version_id)
        .where(LibraryVersion.work_id == first.work_id)
        .order_by(LibraryVolume.sort_order)
    ).all()
    assert [volume.title for volume in volumes] == [volume_2.stem, volume_43.stem]
    assert [volume.volume_index for volume in volumes] == [2, 43]
    assert [volume.sort_order for volume in volumes] == [2000, 43000]


def test_native_reflowable_ranges_sort_by_range_start(
    db_session, test_settings, tmp_path
) -> None:
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    work_dir = tmp_path / "瑞克和莫蒂1-60话 MOBI格式"
    work_dir.mkdir()
    sources = [
        work_dir / "瑞克与莫蒂 - 第016-020话.mobi",
        work_dir / "瑞克与莫蒂 - 第001-005话.mobi",
        work_dir / "瑞克与莫蒂 - 第006-010话.mobi",
    ]
    results = []
    for source in sources:
        source.write_bytes(f"fixture-{source.name}".encode())
        results.append(
            import_managed_book(
                db_session,
                test_settings,
                _options(
                    source_file_path=source,
                    origin="WATCH",
                    original_name=source.name,
                    library_id="folder-1",
                ),
            )
        )

    assert len({result.work_id for result in results}) == 1
    volumes = db_session.scalars(
        select(LibraryVolume)
        .join(LibraryVersion, LibraryVersion.id == LibraryVolume.version_id)
        .where(LibraryVersion.work_id == results[0].work_id)
        .order_by(LibraryVolume.sort_order)
    ).all()
    assert [volume.title for volume in volumes] == [
        sources[1].stem,
        sources[2].stem,
        sources[0].stem,
    ]
    assert [volume.volume_index for volume in volumes] == [1, 6, 16]
    assert [volume.sort_order for volume in volumes] == [1000, 6000, 16000]


def test_native_reflowable_without_volume_numbers_uses_similar_parent_work(
    db_session, test_settings, tmp_path
) -> None:
    create_worker_tables(db_session)
    add_library(db_session, tmp_path)
    work_dir = tmp_path / "Appendix"
    work_dir.mkdir()
    sources = [work_dir / "Appendix B.mobi", work_dir / "Appendix A.mobi"]
    results = []
    for source in sources:
        source.write_bytes(f"fixture-{source.name}".encode())
        results.append(
            import_managed_book(
                db_session,
                test_settings,
                _options(
                    source_file_path=source,
                    origin="WATCH",
                    original_name=source.name,
                    library_id="folder-1",
                ),
            )
        )

    assert len({result.work_id for result in results}) == 1
    volumes = db_session.scalars(select(LibraryVolume)).all()
    assert {volume.title for volume in volumes} == {source.stem for source in sources}
    assert {volume.volume_index for volume in volumes} == {None}


def test_direct_monitor_root_volumes_group_by_resolved_metadata(
    db_session, test_settings, tmp_path
) -> None:
    create_worker_tables(db_session)
    monitor_root = tmp_path / "books"
    monitor_root.mkdir()
    db_session.add(
        Library(
            organization_mode="FLAT",
            id="monitor-root",
            name="books",
            root_path=str(monitor_root),
            enabled=True,
        )
    )
    db_session.commit()
    volume_56 = monitor_root / "高桥留美子漫画 犬夜叉_第56卷.mobi"
    volume_55 = monitor_root / "高桥留美子漫画 犬夜叉_第55卷.mobi"
    volume_56.write_bytes(b"not-a-real-mobi-56")
    volume_55.write_bytes(b"not-a-real-mobi-55")

    first = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=volume_56,
            origin="MANUAL",
            original_name=volume_56.name,
        ),
    )
    second = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=volume_55,
            origin="MANUAL",
            original_name=volume_55.name,
        ),
    )

    assert first.work_id == second.work_id
    works = db_session.scalars(select(LibraryWork).order_by(LibraryWork.id)).all()
    assert [work.title for work in works] == ["高桥留美子漫画 犬夜叉"]
    assert all(work.title != monitor_root.name for work in works)
    volumes = db_session.scalars(
        select(LibraryVolume).order_by(LibraryVolume.volume_index)
    ).all()
    assert [volume.title for volume in volumes] == [volume_55.stem, volume_56.stem]
    assert [volume.volume_index for volume in volumes] == [55, 56]


def test_reimport_backfills_legacy_reflowable_metadata_without_creating_epub(
    db_session, test_settings, tmp_path
) -> None:
    create_worker_tables(db_session)
    source = tmp_path / "legacy.fb2"
    source.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
  <description><title-info><author><first-name>测试</first-name><last-name>作者</last-name></author>
  <book-title>真实标题</book-title><lang>zh-CN</lang></title-info></description>
  <body><section><title><p>第一章</p></title><p>正文</p></section>
  <section><title><p>第二章</p></title><p>正文</p></section></body>
</FictionBook>""",
        encoding="utf-8",
    )
    imported = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=source, origin="MANUAL", original_name=source.name),
    )
    volume = db_session.get(LibraryVolume, imported.volume_id)
    work = db_session.get(LibraryWork, imported.work_id)
    book_file = db_session.scalars(
        select(LibraryFile).where(LibraryFile.volume_id == imported.volume_id)
    ).one()
    assert volume is not None
    assert work is not None
    db_session.add(
        LibraryReadingUnit(
            id="stale-import-navigation",
            volume_id=volume.id,
            file_id=book_file.id,
            unit_type="chapter",
            title="旧目录",
            href="legacy.xhtml",
            sort_order=0,
            metadata_json="{}",
        )
    )
    volume.chapter_count = 1
    work.title = source.stem
    work.author = "未知作者"
    db_session.commit()
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    refreshed = import_managed_book(
        db_session,
        test_settings,
        _options(source_file_path=source, origin="MANUAL", original_name=source.name),
    )

    db_session.refresh(volume)
    db_session.refresh(work)
    assert refreshed.duplicate is True
    assert refreshed.merge_reason == "refreshed-native-metadata"
    assert volume.format == "FB2"
    assert volume.chapter_count is None
    db_session.refresh(book_file)
    assert book_file.size_bytes == source.stat().st_size
    assert work.title == "真实标题"
    assert work.author == "测试作者"
    assert (
        db_session.scalar(
            select(LibraryVolume)
            .join(LibraryVersion, LibraryVersion.id == LibraryVolume.version_id)
            .where(
                LibraryVersion.work_id == imported.work_id,
                LibraryVolume.format == "EPUB",
            )
        )
        is None
    )
    assert (
        len(
            db_session.scalars(
                select(LibraryReadingUnit).where(
                    LibraryReadingUnit.volume_id == imported.volume_id
                )
            ).all()
        )
        == 0
    )


def test_directory_scan_records_candidates_and_summary_in_system_log(
    db_session, tmp_path
):
    create_worker_tables(db_session)
    root = tmp_path / "scan-root"
    nested = root / "nested"
    hidden = root / ".hidden"
    nested.mkdir(parents=True)
    hidden.mkdir()
    (root / "first.epub").write_bytes(b"epub")
    (root / "notes.txt").write_text("ignored", encoding="utf-8")
    (nested / "second.pdf").write_bytes(b"pdf")
    (hidden / "hidden.cbz").write_bytes(b"hidden")
    folder = LibraryConfig(id="folder-scan", root_path=str(root), min_file_size_bytes=1)

    class CollectingQueue:
        def __init__(self):
            self.paths = []

        def enqueue(self, path, _folder):
            self.paths.append(path)

    import_queue = CollectingQueue()

    summary = scan_directory_with_logging(
        db_session,
        root,
        folder,
        import_queue,
        trigger="manual_rescan",
        requested_at="2026-07-17T10:00:00Z",
    )

    assert summary.directories_scanned == 2
    assert summary.files_scanned == 3
    assert summary.candidates_found == 3
    assert summary.ignored_files == 1
    assert {path.name for path in import_queue.paths} == {
        "first.epub",
        "notes.txt",
        "second.pdf",
    }
    events = (
        db_session.execute(
            text("SELECT action, message, metadata FROM SystemEvent ORDER BY createdAt")
        )
        .mappings()
        .all()
    )
    assert [event["action"] for event in events] == [
        "scan.started",
        "scan.completed",
    ]
    completed = json.loads(events[-1]["metadata"])
    assert completed["filesScanned"] == 3
    assert completed["candidatesFound"] == 3
    assert completed["ignoredFiles"] == 1
    assert completed["requestedAt"] == "2026-07-17T10:00:00Z"


def test_directory_scan_filters_minimum_file_size_before_queue(db_session, tmp_path):
    create_worker_tables(db_session)
    root = tmp_path / "scan-size-filter"
    root.mkdir()
    (root / "accepted.epub").write_bytes(b"a" * 16)
    (root / "too-small.epub").write_bytes(b"x")
    folder = LibraryConfig(
        id="folder-size-filter",
        root_path=str(root),
        min_file_size_bytes=10,
    )

    class CollectingQueue:
        def __init__(self):
            self.paths = []

        def enqueue(self, path, _folder):
            self.paths.append(path)

    import_queue = CollectingQueue()

    summary = scan_directory_with_logging(
        db_session, root, folder, import_queue, trigger="watcher_started"
    )

    assert summary.files_scanned == 2
    assert summary.candidates_found == 1
    assert summary.ignored_files == 1
    assert import_queue.paths == [root / "accepted.epub"]


def test_directory_scan_aggregates_ignore_reasons_without_file_events(
    db_session,
    tmp_path,
):
    create_worker_tables(db_session)
    root = tmp_path / "scan-ignore-rules"
    root.mkdir()
    for name in (
        "accepted.epub",
        "global-skip.epub",
        "folder-skip.epub",
        "not-enabled.pdf",
        "unsupported.bin",
        ".hidden.epub",
        ".upload-draft.part",
    ):
        (root / name).write_bytes(b"x" * 16)
    (root / "too-small.epub").write_bytes(b"x")
    folder = LibraryConfig(
        id="folder-ignore-rules",
        root_path=str(root),
        ignore_patterns="folder-*.epub",
        min_file_size_bytes=10,
        global_ignore_patterns="global-*.epub",
        allowed_extensions=(".epub",),
    )

    class CollectingQueue:
        def __init__(self):
            self.paths = []

        def enqueue(self, path, _folder):
            self.paths.append(path)

    import_queue = CollectingQueue()

    summary = scan_directory_with_logging(
        db_session,
        root,
        folder,
        import_queue,
        trigger="manual_rescan",
    )

    assert summary.files_scanned == 8
    assert summary.candidates_found == 1
    assert summary.ignored_files == 7
    assert import_queue.paths == [root / "accepted.epub"]
    completed = db_session.scalars(
        select(SystemEvent).where(SystemEvent.action == "scan.completed")
    ).one()
    assert set(completed.metadata_json["ignoredReasonCounts"]) == {
        "below_minimum_size",
        "extension_not_allowed",
        "global_ignore_pattern",
        "hidden_path",
        "library_ignore_pattern",
        "temporary_upload",
        "unsupported_file_type",
    }


def test_file_watcher_drops_ignored_file_without_file_level_event(
    db_session,
    tmp_path,
):
    create_worker_tables(db_session)
    source = tmp_path / "ignored-by-watcher.epub"
    source.write_bytes(b"ignored")
    folder = LibraryConfig(
        id="folder-watcher-ignore",
        root_path=str(tmp_path),
        ignore_patterns="ignored-by-watcher.epub",
        min_file_size_bytes=1,
    )
    manager = WorkerManager.__new__(WorkerManager)
    manager.db_factory = lambda: nullcontext(db_session)
    manager._imports_paused = False
    state = WatchState(
        observer=object(),
        root_path=tmp_path,
        config_signature="test",
    )

    manager.schedule_import(source, folder, state)

    events = db_session.scalars(
        select(SystemEvent).where(SystemEvent.action == "scan.file.ignored")
    ).all()
    assert events == []


def test_directory_scan_only_queues_files_without_existing_import_records(
    db_session, tmp_path
):
    create_worker_tables(db_session)
    root = tmp_path / "scan-cache-root"
    root.mkdir()
    cached = root / "cached.epub"
    added = root / "added.epub"
    cached.write_bytes(b"cached")
    added.write_bytes(b"added")
    db_session.execute(
        text(
            "INSERT INTO ImportTask (id, origin, status, sourcePath, progress, duplicate, duration, retryable, attempts, createdAt, updatedAt) "
            "VALUES ('cached-task', 'WATCH', 'COMPLETED', :source_path, 100, 0, 0, 0, 1, 'now', 'now')"
        ),
        {"source_path": str(cached.resolve())},
    )
    db_session.commit()
    folder = LibraryConfig(
        id="folder-cache", root_path=str(root), min_file_size_bytes=1
    )

    class CollectingQueue:
        def __init__(self):
            self.paths = []

        def enqueue(self, path, _folder):
            self.paths.append(path)

    import_queue = CollectingQueue()

    summary = scan_directory_with_logging(
        db_session, root, folder, import_queue, trigger="watcher_started"
    )

    assert summary.files_scanned == 2
    assert summary.candidates_found == 2
    assert summary.cached_files == 1
    assert import_queue.paths == [added]
    completed = db_session.execute(
        text(
            "SELECT metadata FROM SystemEvent WHERE action = 'scan.completed' ORDER BY createdAt DESC LIMIT 1"
        )
    ).scalar_one()
    assert json.loads(completed)["cachedFiles"] == 1


def test_parse_comic_volume_from_name_uses_parent_folder():
    parsed = parse_comic_volume_from_name(
        Path("/monitor/[齐木楠雄的灾难][麻生周一]/Vol.05.cbz"), "Vol.05.cbz"
    )
    assert parsed == {
        "seriesName": "齐木楠雄的灾难",
        "seriesIndex": 5.0,
        "title": "齐木楠雄的灾难 (5)",
        "author": "麻生周一",
    }
