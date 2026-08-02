import json
import zipfile
from contextlib import nullcontext
from functools import partial
from http.server import (
    BaseHTTPRequestHandler,
    SimpleHTTPRequestHandler,
    ThreadingHTTPServer,
)
from io import BytesIO
from itertools import count
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, quote, urlparse

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import event, func, select, text

from app.bootstrap.imports import (
    ImportWorkerRuntime,
    import_managed_book,
    process_import_task,
)
from app.contracts.imports import ImportTaskContract
from app.core.auth import hash_password
from app.core.config import get_settings
from app.db.base import Base
from app.db.runner import apply_schema
from app.models.auth import User
from app.models.import_pipeline import BookConversionTask, ImportTask, ImportWorkItem
from app.models.library import LibraryMediaVersion, LibraryVolume, LibraryWork
from app.modules.imports.application.dto import ImportOptions
from app.modules.imports.infrastructure.task_mapper import import_task_dto_from_row
from app.modules.media.infrastructure import http_streaming as media_streaming
from app.services.download_queue import process_next_download_task
from app.services.organize_service import (
    bangumi_candidates,
    douban_candidates,
    system_settings,
)
from tests.test_worker_importer import (
    create_worker_tables,
    write_comic_fixture,
    write_epub_fixture,
    write_pdf_fixture,
)


def _login(client, db_session):
    user = User(
        email="admin@example.com",
        name="管理员",
        password_hash=hash_password("starshipnas"),
        role="admin",
    )
    db_session.add(user)
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "starshipnas"},
    )
    assert response.status_code == 200


def _download_inbox(test_settings):
    directory = test_settings.resolved_monitor_root / "test-downloads"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _post_download_task(client, test_settings, payload):
    return client.post(
        "/api/download-tasks",
        json={"targetPath": str(_download_inbox(test_settings)), **payload},
    )


def test_library_filter_schema_is_read_only_and_bounded(client, db_session):
    create_worker_tables(db_session)
    _login(client, db_session)
    db_session.execute(
        text(
            "INSERT INTO `LibraryFacet` (`id`, `kind`, `name`, `normalizedName`, `aliases`, `createdAt`, `updatedAt`) "
            "VALUES ('facet-author', 'AUTHOR', '测试作者', '测试作者', '[]', 1, 1)"
        )
    )
    db_session.commit()
    statements: list[str] = []
    engine = db_session.get_bind()

    def capture_statement(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ):
        statements.append(" ".join(statement.split()).upper())

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        response = client.get("/api/library/filter-schema")
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert response.status_code == 200
    fields = {field["key"]: field for field in response.json()["data"]["fields"]}
    assert {option["value"] for option in fields["author"]["options"]} == {"测试作者"}
    assert len(statements) <= 25
    assert not any(
        statement.startswith(("INSERT ", "UPDATE ", "DELETE ", "REPLACE "))
        for statement in statements
    )


def _managed_fixture_dir(test_settings, name: str):
    directory = test_settings.resolved_monitor_root / "test-library" / name
    directory.mkdir(parents=True, exist_ok=True)
    return directory


_reader_progress_sequence = count(1)


def _save_reader_progress_v3(client, volume_id: str, legacy_payload: dict):
    reader_type = legacy_payload["readerType"]
    target_volume_id = legacy_payload.get("volumeId") or volume_id
    bootstrap = client.get(f"/api/reader/v3/volumes/{target_volume_id}/bootstrap")
    assert bootstrap.status_code == 200
    bootstrap_data = bootstrap.json()["data"]
    fingerprint = bootstrap_data["contentFingerprint"]
    page = int(
        legacy_payload.get("page")
        or legacy_payload.get("extra", {}).get("pageIndex")
        or 1
    )
    if reader_type == "comic":
        location = {
            "type": "comic",
            "volumeId": target_volume_id,
            "pageIndex": page,
        }
    elif reader_type == "pdf":
        location = {"type": "pdf", "pageNumber": page}
    else:
        location = {
            "type": "epub",
            "cfi": str(legacy_payload.get("position") or "0"),
            "spineIndex": max(0, page - 1),
            "progression": float(legacy_payload.get("percent") or 0) / 100,
        }
    sequence = next(_reader_progress_sequence)
    return client.put(
        f"/api/reader/v3/volumes/{target_volume_id}/progress",
        json={
            "schemaVersion": 3,
            "mutationId": f"compat-test-{sequence}",
            "clientId": "compat-test-client",
            "clientSequence": sequence,
            "contentFingerprint": fingerprint,
            "location": location,
            "percent": legacy_payload.get("percent", 0),
        },
    )


def _comic_page_jpeg_bytes() -> bytes:
    image = Image.new("RGB", (1126, 1600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (420, 220, 1030, 1520), fill=(219, 185, 184), outline=(12, 12, 12), width=7
    )
    draw.rectangle(
        (650, 1020, 1110, 1590), fill=(67, 88, 153), outline=(10, 14, 28), width=6
    )
    draw.ellipse(
        (470, 300, 740, 610), fill=(224, 188, 178), outline=(12, 12, 12), width=5
    )
    draw.polygon(
        [(520, 610), (760, 610), (840, 1450), (430, 1450)],
        fill=(65, 86, 153),
        outline=(10, 14, 28),
    )
    for offset in range(0, 980, 34):
        draw.line(
            (470 + offset // 5, 290 + offset, 840 - offset // 8, 500 + offset),
            fill=(18, 22, 33),
            width=2,
        )
    draw.text((92, 90), "漫画测试页", fill=(70, 84, 145))
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()


def _add_comic_volume(db_session, volume_id: str) -> None:
    work_id = f"{volume_id}-work"
    media_version_id = f"{volume_id}-media"
    db_session.add_all(
        [
            LibraryWork(
                id=work_id,
                origin="MANUAL",
                title="Comic fixture",
                normalized_title=work_id,
                author="Test author",
                normalized_author="test author",
                work_type="COMIC",
                tags="[]",
            ),
            LibraryMediaVersion(
                id=media_version_id,
                work_id=work_id,
                media_kind="COMIC",
            ),
            LibraryVolume(
                id=volume_id,
                media_version_id=media_version_id,
                title="Comic volume",
                sort_order=0,
                format="COMIC",
                resource_key=f"test:{volume_id}",
                import_status="COMPLETED",
            ),
        ]
    )
    db_session.flush()


def create_source_tables(db_session):
    db_session.execute(
        text(
            """CREATE TABLE IF NOT EXISTS Source (
                id TEXT PRIMARY KEY, name TEXT, kind TEXT, providerType TEXT, enabled BOOLEAN, priority INTEGER,
                config TEXT, credentialsKey TEXT, capabilities TEXT, rateLimit TEXT, lastTestAt TEXT,
                lastTestStatus TEXT, lastError TEXT, createdAt TEXT, updatedAt TEXT
            )"""
        )
    )
    db_session.execute(
        text(
            """CREATE TABLE IF NOT EXISTS SourceSearchRecord (
                id TEXT PRIMARY KEY, sourceId TEXT, providerType TEXT, externalId TEXT, title TEXT,
                subtitle TEXT, author TEXT, description TEXT, coverUrl TEXT, externalUrl TEXT, format TEXT,
                size TEXT, language TEXT, publishedAt TEXT, downloadAvailable BOOLEAN, downloadMeta TEXT,
                raw TEXT, status TEXT, createdAt TEXT, updatedAt TEXT, UNIQUE(sourceId, externalId)
            )"""
        )
    )
    db_session.commit()


def create_download_tables(db_session):
    db_session.execute(
        text(
            """CREATE TABLE IF NOT EXISTS DownloadTask (
                id TEXT PRIMARY KEY, sourceId TEXT, searchRecordId TEXT, bookId TEXT, type TEXT, status TEXT,
                displayName TEXT, remoteRef TEXT, savePath TEXT, filePath TEXT, errorMessage TEXT,
                progress INTEGER, createdAt TEXT, updatedAt TEXT
            )"""
        )
    )
    db_session.commit()


def set_default_download_folder(db_session, root_path):
    db_session.execute(
        text(
            """INSERT OR REPLACE INTO MonitorFolder (
                id, name, rootPath, enabled, ignoreHidden, minFileSizeBytes, createdAt, updatedAt
            ) VALUES (
                'download-folder-1', 'Downloads', :root_path, 1, 1, 1024, 'now', 'now'
            )"""
        ),
        {"root_path": str(root_path)},
    )
    db_session.commit()


def create_organize_detail_tables(db_session):
    db_session.execute(
        text(
            """CREATE TABLE IF NOT EXISTS MetadataSuggestion (
                id TEXT PRIMARY KEY, jobId TEXT, field TEXT, currentValue TEXT, suggestedValue TEXT,
                source TEXT, confidence REAL, reason TEXT, status TEXT, createdAt TEXT, updatedAt TEXT
            )"""
        )
    )
    db_session.execute(
        text(
            """CREATE TABLE IF NOT EXISTS DuplicateCandidate (
                id TEXT PRIMARY KEY, jobId TEXT, targetWorkId TEXT, reasons TEXT, confidence REAL,
                suggestedAction TEXT, status TEXT, createdAt TEXT, updatedAt TEXT
            )"""
        )
    )
    db_session.commit()


def serve_directory(directory):
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(directory))
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def serve_qbittorrent_api():
    requests = []

    class QbitHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_POST(self):
            length = int(self.headers.get("content-length") or "0")
            body = self.rfile.read(length).decode("utf-8")
            form = {key: values[0] for key, values in parse_qs(body).items()}
            requests.append(
                {"path": self.path, "form": form, "cookie": self.headers.get("cookie")}
            )
            if self.path == "/api/v2/auth/login":
                self.send_response(200)
                self.send_header("Set-Cookie", "SID=test-session")
                self.end_headers()
                self.wfile.write(b"Ok.")
                return
            if self.path == "/api/v2/torrents/add":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Ok.")
                return
            self.send_response(404)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), QbitHandler)
    server.requests = requests
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def serve_ai_metadata_gateway():
    requests = []

    class AiHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_POST(self):
            length = int(self.headers.get("content-length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("authorization"),
                    "body": body,
                }
            )
            payload = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "suggestions": [
                                        {
                                            "field": "title",
                                            "value": "AI Clean Title",
                                            "confidence": 0.91,
                                            "reason": "cleaned title",
                                        },
                                        {
                                            "field": "tags",
                                            "value": ["space", "ai"],
                                            "confidence": 0.7,
                                            "reason": "inferred tags",
                                        },
                                    ]
                                }
                            )
                        }
                    }
                ]
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), AiHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.requests = requests
    return server


def serve_douban_api_gateway():
    requests = []

    class DoubanHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_GET(self):
            requests.append({"path": self.path, "accept": self.headers.get("accept")})
            payload = {
                "id": "1234567",
                "title": "Douban Clean Title",
                "author": ["External Author"],
                "summary": "External description",
                "tags": [{"name": "fiction"}, {"name": "space"}],
                "pubdate": "2024-05",
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), DoubanHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.requests = requests
    return server


def serve_douban_crawler_gateway():
    requests = []

    class DoubanCrawlerHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_GET(self):
            requests.append(
                {
                    "path": self.path,
                    "accept": self.headers.get("accept"),
                    "user_agent": self.headers.get("user-agent"),
                }
            )
            if self.path.startswith("/subject_search"):
                cover_url = (
                    f"http://127.0.0.1:{self.server.server_port}/covers/cover.jpg"
                )
                revised_cover_url = (
                    f"http://127.0.0.1:{self.server.server_port}/covers/revised.jpg"
                )
                body = (
                    """
                <html><script>
                window.__DATA__ = {"items":[
                  {"tpl_name":"search_subject","id":4913064,"title":"活着","abstract":"余华 / 作家出版社 / 2012-8 / 28.00元","abstract_2":"","cover_url":"__COVER_URL__","url":"/subject/4913064/"},
                  {"tpl_name":"search_subject","id":4913065,"title":"活着：新版","abstract":"余华 / 北京十月文艺出版社 / 2021-1 / 45.00元","abstract_2":"新版简介","cover_url":"__REVISED_COVER_URL__","url":"/subject/4913065/"}
                ]};
                </script></html>
                """.replace("__COVER_URL__", cover_url)
                    .replace("__REVISED_COVER_URL__", revised_cover_url)
                    .replace(
                        '"/subject/4913065/"}',
                        '"/subject/4913065/","topics":[],"extra_actions":[],'
                        '"rating":{"count":21,"value":7.9}}',
                    )
                )
            elif self.path.startswith("/subject/4913064"):
                cover_url = (
                    f"http://127.0.0.1:{self.server.server_port}/covers/large.jpg"
                )
                body = """
                <html>
                  <script type="application/ld+json">{
                    "@context":"http://schema.org",
                    "@type":"Book",
                    "name":"活着",
                    "author":[{"@type":"Person","name":"余华"}],
                    "url":"https://book.douban.test/subject/4913064/",
                    "isbn":"9787506365437"
                  }</script>
                  <meta property="og:image" content="__COVER_URL__" />
                  <div id="info">
                    <span class="pl">出版社:</span> 作家出版社<br/>
                    <span class="pl">出版年:</span> 2012-8<br/>
                    <span class="pl">ISBN:</span> 9787506365437<br/>
                  </div>
                  <h2><span>内容简介</span></h2>
                  <div class="intro"><p>这是一本关于生命韧性的小说。</p></div>
                </html>
                """.replace("__COVER_URL__", cover_url)
            elif self.path.startswith("/covers/"):
                body = b"\xff\xd8\xff\xd9"
                self.send_response(200)
                self.send_header("content-type", "image/jpeg")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            else:
                self.send_response(404)
                self.end_headers()
                return
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), DoubanCrawlerHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.requests = requests
    return server


def serve_bangumi_api_gateway():
    requests = []

    class BangumiHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_POST(self):
            length = int(self.headers.get("content-length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("authorization"),
                    "user_agent": self.headers.get("user-agent"),
                    "body": body,
                }
            )
            payload = {
                "data": [
                    {
                        "id": 42,
                        "name": "Star Comic",
                        "name_cn": "星舰漫画",
                        "summary": "Bangumi description",
                        "date": "2022-07-01",
                        "tags": [{"name": "科幻"}, {"name": "漫画"}],
                        "infobox": [
                            {
                                "key": "别名",
                                "value": [{"k": "非官方", "v": "星舰漫游"}],
                            },
                            {"key": "作者", "value": "漫画作者"},
                            {"key": "出版社", "value": "出版社"},
                            {"key": "册数", "value": "3"},
                        ],
                    }
                ]
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), BangumiHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.requests = requests
    return server


def serve_priority_metadata_gateway(scenario: str):
    requests = []

    class PriorityMetadataHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def write_body(
            self, body: str | bytes, content_type: str = "text/html; charset=utf-8"
        ):
            encoded = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def json_response(self, payload: dict):
            self.write_body(json.dumps(payload, ensure_ascii=False), "application/json")

        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            requests.append({"method": "GET", "path": parsed.path, "query": query})
            if parsed.path == "/subject_search":
                search_text = (query.get("search_text") or [""])[0]
                items = []
                if scenario in {"douban-later-exact", "ai-title"}:
                    items = [
                        {
                            "tpl_name": "search_subject",
                            "id": 1001,
                            "title": "黑暗坡食人树：全新修订版",
                            "abstract": "[日]岛田庄司 / 新星出版社 / 2024-11 / 69.00元",
                            "abstract_2": "新版",
                            "cover_url": "https://img.example/revised.jpg",
                            "url": "/subject/1001/",
                        },
                        {
                            "tpl_name": "search_subject",
                            "id": 1002,
                            "title": "黑暗坡食人树",
                            "abstract": "[日]岛田庄司 / 新星出版社 / 2009-7 / 32.00元",
                            "abstract_2": "",
                            "cover_url": "https://img.example/exact.jpg",
                            "url": "/subject/1002/",
                        },
                    ]
                elif scenario in {"douban-no-exact", "no-exact"}:
                    items = [
                        {
                            "tpl_name": "search_subject",
                            "id": 1001,
                            "title": "黑暗坡食人树：全新修订版",
                            "abstract": "[日]岛田庄司 / 新星出版社 / 2024-11 / 69.00元",
                            "abstract_2": "新版",
                            "cover_url": "https://img.example/revised.jpg",
                            "url": "/subject/1001/",
                        }
                    ]
                body = f"<html><script>window.__DATA__ = {json.dumps({'items': items}, ensure_ascii=False)};</script><p>{search_text}</p></html>"
                self.write_body(body)
                return
            if parsed.path == "/subject/1002/":
                body = """
                <html>
                  <script type="application/ld+json">{
                    "@context":"http://schema.org",
                    "@type":"Book",
                    "name":"黑暗坡食人树",
                    "author":[{"@type":"Person","name":"[日]岛田庄司"}],
                    "url":"https://book.douban.test/subject/1002/",
                    "isbn":"9787802256866"
                  }</script>
                  <meta property="og:image" content="https://img.example/exact-large.jpg" />
                  <div id="info">
                    <span class="pl">出版社:</span> 新星出版社<br/>
                    <span class="pl">出版年:</span> 2009-7<br/>
                    <span class="pl">丛书:</span> 午夜文库·大师系列：岛田庄司作品·御手洗洁系列<br/>
                    <span class="pl">ISBN:</span> 9787802256866<br/>
                  </div>
                  <h2><span>内容简介</span></h2>
                  <div class="intro"><p>大楠树顶部开着锯齿状的缺口。</p></div>
                </html>
                """
                self.write_body(body)
                return
            if parsed.path == "/subject/1001/":
                body = """
                <html>
                  <script type="application/ld+json">{"@type":"Book","name":"黑暗坡食人树：全新修订版","author":[{"name":"[日]岛田庄司"}],"url":"https://book.douban.test/subject/1001/"}</script>
                  <div id="info"><span class="pl">出版社:</span> 新星出版社<br/><span class="pl">出版年:</span> 2024-11<br/></div>
                </html>
                """
                self.write_body(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("content-length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            requests.append({"method": "POST", "path": self.path, "body": body})
            if self.path == "/v0/search/subjects":
                if scenario == "douban-no-exact":
                    self.json_response(
                        {
                            "data": [
                                {
                                    "id": 42,
                                    "name": "Kura Yami Slope",
                                    "name_cn": "黑暗坡食人树",
                                    "summary": "Bangumi exact description",
                                    "date": "2009-07-01",
                                    "infobox": [
                                        {"key": "作者", "value": "岛田庄司"},
                                        {"key": "出版社", "value": "新星出版社"},
                                    ],
                                }
                            ]
                        }
                    )
                    return
                self.json_response(
                    {
                        "data": [
                            {
                                "id": 43,
                                "name": "Kura Yami Slope Revised",
                                "name_cn": "黑暗坡食人树：全新修订版",
                                "summary": "Bangumi non exact",
                            }
                        ]
                    }
                )
                return
            if self.path == "/chat/completions":
                self.json_response(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "suggestions": [
                                                {
                                                    "field": "title",
                                                    "value": "黑暗坡食人树",
                                                    "confidence": 0.92,
                                                    "reason": "cleaned hash",
                                                }
                                            ]
                                        },
                                        ensure_ascii=False,
                                    )
                                }
                            }
                        ]
                    }
                )
                return
            self.send_response(404)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), PriorityMetadataHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.requests = requests
    return server


def insert_priority_metadata_fixture(db_session, gateway, title: str = "黑暗坡食人树"):
    db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS SystemSetting (`key` TEXT PRIMARY KEY, `value` TEXT, `createdAt` TEXT, `updatedAt` TEXT)"
        )
    )
    work_columns = {
        row[1]
        for row in db_session.execute(text("PRAGMA table_info(LibraryWork)")).all()
    }
    if "seriesName" not in work_columns:
        db_session.execute(text("ALTER TABLE LibraryWork ADD COLUMN seriesName TEXT"))
    for key, value in {
        "metadata.douban.mode": "crawler",
        "metadata.douban.baseUrl": f"http://127.0.0.1:{gateway.server_port}",
        "metadata.douban.userAgent": "ShukuPriorityTest/1.0",
        "metadata.bangumi.baseUrl": f"http://127.0.0.1:{gateway.server_port}",
        "metadata.bangumi.userAgent": "ShukuPriorityTest/1.0",
        "metadata.ai.baseUrl": f"http://127.0.0.1:{gateway.server_port}",
        "metadata.ai.apiKey": "ai-key",
        "metadata.ai.model": "ai-model",
    }.items():
        db_session.execute(
            text(
                "INSERT INTO SystemSetting (`key`, `value`, `createdAt`, `updatedAt`) VALUES (:key, :value, 'now', 'now')"
            ),
            {"key": key, "value": value},
        )
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                mergeKey, createdAt, updatedAt
            ) VALUES (
                'work-priority', :title, :normalized, '', '', 'EPUB', 'UNKNOWN',
                'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING', 0, 0, 'epub:priority', 'now', 'now'
            )"""
        ),
        {"title": title, "normalized": title.lower()},
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, workId, origin, format, importStatus, sizeBytes, "primary", hidden, createdAt, updatedAt
            ) VALUES ('edition-priority', 'work-priority', 'MANUAL', 'EPUB', 'IMPORTED', 10, 1, 0, 'now', 'now')"""
        )
    )
    db_session.execute(
        text(
            "INSERT INTO OrganizeJob (id, workId, volumeId, status, issueCodes, summary, createdAt, updatedAt) VALUES ('job-priority', 'work-priority', 'edition-priority', 'REVIEWING', '[]', 'review', 'now', 'now')"
        )
    )
    db_session.commit()


def test_metadata_candidate_parsers_accept_common_provider_shapes():
    douban = douban_candidates(
        {
            "results": [
                {
                    "id": "douban-result-1",
                    "title": "搜索结果书名",
                    "authors": [{"name": "作者甲"}],
                    "summary": "简介",
                    "cover_url": "https://example.test/cover.jpg",
                    "pubdate": "2024-01",
                }
            ]
        },
        0.7,
    )
    bangumi = bangumi_candidates(
        {
            "list": [
                {
                    "id": 123,
                    "name": "Bangumi Name",
                    "name_cn": "中文条目",
                    "summary": "简介",
                    "images": {"common": "https://example.test/bgm.jpg"},
                }
            ]
        },
        0.82,
    )

    assert douban[0]["title"] == "搜索结果书名"
    assert douban[0]["author"] == "作者甲"
    assert douban[0]["coverUrl"] == "https://example.test/cover.jpg"
    assert bangumi[0]["title"] == "中文条目"
    assert bangumi[0]["coverUrl"] == "https://example.test/bgm.jpg"


def test_metadata_system_settings_decode_json_saved_values(db_session):
    db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS SystemSetting (`key` TEXT PRIMARY KEY, `value` TEXT, `createdAt` TEXT, `updatedAt` TEXT)"
        )
    )
    for key, value in {
        "metadata.douban.baseUrl": '""',
        "metadata.douban.enabled": "true",
        "metadata.bangumi.userAgent": '"ShukuStarship/0.1 (https://github.com/GMD170629/ermao-library)"',
    }.items():
        db_session.execute(
            text(
                "INSERT INTO SystemSetting (`key`, `value`, `createdAt`, `updatedAt`) VALUES (:key, :value, 'now', 'now')"
            ),
            {"key": key, "value": value},
        )
    db_session.commit()

    settings = system_settings(
        db_session,
        [
            "metadata.douban.baseUrl",
            "metadata.douban.enabled",
            "metadata.bangumi.userAgent",
        ],
    )

    assert settings == {
        "metadata.douban.baseUrl": "",
        "metadata.douban.enabled": "true",
        "metadata.bangumi.userAgent": "ShukuStarship/0.1 (https://github.com/GMD170629/ermao-library)",
    }


def test_core_compat_endpoints_return_envelopes(client, db_session, test_settings):
    test_settings.resolved_monitor_root.mkdir(parents=True)
    _login(client, db_session)

    endpoints = [
        "/api/dashboard/summary",
        "/api/dashboard/recent-books",
        "/api/dashboard/recent-reading",
        "/api/dashboard/continue-reading",
        "/api/dashboard/system-status",
        "/api/series",
        "/api/works",
        "/api/monitor-folders",
        "/api/system-settings",
        "/api/download-tasks",
        "/api/import-tasks",
        "/api/sources",
        "/api/source-search-records",
        "/api/shelves",
        "/api/organize/jobs",
        "/api/organize/pending",
        "/api/backups",
        "/api/tracking/release-title-parser?title=Example%20Vol.3%20Ch.4",
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code == 200, endpoint
        payload = response.json()
        assert payload["ok"] is True, endpoint
        assert "data" in payload, endpoint


def test_shelf_list_is_summary_and_detail_is_lightweight_paginated(client, db_session):
    db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS Shelf (id TEXT PRIMARY KEY, ownerUserId TEXT, name TEXT NOT NULL, description TEXT, kind TEXT NOT NULL DEFAULT 'STATIC', rulesJson TEXT NOT NULL DEFAULT '{}', pinned INTEGER NOT NULL DEFAULT 0, createdAt TEXT NOT NULL, updatedAt TEXT NOT NULL)"
        )
    )
    db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS ShelfWork (shelfId TEXT NOT NULL, workId TEXT NOT NULL, createdAt TEXT NOT NULL, PRIMARY KEY (shelfId, workId))"
        )
    )
    db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS LibraryWork (id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT, hidden BOOLEAN, createdAt TEXT, updatedAt TEXT)"
        )
    )
    for index in range(25):
        db_session.execute(
            text(
                "INSERT INTO LibraryWork "
                "(id, title, normalizedTitle, author, normalizedAuthor, workType, tags, hidden, createdAt, updatedAt) "
                "VALUES (:id, :title, :title, '林川', '林川', 'EPUB', '[]', 0, 'now', 'now')"
            ),
            {"id": f"work-{index + 1:02d}", "title": f"星海列车 {index + 1:02d}"},
        )
    db_session.commit()
    _login(client, db_session)

    book_ids = [f"work-{index + 1:02d}" for index in range(25)]
    created = client.post(
        "/api/shelves",
        json={"name": "漫画", "description": "收藏漫画", "bookIds": book_ids},
    )
    assert created.status_code == 201
    shelf = created.json()["data"]["shelf"]
    assert shelf["name"] == "漫画"
    assert shelf["bookIds"] == book_ids
    assert shelf["bookCount"] == 25
    assert len(shelf["books"]) == 24
    assert set(shelf["books"][0]) == {"id", "title", "author", "coverUrl"}

    statements: list[str] = []
    engine = db_session.get_bind()

    def capture_statement(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ):
        statements.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        listed = client.get("/api/shelves").json()["data"]["shelves"]
        detailed = client.get(
            f"/api/shelves/{shelf['id']}?page=2&pageSize=10&includeBookIds=false"
        ).json()["data"]["shelf"]
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert listed[0]["id"] == shelf["id"]
    personal_shelf = next(item for item in listed if item["id"] == shelf["id"])
    assert personal_shelf["bookCount"] == 25
    assert len(personal_shelf["books"]) == 3
    assert "bookIds" not in personal_shelf
    assert detailed["bookCount"] == 25
    assert detailed["page"] == 2
    assert detailed["pageSize"] == 10
    assert detailed["totalPages"] == 3
    assert [book["id"] for book in detailed["books"]] == book_ids[10:20]
    assert "bookIds" not in detailed
    assert len(statements) < 60

    updated = client.patch(f"/api/shelves/{shelf['id']}", json={"bookIds": []})
    assert updated.status_code == 200
    assert updated.json()["data"]["shelf"]["name"] == "漫画"
    assert updated.json()["data"]["shelf"]["books"] == []

    deleted = client.delete(f"/api/shelves/{shelf['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True


def test_series_endpoint_hides_single_book_series_by_default(client, db_session):
    create_worker_tables(db_session)
    work_columns = {
        row[1]
        for row in db_session.execute(text("PRAGMA table_info(LibraryWork)")).all()
    }
    if "seriesName" not in work_columns:
        db_session.execute(text("ALTER TABLE LibraryWork ADD COLUMN seriesName TEXT"))
    if "seriesIndex" not in work_columns:
        db_session.execute(text("ALTER TABLE LibraryWork ADD COLUMN seriesIndex REAL"))
    _login(client, db_session)
    for work_id, title, series_name, hidden, updated_at in [
        ("series-visible-1", "星舰纪元 一", "星舰纪元", 0, "2026-06-11T10:00:00"),
        ("series-visible-2", "星舰纪元 二", " 星舰纪元 ", 0, "2026-06-11T12:00:00"),
        ("series-other", "午夜档案", "午夜档案", 0, "2026-06-10T00:00:00"),
        ("series-hidden", "隐藏系列", "隐藏系列", 1, "2026-06-12T00:00:00"),
        ("series-empty", "无系列", "", 0, "2026-06-12T01:00:00"),
    ]:
        db_session.execute(
            text(
                """INSERT INTO LibraryWork (
                    id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                    trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                    seriesName, mergeKey, createdAt, updatedAt
                ) VALUES (
                    :id, :title, :normalized_title, 'Author', 'author', 'EPUB', 'UNKNOWN',
                    'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING', :hidden, 0,
                    :series_name, :merge_key, '2026-06-10T00:00:00', :updated_at
                )"""
            ),
            {
                "id": work_id,
                "title": title,
                "normalized_title": title.lower().replace(" ", ""),
                "hidden": hidden,
                "series_name": series_name,
                "merge_key": f"epub:{work_id}:author",
                "updated_at": updated_at,
            },
        )
    db_session.commit()

    response = client.get("/api/series?visibility=active&limit=10")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["total"] == 1
    assert payload["data"]["series"] == [
        {"name": "星舰纪元", "bookCount": 2, "latestUpdatedAt": "2026-06-11T12:00:00Z"},
    ]

    include_single = client.get("/api/series?visibility=active&limit=10&minBooks=1")
    assert include_single.status_code == 200
    assert include_single.json()["data"]["total"] == 2
    assert include_single.json()["data"]["series"] == [
        {"name": "星舰纪元", "bookCount": 2, "latestUpdatedAt": "2026-06-11T12:00:00Z"},
        {"name": "午夜档案", "bookCount": 1, "latestUpdatedAt": "2026-06-10T00:00:00Z"},
    ]


def test_management_folders_series_group_hides_empty_and_single_book_series(
    client, db_session
):
    create_worker_tables(db_session)
    work_columns = {
        row[1]
        for row in db_session.execute(text("PRAGMA table_info(LibraryWork)")).all()
    }
    if "seriesName" not in work_columns:
        db_session.execute(text("ALTER TABLE LibraryWork ADD COLUMN seriesName TEXT"))
    _login(client, db_session)
    for work_id, title, series_name in [
        ("multi-1", "星舰纪元 一", "星舰纪元"),
        ("multi-2", "星舰纪元 二", " 星舰纪元 "),
        ("single-1", "午夜档案", "午夜档案"),
        ("empty-1", "无系列", ""),
    ]:
        db_session.execute(
            text(
                """INSERT INTO LibraryWork (
                    id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                    trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                    seriesName, mergeKey, createdAt, updatedAt
                ) VALUES (
                    :id, :title, :normalized_title, 'Author', 'author', 'EPUB', 'UNKNOWN',
                    'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING', 0, 0,
                    :series_name, :merge_key, '2026-06-10T00:00:00', '2026-06-10T00:00:00'
                )"""
            ),
            {
                "id": work_id,
                "title": title,
                "normalized_title": title.lower().replace(" ", ""),
                "series_name": series_name,
                "merge_key": f"epub:{work_id}:author",
            },
        )
    db_session.commit()

    response = client.get("/api/management/folders")
    assert response.status_code == 200
    series_groups = response.json()["data"]["logical"]["series"]
    assert len(series_groups) == 1
    assert series_groups[0]["name"] == "星舰纪元"
    assert series_groups[0]["count"] == 2
    assert series_groups[0]["sizeBytes"] == 0
    assert {item["title"] for item in series_groups[0]["items"]} == {
        "星舰纪元 一",
        "星舰纪元 二",
    }


def test_works_series_filter_is_exact_and_accepts_unicode_names(client, db_session):
    create_worker_tables(db_session)
    work_columns = {
        row[1]
        for row in db_session.execute(text("PRAGMA table_info(LibraryWork)")).all()
    }
    if "seriesName" not in work_columns:
        db_session.execute(text("ALTER TABLE LibraryWork ADD COLUMN seriesName TEXT"))
    if "seriesIndex" not in work_columns:
        db_session.execute(text("ALTER TABLE LibraryWork ADD COLUMN seriesIndex REAL"))
    _login(client, db_session)
    for work_id, title, series_name, series_index in [
        ("exact-1", "第 2 卷", "午夜文库·大师系列：岛田庄司作品", 2),
        ("exact-2", "第 1 卷", "午夜文库·大师系列：岛田庄司作品", 1),
        ("fuzzy-title", "午夜文库·大师系列：岛田庄司作品 番外", "其他系列", 1),
        ("near-series", "相近系列", "午夜文库·大师系列：岛田庄司作品 番外", 1),
    ]:
        db_session.execute(
            text(
                """INSERT INTO LibraryWork (
                    id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                    trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                    seriesName, seriesIndex, mergeKey, createdAt, updatedAt
                ) VALUES (
                    :id, :title, :normalized_title, 'Author', 'author', 'EPUB', 'UNKNOWN',
                    'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING', 0, 0,
                    :series_name, :series_index, :merge_key, '2026-06-10T00:00:00', '2026-06-10T00:00:00'
                )"""
            ),
            {
                "id": work_id,
                "title": title,
                "normalized_title": title.lower().replace(" ", ""),
                "series_name": series_name,
                "series_index": series_index,
                "merge_key": f"epub:{work_id}:author",
            },
        )
    db_session.commit()

    response = client.get(
        "/api/works",
        params={
            "seriesName": "午夜文库·大师系列：岛田庄司作品",
            "sort": "series_index",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["total"] == 2
    assert [book["id"] for book in payload["data"]["books"]] == ["exact-2", "exact-1"]


def test_works_library_filters_cover_type_status_tags_and_import_state(
    client, db_session
):
    create_worker_tables(db_session)
    _login(client, db_session)
    fixtures = [
        (
            "comic-ready",
            "漫画成品",
            "COMIC",
            "READING",
            "ONGOING",
            "TRACKING",
            '["侦探", "漫画"]',
            "READY",
            "covers/comic.jpg",
            1,
            "APPLIED",
            "2026-06-10T10:00:00",
        ),
        (
            "comic-new",
            "漫画新导入",
            "COMIC",
            "WANT",
            "UNKNOWN",
            "NOT_TRACKING",
            '["新导入"]',
            "PENDING",
            None,
            0,
            "REVIEWING",
            "2026-06-11T10:00:00",
        ),
        (
            "epub-ready",
            "电子书",
            "EPUB",
            "FINISHED",
            "COMPLETED",
            "PAUSED",
            '["侦探"]',
            "READY",
            "covers/epub.jpg",
            1,
            "APPLIED",
            "2026-06-09T10:00:00",
        ),
        (
            "pdf-ready",
            "PDF 手册",
            "PDF",
            "WANT",
            "UNKNOWN",
            "NOT_TRACKING",
            "[]",
            "READY",
            "covers/pdf.jpg",
            1,
            "APPLIED",
            "2026-06-08T10:00:00",
        ),
    ]
    for (
        work_id,
        title,
        work_type,
        _legacy_status,
        publication_status,
        tracking_status,
        tags,
        cover_status,
        cover_path,
        organized,
        organize_status,
        created_at,
    ) in fixtures:
        db_session.execute(
            text(
                """INSERT INTO LibraryWork (
                    id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                    trackingStatus, tags, metadataQuality, organizeStatus, coverPath, coverStatus, hidden, organized,
                    mergeKey, createdAt, updatedAt
                ) VALUES (
                    :id, :title, :normalized_title, 'Author', 'author', :work_type, :publication_status,
                    :tracking_status, :tags, 0, :organize_status, :cover_path, :cover_status, 0, :organized,
                    :merge_key, :created_at, :created_at
                )"""
            ),
            {
                "id": work_id,
                "title": title,
                "normalized_title": title.lower().replace(" ", ""),
                "work_type": work_type,
                "publication_status": publication_status,
                "tracking_status": tracking_status,
                "tags": tags,
                "cover_status": cover_status,
                "cover_path": cover_path,
                "organized": organized,
                "organize_status": organize_status,
                "merge_key": f"{work_type.lower()}:{work_id}:author",
                "created_at": created_at,
            },
        )
    db_session.execute(
        text(
            """INSERT INTO LibraryMediaVersion (
                id, workId, mediaKind, createdAt, updatedAt
            ) VALUES
                ('comic-ready-media', 'comic-ready', 'COMIC', 'now', 'now'),
                ('comic-new-media', 'comic-new', 'COMIC', 'now', 'now'),
                ('epub-ready-media', 'epub-ready', 'EBOOK', 'now', 'now'),
                ('pdf-ready-media', 'pdf-ready', 'EBOOK', 'now', 'now')
            """
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, mediaVersionId, origin, title, sortOrder, format, resourceKey,
                importStatus, sizeBytes, coverStatus, hidden, createdAt, updatedAt
            ) VALUES
                ('comic-ready-edition', 'comic-ready-media', 'MANUAL', 'Comic', 0, 'CBZ', 'test:comic-ready', 'COMPLETED', 10, 'PENDING', 0, 'now', 'now'),
                ('comic-new-edition', 'comic-new-media', 'MANUAL', 'Comic', 0, 'ZIP', 'test:comic-new', 'COMPLETED', 10, 'PENDING', 0, 'now', 'now'),
                ('epub-ready-edition', 'epub-ready-media', 'MANUAL', 'EPUB', 0, 'EPUB', 'test:epub-ready', 'COMPLETED', 10, 'PENDING', 0, 'now', 'now'),
                ('pdf-ready-edition', 'pdf-ready-media', 'MANUAL', 'PDF', 0, 'PDF', 'test:pdf-ready', 'COMPLETED', 10, 'PENDING', 0, 'now', 'now')
            """
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryFile (
                id, volumeId, path, kind, mimeType, sizeBytes, sortOrder, createdAt, updatedAt
            ) VALUES
                ('comic-ready-file', 'comic-ready-edition', '/books/comic-ready.cbz', 'COMIC', 'application/zip', 10, 0, 'now', 'now'),
                ('comic-new-file', 'comic-new-edition', '/books/comic-new.zip', 'COMIC', 'application/zip', 10, 0, 'now', 'now')
            """
        )
    )
    db_session.commit()

    cases = [
        ({"type": "COMIC"}, ["comic-new", "comic-ready"]),
        ({"type": "ebook"}, ["epub-ready", "pdf-ready"]),
        ({"type": "ZIP"}, ["comic-new"]),
        ({"publicationStatus": "ONGOING"}, ["comic-ready"]),
        ({"trackingStatus": "TRACKING"}, ["comic-ready"]),
        ({"tag": "侦探"}, ["comic-ready", "epub-ready"]),
        ({"missingCover": "true"}, ["comic-new"]),
        ({"newImport": "true"}, ["comic-new"]),
    ]
    for params, expected_ids in cases:
        response = client.get("/api/works", params={**params, "sort": "recent_import"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert [book["id"] for book in payload["data"]["books"]] == expected_ids, params

    unread = client.get("/api/works/comic-new").json()["data"]["book"]
    assert unread["completed"] is False
    assert unread["mediaVersions"][0]["volumes"][0]["progress"] == 0


def test_work_detail_epub_reading_units_are_paginated_and_clamped(client, db_session):
    create_worker_tables(db_session)
    _login(client, db_session)
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, title, normalizedTitle, author, normalizedAuthor, workType,
                publicationStatus, trackingStatus, tags, metadataQuality,
                organizeStatus, coverStatus, hidden, organized, mergeKey, createdAt, updatedAt
            ) VALUES (
                'paged-epub', 'Paged EPUB', 'pagedepub', 'Author', 'author', 'EPUB',
                'UNKNOWN', 'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING', 0, 0,
                'epub:paged-epub:author', 'now', 'now'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryMediaVersion (id, workId, mediaKind, createdAt, updatedAt)
            VALUES ('paged-epub-media', 'paged-epub', 'EBOOK', 'now', 'now')"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, mediaVersionId, origin, title, volumeIndex, sortOrder, format,
                resourceKey, importStatus, sizeBytes, chapterCount, coverStatus,
                hidden, createdAt, updatedAt
            ) VALUES (
                'paged-epub-volume', 'paged-epub-media', 'MANUAL', '正文', 1, 0,
                'EPUB', 'test:paged-epub', 'COMPLETED', 0, 125, 'PENDING',
                0, 'now', 'now'
            )"""
        )
    )
    for index in range(1, 126):
        db_session.execute(
            text(
                """INSERT INTO LibraryReadingUnit (
                    id, volumeId, fileId, unitType, title, href, mediaType, sortOrder,
                    metadataJson, createdAt, updatedAt
                ) VALUES (
                    :id, 'paged-epub-volume', NULL, 'chapter', :title, :href,
                    'application/xhtml+xml', :sort_order, '{}', 'now', 'now'
                )"""
            ),
            {
                "id": f"chapter-{index}",
                "title": f"第 {index} 章",
                "href": f"{index}.xhtml",
                "sort_order": index,
            },
        )
    db_session.commit()

    page_two = client.get(
        "/api/works/paged-epub",
        params={"chapterPage": 2, "chapterPageSize": 50},
    )
    assert page_two.status_code == 200
    page_two_data = page_two.json()["data"]
    assert page_two_data["readingUnitsPage"] == {
        "page": 2,
        "pageSize": 50,
        "total": 125,
        "totalPages": 3,
    }
    assert [unit["title"] for unit in page_two_data["readingUnits"][:2]] == [
        "第 51 章",
        "第 52 章",
    ]
    assert page_two_data["readingUnits"][-1]["title"] == "第 100 章"

    clamped = client.get(
        "/api/works/paged-epub",
        params={"chapterPage": 999, "chapterPageSize": 50},
    ).json()["data"]
    assert clamped["readingUnitsPage"] == {
        "page": 3,
        "pageSize": 50,
        "total": 125,
        "totalPages": 3,
    }
    assert [unit["title"] for unit in clamped["readingUnits"]] == [
        f"第 {index} 章" for index in range(101, 126)
    ]


def test_work_detail_empty_epub_and_comic_return_reading_units_page(client, db_session):
    create_worker_tables(db_session)
    _login(client, db_session)
    for work_id, media_id, volume_id, fmt, work_type, media_kind in [
        (
            "empty-epub",
            "empty-epub-media",
            "empty-epub-volume",
            "EPUB",
            "EPUB",
            "EBOOK",
        ),
        (
            "comic-detail",
            "comic-detail-media",
            "comic-detail-volume",
            "CBZ",
            "COMIC",
            "COMIC",
        ),
    ]:
        db_session.execute(
            text(
                """INSERT INTO LibraryWork (
                    id, title, normalizedTitle, author, normalizedAuthor, workType,
                    publicationStatus, trackingStatus, tags, metadataQuality,
                    organizeStatus, coverStatus, hidden, organized, mergeKey, createdAt, updatedAt
                ) VALUES (
                    :work_id, :work_id, :work_id, 'Author', 'author', :work_type,
                    'UNKNOWN', 'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING',
                    0, 0, :merge_key, 'now', 'now'
                )"""
            ),
            {
                "work_id": work_id,
                "work_type": work_type,
                "merge_key": f"{fmt.lower()}:{work_id}:author",
            },
        )
        db_session.execute(
            text(
                """INSERT INTO LibraryMediaVersion (
                    id, workId, mediaKind, createdAt, updatedAt
                ) VALUES (:media_id, :work_id, :media_kind, 'now', 'now')"""
            ),
            {"media_id": media_id, "work_id": work_id, "media_kind": media_kind},
        )
        db_session.execute(
            text(
                """INSERT INTO LibraryVolume (
                    id, mediaVersionId, origin, title, volumeIndex, sortOrder,
                    format, resourceKey, importStatus, sizeBytes, pageCount,
                    chapterCount, coverStatus, hidden, createdAt, updatedAt
                ) VALUES (
                    :volume_id, :media_id, 'MANUAL', :title, 1, 0, :fmt,
                    :resource_key, 'COMPLETED', 0, :page_count, 0, 'PENDING',
                    0, 'now', 'now'
                )"""
            ),
            {
                "volume_id": volume_id,
                "media_id": media_id,
                "title": "第 1 卷" if media_kind == "COMIC" else "正文",
                "fmt": fmt,
                "resource_key": f"test:{volume_id}",
                "page_count": 5 if media_kind == "COMIC" else 0,
            },
        )
    db_session.commit()

    for work_id in ("empty-epub", "comic-detail"):
        detail = client.get(
            f"/api/works/{work_id}", params={"chapterPageSize": 50}
        ).json()["data"]
        assert detail["readingUnits"] == []
        assert detail["readingUnitsPage"] == {
            "page": 1,
            "pageSize": 50,
            "total": 0,
            "totalPages": 1,
        }
    comic = client.get("/api/works/comic-detail", params={"detailTab": "COMIC"}).json()[
        "data"
    ]
    assert comic["activeMedia"]["selectedVolumeId"] == "comic-detail-volume"


def test_works_recent_read_sort_uses_latest_volume_progress_across_pages(
    client, db_session
):
    create_worker_tables(db_session)
    _login(client, db_session)
    user_id = db_session.query(User).filter(User.email == "admin@example.com").one().id
    fixtures = [
        ("work-old", "较早阅读", "2026-06-12T10:00:00"),
        ("work-new", "最近阅读", "2026-06-10T10:00:00"),
        ("work-unread", "尚未阅读", "2026-06-18T10:00:00"),
    ]
    for work_id, title, updated_at in fixtures:
        db_session.execute(
            text(
                """INSERT INTO LibraryWork (
                    id, title, normalizedTitle, author, normalizedAuthor, workType,
                    publicationStatus, trackingStatus, tags, metadataQuality,
                    organizeStatus, coverStatus, hidden, organized, mergeKey, createdAt, updatedAt
                ) VALUES (
                    :id, :title, :normalized_title, 'Author', 'author', 'EPUB',
                    'UNKNOWN', 'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING',
                    0, 0, :merge_key, '2026-06-01T10:00:00', :updated_at
                )"""
            ),
            {
                "id": work_id,
                "title": title,
                "normalized_title": title.lower().replace(" ", ""),
                "merge_key": f"epub:{work_id}:author",
                "updated_at": updated_at,
            },
        )
        db_session.execute(
            text(
                """INSERT INTO LibraryMediaVersion (
                    id, workId, mediaKind, createdAt, updatedAt
                ) VALUES (:id, :work_id, 'EBOOK', 'now', 'now')"""
            ),
            {"id": f"{work_id}-media", "work_id": work_id},
        )
        db_session.execute(
            text(
                """INSERT INTO LibraryVolume (
                    id, mediaVersionId, origin, title, sortOrder, format, resourceKey,
                    importStatus, sizeBytes, coverStatus, hidden, createdAt, updatedAt
                ) VALUES (
                    :id, :media_id, 'MANUAL', :title, 0, 'EPUB', :resource_key,
                    'COMPLETED', 10, 'PENDING', 0, 'now', 'now'
                )"""
            ),
            {
                "id": f"{work_id}-volume",
                "media_id": f"{work_id}-media",
                "title": title,
                "resource_key": f"test:{work_id}-volume",
            },
        )
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, mediaVersionId, origin, title, volumeIndex, sortOrder, format,
                resourceKey, importStatus, sizeBytes, coverStatus, hidden, createdAt, updatedAt
            ) VALUES (
                'work-new-volume-2', 'work-new-media', 'MANUAL', '第二卷', 2, 1,
                'EPUB', 'test:work-new-volume-2', 'COMPLETED', 10, 'PENDING',
                0, 'now', 'now'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryReadingProgress (
                id, userId, volumeId, readerType, position, page, percent, extra,
                schemaVersion, createdAt, updatedAt
            ) VALUES
                ('progress-old', :user_id, 'work-old-volume', 'epub', 'cfi-old', 1, 80, '{}', 3, '2026-06-15T08:00:00', '2026-06-15T08:00:00'),
                ('progress-new-old', :user_id, 'work-new-volume', 'epub', 'cfi-first', 50, 50, '{}', 3, '2026-06-16T09:00:00', '2026-06-16T09:00:00'),
                ('progress-new', :user_id, 'work-new-volume-2', 'epub', 'cfi-finished', 100, 100, '{}', 3, '2026-06-17T09:00:00', '2026-06-17T09:00:00')
            """
        ),
        {"user_id": user_id},
    )
    db_session.commit()

    response = client.get("/api/works", params={"sort": "recent_read", "pageSize": 3})
    assert response.status_code == 200
    books = response.json()["data"]["books"]
    assert [book["id"] for book in books] == ["work-new", "work-old", "work-unread"]
    assert books[0]["lastReadAt"] == "2026-06-17T09:00:00Z"
    assert books[2]["lastReadAt"] is None

    second_page = client.get(
        "/api/works", params={"sort": "recent_read", "pageSize": 1, "page": 2}
    ).json()
    assert second_page["data"]["books"][0]["id"] == "work-old"

    recent_reading = client.get(
        "/api/dashboard/recent-reading", params={"limit": 10}
    ).json()
    assert [book["id"] for book in recent_reading["data"]["books"]] == [
        "work-new",
        "work-old",
    ]

    continue_item = client.get("/api/dashboard/continue-reading").json()["data"]["item"]
    assert continue_item["workId"] == "work-new"
    assert continue_item["resumeVolumeId"] == "work-new-volume"
    assert continue_item["progress"] == 50

    db_session.execute(
        text(
            "UPDATE LibraryVolume SET hidden = 1 "
            "WHERE mediaVersionId = 'work-new-media'"
        )
    )
    db_session.commit()
    fallback = client.get("/api/dashboard/continue-reading").json()["data"]["item"]
    assert fallback["workId"] == "work-old"
    assert fallback["resumeVolumeId"] == "work-old-volume"


def test_works_sortable_metadata_fields_support_both_directions(client, db_session):
    create_worker_tables(db_session)
    work_columns = {
        row[1]
        for row in db_session.execute(text("PRAGMA table_info(LibraryWork)")).all()
    }
    if "seriesName" not in work_columns:
        db_session.execute(text("ALTER TABLE LibraryWork ADD COLUMN seriesName TEXT"))
    if "seriesIndex" not in work_columns:
        db_session.execute(text("ALTER TABLE LibraryWork ADD COLUMN seriesIndex REAL"))
    edition_columns = {
        row[1]
        for row in db_session.execute(text("PRAGMA table_info(LibraryVolume)")).all()
    }
    if "publisher" not in edition_columns:
        db_session.execute(text("ALTER TABLE LibraryVolume ADD COLUMN publisher TEXT"))
    _login(client, db_session)

    fixtures = [
        ("sort-gamma", "Gamma", "Alice", "Omega", 2, "Zeta Press"),
        ("sort-alpha", "Alpha", "Bob", "Alpha Series", 1, "Alpha Press"),
        ("sort-beta", "Beta", "Charlie", None, None, None),
    ]
    for index, (
        work_id,
        title,
        author,
        series_name,
        series_index,
        publisher,
    ) in enumerate(fixtures):
        db_session.execute(
            text(
                """INSERT INTO LibraryWork (
                    id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                    trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                    seriesName, seriesIndex, mergeKey, createdAt, updatedAt
                ) VALUES (
                    :id, :title, :normalized_title, :author, :normalized_author, 'EPUB', 'UNKNOWN',
                    'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING', 0, 0,
                    :series_name, :series_index, :merge_key, :created_at, :created_at
                )"""
            ),
            {
                "id": work_id,
                "title": title,
                "normalized_title": title.lower(),
                "author": author,
                "normalized_author": author.lower(),
                "series_name": series_name,
                "series_index": series_index,
                "merge_key": f"epub:{work_id}",
                "created_at": f"2026-06-{index + 10:02d}T10:00:00",
            },
        )
        db_session.execute(
            text(
                """INSERT INTO LibraryMediaVersion (
                    id, workId, mediaKind, createdAt, updatedAt
                ) VALUES (
                    :id, :work_id, 'EBOOK', 'now', 'now'
                )"""
            ),
            {"id": f"{work_id}-media", "work_id": work_id},
        )
        db_session.execute(
            text(
                """INSERT INTO LibraryVolume (
                    id, mediaVersionId, origin, title, sortOrder, format, resourceKey,
                    publisher, importStatus, sizeBytes, coverStatus, hidden, createdAt, updatedAt
                ) VALUES (
                    :id, :media_id, 'MANUAL', :title, 0, 'EPUB', :resource_key,
                    :publisher, 'COMPLETED', 10, 'PENDING', 0, 'now', 'now'
                )"""
            ),
            {
                "id": f"{work_id}-volume",
                "media_id": f"{work_id}-media",
                "title": title,
                "resource_key": f"test:{work_id}-volume",
                "publisher": publisher,
            },
        )
    db_session.commit()

    def sorted_ids(sort: str, direction: str):
        payload = client.get(
            "/api/works",
            params={"sort": sort, "sortDirection": direction, "pageSize": 10},
        ).json()
        assert payload["ok"] is True
        return [book["id"] for book in payload["data"]["books"]]

    assert sorted_ids("title", "asc") == ["sort-alpha", "sort-beta", "sort-gamma"]
    assert sorted_ids("title", "desc") == ["sort-gamma", "sort-beta", "sort-alpha"]
    assert sorted_ids("author", "asc") == ["sort-gamma", "sort-alpha", "sort-beta"]
    assert sorted_ids("author", "desc") == ["sort-beta", "sort-alpha", "sort-gamma"]
    assert sorted_ids("publisher", "asc") == ["sort-beta", "sort-alpha", "sort-gamma"]
    assert sorted_ids("publisher", "desc") == ["sort-gamma", "sort-alpha", "sort-beta"]
    assert sorted_ids("series", "asc") == ["sort-beta", "sort-alpha", "sort-gamma"]
    assert sorted_ids("series", "desc") == ["sort-gamma", "sort-alpha", "sort-beta"]


def test_update_work_accepts_empty_numeric_metadata_from_forms(client, db_session):
    create_worker_tables(db_session)
    work_columns = {
        row[1]
        for row in db_session.execute(text("PRAGMA table_info(LibraryWork)")).all()
    }
    if "seriesName" not in work_columns:
        db_session.execute(text("ALTER TABLE LibraryWork ADD COLUMN seriesName TEXT"))
    if "seriesIndex" not in work_columns:
        db_session.execute(text("ALTER TABLE LibraryWork ADD COLUMN seriesIndex REAL"))
    if "publishedYear" not in work_columns:
        db_session.execute(
            text("ALTER TABLE LibraryWork ADD COLUMN publishedYear INTEGER")
        )
    _login(client, db_session)
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                seriesName, seriesIndex, publishedYear, mergeKey, createdAt, updatedAt
            ) VALUES (
                'work-form-numeric', 'Form Numeric', 'formnumeric', 'Author', 'author', 'EPUB', 'UNKNOWN',
                'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING', 0, 0,
                'Series', 3.5, 2024, 'epub:form-numeric:author', '2026-06-10T00:00:00', '2026-06-10T00:00:00'
            )"""
        )
    )
    db_session.commit()

    response = client.patch(
        "/api/works/work-form-numeric", json={"seriesIndex": "", "publishedYear": ""}
    )
    assert response.status_code == 200
    assert response.json()["data"]["book"]["seriesIndex"] is None
    assert response.json()["data"]["book"]["publishedYear"] is None
    row = (
        db_session.execute(
            text(
                "SELECT seriesIndex, publishedYear FROM LibraryWork WHERE id = 'work-form-numeric'"
            )
        )
        .mappings()
        .first()
    )
    assert row["seriesIndex"] is None
    assert row["publishedYear"] is None

    invalid = client.patch(
        "/api/works/work-form-numeric", json={"seriesIndex": "第 3 卷"}
    )
    assert invalid.status_code == 400
    assert "系列序号格式不正确" in invalid.json()["error"]["message"]


def test_bulk_works_delete_records_removes_selected_books(
    client, db_session, test_settings
):
    create_worker_tables(db_session)
    _login(client, db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    managed_file = (
        test_settings.resolved_storage_root / "library" / "bulk-delete" / "book.epub"
    )
    managed_file.parent.mkdir(parents=True)
    managed_file.write_bytes(b"bulk")
    source_file = (
        test_settings.resolved_storage_root / "imports" / "bulk-delete-source.epub"
    )
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"source")
    for work_id, title in [
        ("bulk-delete-1", "Bulk Delete One"),
        ("bulk-delete-2", "Bulk Delete Two"),
        ("bulk-keep", "Bulk Keep"),
    ]:
        db_session.execute(
            text(
                """INSERT INTO LibraryWork (
                    id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                    trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                    mergeKey, createdAt, updatedAt
                ) VALUES (
                    :id, :title, :normalized_title, 'Author', 'author', 'EPUB', 'UNKNOWN',
                    'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING', 0, 0,
                    :merge_key, '2026-06-11T00:00:00', '2026-06-11T00:00:00'
                )"""
            ),
            {
                "id": work_id,
                "title": title,
                "normalized_title": title.lower().replace(" ", ""),
                "merge_key": f"epub:{work_id}:author",
            },
        )
    db_session.execute(
        text(
            """INSERT INTO LibraryMediaVersion (
                id, workId, mediaKind, createdAt, updatedAt
            ) VALUES (
                'bulk-delete-media', 'bulk-delete-1', 'EBOOK',
                '2026-06-11T00:00:00', '2026-06-11T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, mediaVersionId, origin, title, sortOrder, format, resourceKey,
                importStatus, sizeBytes, chapterCount, coverStatus, hidden, createdAt, updatedAt
            ) VALUES (
                'bulk-delete-edition', 'bulk-delete-media', 'MANUAL', 'Default', 0,
                'EPUB', 'test:bulk-delete-edition', 'COMPLETED', 4, 1, 'PENDING',
                0, '2026-06-11T00:00:00', '2026-06-11T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryFile (
                id, volumeId, path, filePathHash, fingerprint, fullHash, hashStatus, mtimeMs,
                kind, mimeType, sizeBytes, sortOrder, createdAt, updatedAt
            ) VALUES (
                'bulk-delete-file', 'bulk-delete-edition', :path, 'bulk-delete-path',
                'bulk-delete-fingerprint', 'bulk-delete-full', 'FAILED', 0, 'EPUB',
                'application/epub+zip', 4, 0, '2026-06-11T00:00:00', '2026-06-11T00:00:00'
            )"""
        ),
        {"path": str(managed_file)},
    )
    db_session.add(
        ImportTask(
            id="bulk-delete-import",
            work_id="bulk-delete-2",
            origin="MANUAL",
            status="COMPLETED",
            original_name=source_file.name,
            source_path=str(source_file),
        )
    )
    db_session.commit()

    response = client.post(
        "/api/works/bulk",
        json={
            "ids": ["bulk-delete-1", "bulk-delete-2"],
            "action": "delete_records",
            "deleteSource": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["deleted"] == 2
    assert payload["data"]["deleteSource"] is True
    assert payload["data"]["deletedFiles"] == 2
    assert payload["data"]["deletedSourceFiles"] == 1
    assert not managed_file.exists()
    assert not source_file.exists()
    remaining = (
        db_session.execute(text("SELECT id FROM LibraryWork ORDER BY id"))
        .scalars()
        .all()
    )
    assert remaining == ["bulk-keep"]


def _create_bulk_management_fixture(db_session):
    create_worker_tables(db_session)
    work_columns = {
        row[1]
        for row in db_session.execute(text("PRAGMA table_info(LibraryWork)")).all()
    }
    edition_columns = {
        row[1]
        for row in db_session.execute(text("PRAGMA table_info(LibraryVolume)")).all()
    }
    for column, statement in [
        ("seriesName", "ALTER TABLE LibraryWork ADD COLUMN seriesName TEXT"),
        ("seriesIndex", "ALTER TABLE LibraryWork ADD COLUMN seriesIndex REAL"),
        ("publishedYear", "ALTER TABLE LibraryWork ADD COLUMN publishedYear INTEGER"),
    ]:
        if column not in work_columns:
            db_session.execute(text(statement))
    for column, statement in [
        ("narrator", "ALTER TABLE LibraryVolume ADD COLUMN narrator TEXT"),
        ("durationMs", "ALTER TABLE LibraryVolume ADD COLUMN durationMs INTEGER"),
    ]:
        if column not in edition_columns:
            db_session.execute(text(statement))
    db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS Shelf (id TEXT PRIMARY KEY, ownerUserId TEXT, name TEXT NOT NULL, description TEXT, kind TEXT NOT NULL DEFAULT 'STATIC', rulesJson TEXT NOT NULL DEFAULT '{}', pinned INTEGER NOT NULL DEFAULT 0, createdAt TEXT, updatedAt TEXT)"
        )
    )
    db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS ShelfWork (shelfId TEXT NOT NULL, workId TEXT NOT NULL, createdAt TEXT, PRIMARY KEY (shelfId, workId))"
        )
    )
    db_session.execute(
        text(
            "INSERT INTO Shelf (id, name, kind, createdAt, updatedAt) VALUES ('bulk-shelf', '批量书架', 'STATIC', 'now', 'now')"
        )
    )
    for index, work_id in enumerate(("bulk-manage-1", "bulk-manage-2"), start=1):
        db_session.execute(
            text(
                """INSERT INTO LibraryWork (
                    id, origin, title, normalizedTitle, author, normalizedAuthor, description, workType,
                    publicationStatus, trackingStatus, tags, metadataQuality, organizeStatus, coverStatus,
                    hidden, organized, mergeKey, createdAt, updatedAt
                ) VALUES (
                    :id, 'MANUAL', :title, :normalized_title, '旧作者', '旧作者', '旧简介', 'EPUB',
                    'UNKNOWN', 'NOT_TRACKING', :tags, 0, 'REVIEWING', 'PENDING', 0, 0,
                    :merge_key, '2026-07-20T00:00:00', '2026-07-20T00:00:00'
                )"""
            ),
            {
                "id": work_id,
                "title": f"Book {index}",
                "normalized_title": f"book{index}",
                "tags": json.dumps(["旧标签", f"保留{index}"], ensure_ascii=False),
                "merge_key": f"book{index}:旧作者",
            },
        )
        db_session.execute(
            text(
                """INSERT INTO LibraryMediaVersion (
                    id, workId, mediaKind, createdAt, updatedAt
                ) VALUES (
                    :id, :work_id, 'EBOOK', '2026-07-20T00:00:00', '2026-07-20T00:00:00'
                )"""
            ),
            {"id": f"{work_id}-media", "work_id": work_id},
        )
        db_session.execute(
            text(
                """INSERT INTO LibraryVolume (
                    id, mediaVersionId, origin, title, sortOrder, format, resourceKey,
                    language, publisher, importStatus, sizeBytes, coverStatus, hidden,
                    createdAt, updatedAt
                ) VALUES (
                    :id, :media_id, 'MANUAL', '旧版本', 0, 'EPUB', :resource_key,
                    'zh-CN', '旧出版社', 'COMPLETED', 0, 'PENDING', 0,
                    '2026-07-20T00:00:00', '2026-07-20T00:00:00'
                )"""
            ),
            {
                "id": f"{work_id}-edition",
                "media_id": f"{work_id}-media",
                "resource_key": f"test:{work_id}-edition",
            },
        )
    db_session.commit()


def test_bulk_management_updates_metadata_shelves_and_find_replace(client, db_session):
    _create_bulk_management_fixture(db_session)
    _login(client, db_session)
    owner_id = db_session.query(User).filter(User.email == "admin@example.com").one().id
    db_session.execute(
        text("UPDATE Shelf SET ownerUserId = :owner_id WHERE id = 'bulk-shelf'"),
        {"owner_id": owner_id},
    )
    db_session.commit()
    ids = ["bulk-manage-1", "bulk-manage-2"]

    metadata = client.post(
        "/api/works/bulk",
        json={
            "ids": ids,
            "action": "update_metadata",
            "fields": {
                "author": "新作者",
                "seriesName": "新系列",
            },
            "addTags": ["新标签"],
            "removeTags": ["旧标签"],
        },
    )
    assert metadata.status_code == 200
    assert metadata.json()["data"]["updated"] == 2
    works = (
        db_session.execute(
            text("SELECT author, seriesName, tags FROM LibraryWork ORDER BY id")
        )
        .mappings()
        .all()
    )
    assert all(
        row["author"] == "新作者" and row["seriesName"] == "新系列" for row in works
    )
    assert all(
        json.loads(row["tags"])[-1] == "新标签"
        and "旧标签" not in json.loads(row["tags"])
        for row in works
    )
    for work_id in ids:
        volume_response = client.patch(
            f"/api/works/{work_id}/volumes/{work_id}-edition",
            json={"publisher": "新出版社"},
        )
        assert volume_response.status_code == 200
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryVolume WHERE publisher = '新出版社'")
        ).scalar()
        == 2
    )

    added = client.post(
        "/api/works/bulk",
        json={
            "ids": ids,
            "action": "shelf_membership",
            "membership": "ADD",
            "shelfId": "bulk-shelf",
        },
    )
    assert added.status_code == 200
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM ShelfWork WHERE shelfId = 'bulk-shelf'")
        ).scalar()
        == 2
    )
    removed = client.post(
        "/api/works/bulk",
        json={
            "ids": [ids[0]],
            "action": "shelf_membership",
            "membership": "REMOVE",
            "shelfId": "bulk-shelf",
        },
    )
    assert removed.status_code == 200
    assert db_session.execute(text("SELECT workId FROM ShelfWork")).scalar() == ids[1]

    replacement_payload = {
        "ids": ids,
        "field": "title",
        "find": "Book",
        "replacement": "卷{{ number }}-{{ match|upper }}",
        "startNumber": 3,
        "caseSensitive": False,
        "regex": False,
    }
    preview = client.post(
        "/api/works/bulk/find-replace/preview", json=replacement_payload
    )
    assert preview.status_code == 200
    assert preview.json()["data"]["changedWorks"] == 2
    assert preview.json()["data"]["items"][0]["after"] == "卷3-BOOK 1"
    applied = client.post(
        "/api/works/bulk", json={**replacement_payload, "action": "find_replace"}
    )
    assert applied.status_code == 200
    assert db_session.execute(
        text("SELECT title FROM LibraryWork ORDER BY id")
    ).scalars().all() == ["卷3-BOOK 1", "卷4-BOOK 2"]

    invalid = client.post(
        "/api/works/bulk/find-replace/preview",
        json={**replacement_payload, "replacement": "{{ unsafe }}"},
    )
    assert invalid.status_code == 400
    assert "不支持的模板变量" in invalid.json()["error"]["message"]


def test_bulk_cover_crop_compress_replace_and_regenerate(
    client, db_session, test_settings
):
    _create_bulk_management_fixture(db_session)
    _login(client, db_session)
    source_dir = test_settings.resolved_storage_root / "covers" / "source"
    source_dir.mkdir(parents=True)
    for work_id, color in (("bulk-manage-1", "#ef4d2f"), ("bulk-manage-2", "#355c7d")):
        source = source_dir / f"{work_id}.png"
        Image.new("RGB", (900, 900), color).save(source)
        db_session.execute(
            text(
                "UPDATE LibraryWork SET coverPath = :path, coverStatus = 'READY' WHERE id = :id"
            ),
            {
                "path": str(source.relative_to(test_settings.resolved_storage_root)),
                "id": work_id,
            },
        )
        db_session.execute(
            text(
                "UPDATE LibraryVolume SET coverPath = :path, coverStatus = 'READY' "
                "WHERE mediaVersionId = :media_id"
            ),
            {
                "path": str(source.relative_to(test_settings.resolved_storage_root)),
                "id": work_id,
                "media_id": f"{work_id}-media",
            },
        )
    db_session.commit()
    ids = json.dumps(["bulk-manage-1", "bulk-manage-2"])

    cropped = client.post(
        "/api/works/bulk/cover",
        data={
            "ids": ids,
            "action": "crop",
            "ratio": "2:3",
            "maxDimension": "1200",
            "quality": "84",
        },
    )
    assert cropped.status_code == 200
    assert cropped.json()["data"]["updated"] == 2
    crop_path = db_session.execute(
        text("SELECT coverPath FROM LibraryWork WHERE id = 'bulk-manage-1'")
    ).scalar()
    with Image.open(test_settings.resolved_storage_root / crop_path) as crop_image:
        assert crop_image.width * 3 == crop_image.height * 2

    compressed = client.post(
        "/api/works/bulk/cover",
        data={"ids": ids, "action": "compress", "maxDimension": "600", "quality": "50"},
    )
    assert compressed.status_code == 200
    compressed_path = db_session.execute(
        text("SELECT coverPath FROM LibraryWork WHERE id = 'bulk-manage-1'")
    ).scalar()
    with Image.open(
        test_settings.resolved_storage_root / compressed_path
    ) as compressed_image:
        assert max(compressed_image.size) <= 600

    replacement = BytesIO()
    Image.new("RGB", (640, 960), "#f6e7cf").save(replacement, format="PNG")
    replaced = client.post(
        "/api/works/bulk/cover",
        data={"ids": ids, "action": "replace", "maxDimension": "1600", "quality": "82"},
        files={"cover": ("replacement.png", replacement.getvalue(), "image/png")},
    )
    assert replaced.status_code == 200
    assert replaced.json()["data"]["updated"] == 2

    regenerated = client.post(
        "/api/works/bulk/cover", data={"ids": ids, "action": "regenerate"}
    )
    assert regenerated.status_code == 200
    regenerated_path = db_session.execute(
        text("SELECT coverPath FROM LibraryWork WHERE id = 'bulk-manage-1'")
    ).scalar()
    assert regenerated_path == "covers/source/bulk-manage-1.png"


def test_delete_work_removes_storage_managed_files_only(
    client, db_session, test_settings
):
    create_worker_tables(db_session)
    _login(client, db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    test_settings.resolved_monitor_root.mkdir(parents=True)
    managed_file = (
        test_settings.resolved_storage_root / "library" / "delete" / "book.epub"
    )
    cover_file = test_settings.resolved_storage_root / "covers" / "delete" / "cover.jpg"
    monitor_file = test_settings.resolved_monitor_root / "original.epub"
    managed_file.parent.mkdir(parents=True)
    cover_file.parent.mkdir(parents=True)
    managed_file.write_bytes(b"managed")
    cover_file.write_bytes(b"cover")
    monitor_file.write_bytes(b"monitor")
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                trackingStatus, tags, metadataQuality, organizeStatus, coverPath, coverStatus, hidden, organized,
                mergeKey, createdAt, updatedAt
            ) VALUES (
                'delete-with-files', 'Delete With Files', 'deletewithfiles', 'Author', 'author', 'EPUB',
                'UNKNOWN', 'NOT_TRACKING', '[]', 0, 'REVIEWING', 'covers/delete/cover.jpg',
                'READY', 0, 0, 'epub:delete-with-files:author',
                '2026-06-11T00:00:00', '2026-06-11T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryMediaVersion (
                id, workId, mediaKind, createdAt, updatedAt
            ) VALUES (
                'delete-media', 'delete-with-files', 'EBOOK',
                '2026-06-11T00:00:00', '2026-06-11T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, mediaVersionId, origin, title, volumeIndex, sortOrder, format,
                resourceKey, importStatus, sizeBytes, chapterCount, coverPath,
                coverStatus, hidden, createdAt, updatedAt
            ) VALUES (
                'delete-volume', 'delete-media', 'MANUAL', 'Default', 1, 0, 'EPUB',
                'test:delete-volume', 'COMPLETED', 7, 1, :cover_path, 'READY', 0,
                '2026-06-11T00:00:00', '2026-06-11T00:00:00'
            )"""
        ),
        {"cover_path": str(cover_file)},
    )
    for file_id, path in [
        ("delete-file-managed", managed_file),
        ("delete-file-monitor", monitor_file),
    ]:
        db_session.execute(
            text(
                """INSERT INTO LibraryFile (
                    id, volumeId, path, filePathHash, fingerprint, fullHash, hashStatus, mtimeMs,
                    kind, mimeType, sizeBytes, sortOrder, createdAt, updatedAt
                ) VALUES (
                    :id, 'delete-volume', :path, :path_hash, :fingerprint, :full_hash,
                    'FAILED', 0, 'EPUB', 'application/epub+zip', 7, 0,
                    '2026-06-11T00:00:00', '2026-06-11T00:00:00'
                )"""
            ),
            {
                "id": file_id,
                "path": str(path),
                "path_hash": f"{file_id}-path",
                "fingerprint": f"{file_id}-fingerprint",
                "full_hash": f"{file_id}-full",
            },
        )
    db_session.commit()

    response = client.delete("/api/works/delete-with-files")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["deleted"] is True
    assert payload["data"]["deletedFiles"] == 2
    assert not managed_file.exists()
    assert not cover_file.exists()
    assert monitor_file.exists()
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryWork WHERE id = 'delete-with-files'")
        ).scalar()
        == 0
    )
    assert (
        db_session.execute(
            text(
                "SELECT COUNT(*) FROM LibraryMediaVersion WHERE workId = 'delete-with-files'"
            )
        ).scalar()
        == 0
    )
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryVolume WHERE id = 'delete-volume'")
        ).scalar()
        == 0
    )
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryFile WHERE volumeId = 'delete-volume'")
        ).scalar()
        == 0
    )


def test_delete_work_can_also_remove_linked_source_files(
    client, db_session, test_settings
):
    create_worker_tables(db_session)
    _login(client, db_session)
    test_settings.resolved_monitor_root.mkdir(parents=True)
    source_file = test_settings.resolved_monitor_root / "delete-source.epub"
    source_file.write_bytes(b"source")
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                mergeKey, createdAt, updatedAt
            ) VALUES (
                'delete-source-work', 'Delete Source', 'deletesource', 'Author', 'author', 'EPUB',
                'UNKNOWN', 'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING', 0, 0,
                'delete-source-work:author', '2026-07-19T00:00:00', '2026-07-19T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO ImportTask (
                id, workId, origin, status, originalName, sourcePath, progress, duplicate, createdAt, updatedAt
            ) VALUES (
                'delete-source-import', 'delete-source-work', 'MANUAL', 'COMPLETED', 'delete-source.epub',
                :source_path, 100, 0, '2026-07-19T00:00:00', '2026-07-19T00:00:00'
            )"""
        ),
        {"source_path": str(source_file)},
    )
    db_session.commit()

    response = client.request(
        "DELETE", "/api/works/delete-source-work", json={"deleteSource": True}
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["deleted"] is True
    assert data["deleteSource"] is True
    assert data["deletedSourceFiles"] == 1
    assert not source_file.exists()


def test_delete_work_preserves_linked_source_inside_storage_by_default(
    client, db_session, test_settings
):
    create_worker_tables(db_session)
    _login(client, db_session)
    source_file = (
        test_settings.resolved_storage_root / "uploads" / "preserved-source.epub"
    )
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"source")
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                mergeKey, createdAt, updatedAt
            ) VALUES (
                'preserve-source-work', 'Preserve Source', 'preservesource', 'Author', 'author', 'EPUB',
                'UNKNOWN', 'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING', 0, 0,
                'preserve-source:author',
                '2026-07-19T00:00:00', '2026-07-19T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryMediaVersion (
                id, workId, mediaKind, createdAt, updatedAt
            ) VALUES (
                'preserve-source-media', 'preserve-source-work', 'EBOOK',
                '2026-07-19T00:00:00', '2026-07-19T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, mediaVersionId, origin, title, sortOrder, format, resourceKey,
                importStatus, sizeBytes, coverStatus, hidden, createdAt, updatedAt
            ) VALUES (
                'preserve-source-edition', 'preserve-source-media', 'MANUAL', 'Default',
                0, 'EPUB', 'test:preserve-source-edition', 'COMPLETED', 6, 'PENDING',
                0, '2026-07-19T00:00:00', '2026-07-19T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryFile (
                id, volumeId, path, hashStatus, mtimeMs, kind, mimeType, sizeBytes,
                sortOrder, createdAt, updatedAt
            ) VALUES (
                'preserve-source-file', 'preserve-source-edition', :source_path, 'FAILED', 0,
                'EPUB', 'application/epub+zip', 6, 0,
                '2026-07-19T00:00:00', '2026-07-19T00:00:00'
            )"""
        ),
        {"source_path": str(source_file)},
    )
    db_session.execute(
        text(
            """INSERT INTO ImportTask (
                id, workId, volumeId, origin, status, originalName, sourcePath,
                progress, duplicate, createdAt, updatedAt
            ) VALUES (
                'preserve-source-import', 'preserve-source-work', 'preserve-source-edition', 'MANUAL',
                'COMPLETED', 'preserved-source.epub', :source_path, 100, 0,
                '2026-07-19T00:00:00', '2026-07-19T00:00:00'
            )"""
        ),
        {"source_path": str(source_file)},
    )
    db_session.commit()

    response = client.delete("/api/works/preserve-source-work")

    assert response.status_code == 200
    assert response.json()["data"]["deletedSourceFiles"] == 0
    assert source_file.exists()
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryWork WHERE id = 'preserve-source-work'")
        ).scalar()
        == 0
    )


def test_delete_import_task_supports_record_source_and_converted_scopes(
    client, db_session, test_settings
):
    create_worker_tables(db_session)
    _login(client, db_session)
    test_settings.resolved_monitor_root.mkdir(parents=True)
    test_settings.conversion_root.mkdir(parents=True)
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, title, normalizedTitle, author, normalizedAuthor, workType,
                publicationStatus, trackingStatus, tags, metadataQuality,
                organizeStatus, coverStatus, hidden, organized, mergeKey,
                createdAt, updatedAt
            ) VALUES (
                'conversion-cleanup-work', 'Conversion Cleanup', 'conversioncleanup',
                'Author', 'author', 'EPUB', 'UNKNOWN', 'NOT_TRACKING', '[]', 0,
                'UNASSESSED', 'PENDING', 0, 0, 'conversion:cleanup',
                '2026-07-19T00:00:00', '2026-07-19T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryMediaVersion (
                id, workId, mediaKind, createdAt, updatedAt
            ) VALUES (
                'conversion-cleanup-media', 'conversion-cleanup-work', 'EBOOK',
                '2026-07-19T00:00:00', '2026-07-19T00:00:00'
            )"""
        )
    )

    paths: dict[str, tuple[Path, Path]] = {}
    for suffix in ["record", "source", "converted"]:
        source = test_settings.resolved_monitor_root / f"{suffix}.azw3"
        output = test_settings.conversion_root / suffix / "book.epub"
        source.write_bytes(b"source")
        output.parent.mkdir(parents=True)
        output.write_bytes(b"converted")
        paths[suffix] = (source, output)
        db_session.execute(
            text(
                """INSERT INTO ImportTask (
                    id, origin, status, originalName, sourcePath, progress, duplicate, createdAt, updatedAt
                ) VALUES (
                    :id, 'MANUAL', 'COMPLETED', :name, :source_path, 100, 0,
                    '2026-07-19T00:00:00', '2026-07-19T00:00:00'
                )"""
            ),
            {"id": f"import-{suffix}", "name": source.name, "source_path": str(source)},
        )
        db_session.execute(
            text(
                """INSERT INTO LibraryVolume (
                    id, mediaVersionId, origin, title, sortOrder, format,
                    resourceKey, importStatus, sizeBytes, coverStatus, hidden,
                    createdAt, updatedAt
                ) VALUES (
                    :id, 'conversion-cleanup-media', 'MANUAL', :title, :sort_order,
                    'AZW3', :resource_key, 'COMPLETED', 6, 'PENDING', 0,
                    '2026-07-19T00:00:00', '2026-07-19T00:00:00'
                )"""
            ),
            {
                "id": f"conversion-source-{suffix}",
                "title": suffix,
                "sort_order": len(paths),
                "resource_key": f"conversion:{suffix}",
            },
        )
        db_session.execute(
            text(
                """INSERT INTO BookConversionTask (
                    id, importTaskId, sourceVolumeId, idempotencyKey,
                    sourceFormat, sourcePath, outputPath, status, updatedAt
                ) VALUES (
                    :id, :task_id, :source_volume_id, :idempotency_key,
                    'AZW3', :source_path, :output_path, 'COMPLETED',
                    '2026-07-19T00:00:00'
                )"""
            ),
            {
                "id": f"conversion-{suffix}",
                "task_id": f"import-{suffix}",
                "source_volume_id": f"conversion-source-{suffix}",
                "idempotency_key": f"conversion-cleanup:{suffix}",
                "source_path": str(source),
                "output_path": str(output),
            },
        )
    sidecar = paths["converted"][1].with_name("normalization.json")
    sidecar.write_text("{}", encoding="utf-8")
    active_source = test_settings.resolved_monitor_root / "active.epub"
    active_source.write_bytes(b"active")
    db_session.execute(
        text(
            """INSERT INTO ImportTask (
                id, origin, status, originalName, sourcePath, progress, duplicate, createdAt, updatedAt
            ) VALUES (
                'import-active', 'MANUAL', 'PARSING', 'active.epub', :source_path, 50, 0,
                '2026-07-19T00:00:00', '2026-07-19T00:00:00'
            )"""
        ),
        {"source_path": str(active_source)},
    )
    db_session.commit()

    record_response = client.request(
        "DELETE", "/api/import-tasks/import-record", json={"deleteMode": "record"}
    )
    assert record_response.status_code == 200
    assert paths["record"][0].exists()
    assert paths["record"][1].exists()

    source_response = client.request(
        "DELETE", "/api/import-tasks/import-source", json={"deleteMode": "source"}
    )
    assert source_response.status_code == 200
    assert not paths["source"][0].exists()
    assert paths["source"][1].exists()

    converted_response = client.request(
        "DELETE", "/api/import-tasks/import-converted", json={"deleteMode": "converted"}
    )
    assert converted_response.status_code == 200
    assert paths["converted"][0].exists()
    assert not paths["converted"][1].exists()
    assert not sidecar.exists()

    active_response = client.request(
        "DELETE", "/api/import-tasks/import-active", json={"deleteMode": "record"}
    )
    assert active_response.status_code == 409
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM ImportTask WHERE id = 'import-active'")
        ).scalar()
        == 1
    )


def test_delete_import_task_only_deletes_its_linked_volume(
    client, db_session, test_settings
):
    create_worker_tables(db_session)
    _login(client, db_session)
    test_settings.resolved_monitor_root.mkdir(parents=True)
    managed_root = (
        test_settings.resolved_storage_root / "library" / "import-delete-linked"
    )
    managed_root.mkdir(parents=True)
    first_source = test_settings.resolved_monitor_root / "linked-first.epub"
    second_source = test_settings.resolved_monitor_root / "linked-second.epub"
    third_source = test_settings.resolved_monitor_root / "linked-third.epub"
    fourth_source = test_settings.resolved_monitor_root / "linked-fourth.epub"
    first_source.write_bytes(b"source-one")
    second_source.write_bytes(b"source-two")
    third_source.write_bytes(b"source-three")
    fourth_source.write_bytes(b"source-four")

    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, title, normalizedTitle, author, normalizedAuthor, workType,
                publicationStatus, trackingStatus, tags, metadataQuality,
                organizeStatus, coverStatus, hidden, organized, mergeKey,
                createdAt, updatedAt
            ) VALUES (
                'linked-delete-work', 'Linked Delete', 'linkeddelete', 'Author',
                'author', 'EPUB', 'UNKNOWN', 'NOT_TRACKING', '[]', 0,
                'REVIEWING', 'PENDING', 0, 0, 'linked-delete:author',
                '2026-07-19T00:00:00', '2026-07-19T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryMediaVersion (
                id, workId, mediaKind, createdAt, updatedAt
            ) VALUES (
                'linked-delete-media', 'linked-delete-work', 'EBOOK',
                '2026-07-19T00:00:00', '2026-07-19T00:00:00'
            )"""
        )
    )
    for index in [1, 2]:
        managed_file = managed_root / f"volume-{index}.epub"
        managed_file.write_bytes(f"managed-{index}".encode())
        db_session.execute(
            text(
                """INSERT INTO LibraryVolume (
                    id, mediaVersionId, origin, title, sortOrder, format, resourceKey,
                    importStatus, sizeBytes, chapterCount, coverStatus, hidden,
                    createdAt, updatedAt
                ) VALUES (
                    :volume_id, 'linked-delete-media', 'MANUAL', :title, :sort_order,
                    'EPUB', :resource_key, 'COMPLETED', 9, 1, 'PENDING', 0,
                    '2026-07-19T00:00:00', '2026-07-19T00:00:00'
                )"""
            ),
            {
                "volume_id": f"linked-volume-{index}",
                "title": f"Volume {index}",
                "sort_order": index - 1,
                "resource_key": f"linked-{index}",
            },
        )
        db_session.execute(
            text(
                """INSERT INTO LibraryFile (
                    id, volumeId, path, hashStatus, mtimeMs, kind, mimeType,
                    sizeBytes, sortOrder, createdAt, updatedAt
                ) VALUES (
                    :file_id, :volume_id, :path, 'FAILED', 0, 'EPUB',
                    'application/epub+zip', 9, 0, '2026-07-19T00:00:00', '2026-07-19T00:00:00'
                )"""
            ),
            {
                "file_id": f"linked-file-{index}",
                "volume_id": f"linked-volume-{index}",
                "path": str(managed_file),
            },
        )
    remaining_volume_file = managed_root / "edition-1-volume-2.epub"
    remaining_volume_file.write_bytes(b"managed-1-volume-2")
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, mediaVersionId, origin, title, sortOrder, format, resourceKey,
                importStatus, sizeBytes, chapterCount, coverStatus, hidden,
                createdAt, updatedAt
            ) VALUES (
                'linked-volume-1b', 'linked-delete-media', 'MANUAL', 'Volume 1B', 2,
                'EPUB', 'linked-1b', 'COMPLETED', 18, 1, 'PENDING', 0,
                '2026-07-19T00:00:00', '2026-07-19T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryFile (
                id, volumeId, path, hashStatus, mtimeMs, kind, mimeType,
                sizeBytes, sortOrder, createdAt, updatedAt
            ) VALUES (
                'linked-file-1b', 'linked-volume-1b', :path, 'FAILED', 0,
                'EPUB', 'application/epub+zip', 18, 1,
                '2026-07-19T00:00:00', '2026-07-19T00:00:00'
            )"""
        ),
        {"path": str(remaining_volume_file)},
    )
    for task_id, source_path, volume_id in [
        ("linked-record-only", first_source, "linked-volume-1"),
        ("linked-delete-volume", second_source, "linked-volume-1"),
        (
            "linked-delete-second-volume",
            third_source,
            "linked-volume-2",
        ),
        (
            "linked-delete-final-volume",
            fourth_source,
            "linked-volume-1b",
        ),
    ]:
        db_session.execute(
            text(
                """INSERT INTO ImportTask (
                    id, workId, volumeId, origin, status, originalName, sourcePath,
                    progress, duplicate, createdAt, updatedAt
                ) VALUES (
                    :task_id, 'linked-delete-work', :volume_id, 'MANUAL',
                    'COMPLETED', :original_name, :source_path, 100, 0,
                    '2026-07-19T00:00:00', '2026-07-19T00:00:00'
                )"""
            ),
            {
                "task_id": task_id,
                "original_name": source_path.name,
                "source_path": str(source_path),
                "volume_id": volume_id,
            },
        )
    db_session.commit()

    record_only = client.request(
        "DELETE", "/api/import-tasks/linked-record-only", json={"deleteMode": "record"}
    )
    assert record_only.status_code == 200
    assert record_only.json()["data"]["deletedLibraryRecord"] is False
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryWork WHERE id = 'linked-delete-work'")
        ).scalar()
        == 1
    )
    assert first_source.exists()

    delete_volume = client.request(
        "DELETE",
        "/api/import-tasks/linked-delete-volume",
        json={"deleteMode": "source", "deleteLibraryRecord": True},
    )
    assert delete_volume.status_code == 200
    data = delete_volume.json()["data"]
    assert data["deletedLibraryRecord"] is True
    assert data["deletedWorkRecord"] is False
    assert data["deletedLibraryDatabaseRecords"] >= 1
    assert data["libraryRecordId"] == "linked-delete-work"
    assert not second_source.exists()
    assert not (managed_root / "volume-1.epub").exists()
    assert remaining_volume_file.exists()
    assert (managed_root / "volume-2.epub").exists()
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryWork WHERE id = 'linked-delete-work'")
        ).scalar()
        == 1
    )
    assert (
        db_session.execute(
            text(
                "SELECT COUNT(*) FROM LibraryMediaVersion WHERE id = 'linked-delete-media'"
            )
        ).scalar()
        == 1
    )
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryVolume WHERE id = 'linked-volume-1'")
        ).scalar()
        == 0
    )
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryVolume WHERE id = 'linked-volume-1b'")
        ).scalar()
        == 1
    )
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryVolume WHERE id = 'linked-volume-2'")
        ).scalar()
        == 1
    )
    delete_final = client.request(
        "DELETE",
        "/api/import-tasks/linked-delete-second-volume",
        json={"deleteMode": "record", "deleteLibraryRecord": True},
    )
    assert delete_final.status_code == 200
    final_data = delete_final.json()["data"]
    assert final_data["deletedLibraryRecord"] is True
    assert final_data["deletedWorkRecord"] is False
    assert not (managed_root / "volume-2.epub").exists()
    assert third_source.exists()
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryWork WHERE id = 'linked-delete-work'")
        ).scalar()
        == 1
    )
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryVolume WHERE id = 'linked-volume-2'")
        ).scalar()
        == 0
    )

    delete_last_volume = client.request(
        "DELETE",
        "/api/import-tasks/linked-delete-final-volume",
        json={"deleteMode": "record", "deleteLibraryRecord": True},
    )
    assert delete_last_volume.status_code == 200
    last_data = delete_last_volume.json()["data"]
    assert last_data["deletedLibraryRecord"] is True
    assert last_data["deletedWorkRecord"] is True
    assert not remaining_volume_file.exists()
    assert fourth_source.exists()
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryWork WHERE id = 'linked-delete-work'")
        ).scalar()
        == 0
    )
    assert (
        db_session.execute(
            text(
                "SELECT COUNT(*) FROM LibraryMediaVersion WHERE workId = 'linked-delete-work'"
            )
        ).scalar()
        == 0
    )


def test_regenerate_cover_uses_first_sorted_volume(client, db_session, test_settings):
    create_worker_tables(db_session)
    _login(client, db_session)
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, monitorFolderId, origin, title, normalizedTitle, author, normalizedAuthor, description,
                workType, publicationStatus, trackingStatus, tags, metadataQuality, organizeStatus,
                coverPath, coverStatus, hidden, organized, mergeKey, createdAt, updatedAt
            ) VALUES (
                'work-cover', NULL, 'MANUAL', '星舰漫画', '星舰漫画', '画师', '画师', NULL,
                'COMIC', 'UNKNOWN', 'NOT_TRACKING', '[]', 0, 'REVIEWING',
                'books/work-cover/comic/volume-2/cover.jpg', 'READY', 0, 0,
                'comic:cover', 'now', 'now'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryMediaVersion (
                id, workId, mediaKind, createdAt, updatedAt
            ) VALUES (
                'comic-media', 'work-cover', 'COMIC', 'now', 'now'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, mediaVersionId, origin, title, volumeIndex, sortOrder, format,
                resourceKey, importStatus, sizeBytes, pageCount, coverPath,
                coverStatus, hidden, createdAt, updatedAt
            ) VALUES
                ('volume-2', 'comic-media', 'MANUAL', '第 2 卷', 2, 2000, 'COMIC',
                 'comic:2', 'COMPLETED', 0, 2, 'books/work-cover/comic/volume-2/cover.jpg',
                 'READY', 0, 'now', 'now'),
                ('volume-1', 'comic-media', 'MANUAL', '第 1 卷', 1, 1000, 'COMIC',
                 'comic:1', 'COMPLETED', 0, 2, 'books/work-cover/comic/volume-1/cover.jpg',
                 'READY', 0, 'now', 'now')
            """
        )
    )
    db_session.commit()
    for volume_id in ("volume-1", "volume-2"):
        cover = (
            test_settings.resolved_storage_root
            / "books"
            / "work-cover"
            / "comic"
            / volume_id
            / "cover.jpg"
        )
        cover.parent.mkdir(parents=True, exist_ok=True)
        cover.write_bytes(b"cover")
    before_detail = client.get("/api/works/work-cover")
    assert before_detail.status_code == 200
    before_cover_url = before_detail.json()["data"]["book"]["coverUrl"]

    response = client.post("/api/works/work-cover/cover/regenerate")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert (
        db_session.execute(
            text("SELECT coverPath FROM LibraryWork WHERE id = 'work-cover'")
        ).scalar()
        == "books/work-cover/comic/volume-1/cover.jpg"
    )
    after_detail = client.get("/api/works/work-cover")
    assert after_detail.status_code == 200
    after_cover_url = after_detail.json()["data"]["book"]["coverUrl"]
    assert after_cover_url.startswith("/api/works/work-cover/cover?size=medium&v=")
    assert after_cover_url != before_cover_url


def test_cover_endpoints_serve_default_without_mutating_existing_entries(
    client, db_session, test_settings
):
    create_worker_tables(db_session)
    _login(client, db_session)
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, origin, title, normalizedTitle, author, normalizedAuthor, workType,
                publicationStatus, trackingStatus, tags, metadataQuality, organizeStatus, coverStatus,
                hidden, organized, mergeKey, createdAt, updatedAt
            ) VALUES (
                'work-default', 'MANUAL', '无封面读物', '无封面读物', '未知作者', '未知作者', 'EPUB',
                'UNKNOWN', 'NOT_TRACKING', '[]', 0, 'LOOKUP_PENDING', 'PENDING',
                0, 0, 'default:test', 'now', 'now'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryMediaVersion (
                id, workId, mediaKind, createdAt, updatedAt
            ) VALUES (
                'media-default', 'work-default', 'EBOOK', 'now', 'now'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, mediaVersionId, origin, title, sortOrder, format, resourceKey,
                importStatus, sizeBytes, coverStatus, hidden, createdAt, updatedAt
            ) VALUES (
                'volume-default', 'media-default', 'MANUAL', '正文', 0, 'EPUB',
                'default-volume', 'COMPLETED', 0, 'PENDING', 0, 'now', 'now'
            )"""
        )
    )
    db_session.commit()

    for url in (
        "/api/works/work-default/cover",
        "/api/volumes/volume-default/cover",
    ):
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"

    default_path = "covers/default-book-cover-v1.png"
    assert (
        db_session.execute(
            text("SELECT coverPath FROM LibraryWork WHERE id = 'work-default'")
        ).scalar()
        is None
    )
    assert (
        db_session.execute(
            text("SELECT coverStatus FROM LibraryWork WHERE id = 'work-default'")
        ).scalar()
        == "PENDING"
    )
    assert (
        db_session.execute(
            text("SELECT coverPath FROM LibraryVolume WHERE id = 'volume-default'")
        ).scalar()
        is None
    )
    assert (test_settings.resolved_storage_root / default_path).is_file()

    for url in (
        "/api/works/work-default/cover?size=small",
        "/api/volumes/volume-default/cover?size=small",
    ):
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/webp"
        assert (
            int(response.headers["content-length"])
            == len(response.content)
            <= 50 * 1024
        )
        with Image.open(BytesIO(response.content)) as image:
            assert image.format == "WEBP"

    missing = client.get("/api/works/not-found/cover")
    assert missing.status_code == 404


def test_small_cover_endpoints_compress_cache_and_preserve_other_variants(
    client, db_session, test_settings
):
    create_worker_tables(db_session)
    _login(client, db_session)
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, origin, title, normalizedTitle, author, normalizedAuthor, workType,
                publicationStatus, trackingStatus, tags, metadataQuality, organizeStatus, coverStatus,
                hidden, organized, mergeKey, createdAt, updatedAt
            ) VALUES (
                'work-small-cover', 'MANUAL', 'Small Cover', 'smallcover', 'Author', 'author', 'EPUB',
                'UNKNOWN', 'NOT_TRACKING', '[]', 0, 'REVIEWING', 'READY',
                0, 0, 'small:cover', 'now', 'now'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryMediaVersion (
                id, workId, mediaKind, createdAt, updatedAt
            ) VALUES (
                'media-small-cover', 'work-small-cover', 'EBOOK', 'now', 'now'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, mediaVersionId, origin, title, sortOrder, format, resourceKey,
                importStatus, sizeBytes, coverStatus, hidden, createdAt, updatedAt
            ) VALUES (
                'volume-small-cover', 'media-small-cover', 'MANUAL', '正文', 0,
                'EPUB', 'small-cover-volume', 'COMPLETED', 0, 'READY', 0,
                'now', 'now'
            )"""
        )
    )
    source = test_settings.resolved_storage_root / "covers" / "small-cover-source.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    Image.effect_noise((1200, 1800), 100).convert("RGB").save(source, format="PNG")
    relative = str(source.relative_to(test_settings.resolved_storage_root))
    db_session.execute(
        text("UPDATE LibraryWork SET coverPath = :path WHERE id = 'work-small-cover'"),
        {"path": relative},
    )
    db_session.execute(
        text(
            "UPDATE LibraryVolume SET coverPath = :path WHERE id = 'volume-small-cover'"
        ),
        {"path": relative},
    )
    db_session.commit()

    endpoints = (
        "/api/works/work-small-cover/cover",
        "/api/volumes/volume-small-cover/cover",
    )
    etag = None
    for endpoint in endpoints:
        response = client.get(f"{endpoint}?size=small")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/webp"
        assert (
            int(response.headers["content-length"])
            == len(response.content)
            <= 50 * 1024
        )
        with Image.open(BytesIO(response.content)) as image:
            assert image.format == "WEBP"
            assert image.width * 3 == image.height * 2
            assert max(image.size) <= media_streaming.SMALL_COVER_MAX_DIMENSION
        etag = etag or response.headers["etag"]

    cache_files = list(
        (test_settings.resolved_storage_root / "cache" / "covers").rglob("*.webp")
    )
    assert len(cache_files) == 1
    repeated = client.get(f"{endpoints[0]}?size=small")
    assert repeated.headers["etag"] == etag
    assert (
        len(
            list(
                (test_settings.resolved_storage_root / "cache" / "covers").rglob(
                    "*.webp"
                )
            )
        )
        == 1
    )

    for size in (None, "medium", "large", "unexpected"):
        suffix = "" if size is None else f"?size={size}"
        response = client.get(f"{endpoints[0]}{suffix}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == source.read_bytes()

    Image.new("RGB", (20, 30), "#ef4d2f").save(source, format="PNG")
    updated = client.get(f"{endpoints[0]}?size=small")
    assert updated.headers["etag"] != etag
    with Image.open(BytesIO(updated.content)) as image:
        assert image.size == (20, 30)

    source.write_bytes(b"not an image")
    fallback = client.get(f"{endpoints[0]}?size=small")
    assert fallback.status_code == 200
    assert fallback.headers["content-type"] == "image/webp"
    assert len(fallback.content) <= 50 * 1024
    with Image.open(BytesIO(fallback.content)) as image:
        assert image.format == "WEBP"


def test_organize_jobs_return_frontend_contract(client, db_session):
    create_worker_tables(db_session)
    create_organize_detail_tables(db_session)
    _login(client, db_session)
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                mergeKey, createdAt, updatedAt
            ) VALUES (
                'work-contract', 'Contract Book', 'contractbook', '', '', 'EPUB', 'UNKNOWN', 'NOT_TRACKING',
                '[]', 20, 'REVIEWING', 'PENDING', 0, 0, 'epub:contract:', '2026-06-11T00:00:00', '2026-06-11T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                mergeKey, createdAt, updatedAt
            ) VALUES (
                'work-organized-history', 'Organized History', 'organizedhistory', 'Author', 'author', 'EPUB',
                'UNKNOWN', 'NOT_TRACKING', '[]', 90, 'APPLIED', 'READY', 1, 1,
                'epub:organized-history:author', '2026-06-10T00:00:00', '2026-06-10T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                mergeKey, createdAt, updatedAt
            ) VALUES
                ('work-recognizing-history', 'Recognizing History', 'recognizinghistory', 'Author', 'author', 'EPUB',
                 'UNKNOWN', 'NOT_TRACKING', '[]', 20, 'RUNNING', 'PENDING', 0, 0,
                 'epub:recognizing-history:author', '2026-06-09T00:00:00', '2026-06-09T00:00:00'),
                ('work-waiting-history', 'Waiting History', 'waitinghistory', 'Author', 'author', 'EPUB',
                 'UNKNOWN', 'NOT_TRACKING', '[]', 20, 'LOOKUP_PENDING', 'PENDING', 0, 0,
                 'epub:waiting-history:author', '2026-06-08T00:00:00', '2026-06-08T00:00:00')
            """
        )
    )
    db_session.execute(
        text(
            """INSERT INTO OrganizeJob (
                id, workId, status, issueCodes, summary, createdAt, updatedAt
            ) VALUES (
                'job-contract', 'work-contract', 'REVIEWING', '["MISSING_AUTHOR","SUGGEST_TITLE"]',
                'needs metadata', '2026-06-11T00:00:00', '2026-06-11T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO OrganizeJob (id, workId, status, issueCodes, summary, createdAt, updatedAt) VALUES
                ('job-recognizing-history', 'work-recognizing-history', 'RUNNING', '[]', 'recognizing', '2026-06-09T00:00:00', '2026-06-09T00:00:00'),
                ('job-waiting-history', 'work-waiting-history', 'LOOKUP_PENDING', '[]', 'waiting', '2026-06-08T00:00:00', '2026-06-08T00:00:00')
            """
        )
    )
    db_session.execute(
        text(
            """INSERT INTO OrganizeJob (
                id, workId, status, issueCodes, summary, createdAt, updatedAt
            ) VALUES (
                'job-organized-history', 'work-organized-history', 'APPLIED', '[]',
                'metadata applied', '2026-06-10T00:00:00', '2026-06-10T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO MetadataSuggestion (
                id, jobId, field, currentValue, suggestedValue, source, confidence, reason, status, createdAt, updatedAt
            ) VALUES (
                'suggest-contract', 'job-contract', 'title', '"Contract Book"', '"Better Contract Book"',
                'filename', 0.91, 'clean filename', 'PENDING', '2026-06-11T00:00:00', '2026-06-11T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO DuplicateCandidate (
                id, jobId, targetWorkId, reasons, confidence, suggestedAction, status, createdAt, updatedAt
            ) VALUES (
                'dup-contract', 'job-contract', 'work-other', '["title"]', 0.82,
                'KEEP_SEPARATE', 'PENDING', '2026-06-11T00:00:00', '2026-06-11T00:00:00'
            )"""
        )
    )
    db_session.commit()

    listed = client.get("/api/organize/jobs?pageSize=100")
    assert listed.status_code == 200
    list_payload = listed.json()["data"]
    job = next(item for item in list_payload["jobs"] if item["id"] == "job-contract")
    assert set(list_payload) == {
        "jobs",
        "page",
        "pageSize",
        "total",
        "totalPages",
        "statusCounts",
        "providerNames",
    }
    assert list_payload["page"] == 1
    assert list_payload["pageSize"] == 100
    assert list_payload["total"] == 4
    assert list_payload["totalPages"] == 1
    assert list_payload["statusCounts"] == {
        "SUCCESS": 1,
        "FAILED": 1,
        "RECOGNIZING": 1,
        "WAITING": 1,
    }
    assert list_payload["providerNames"] == {}
    assert set(job) == {
        "id",
        "trigger",
        "statusCategory",
        "issueCodes",
        "reasonCodes",
        "metadataSources",
        "createdAt",
        "updatedAt",
        "book",
    }
    assert job["book"] == {
        "id": "work-contract",
        "title": "Contract Book",
        "author": "未知作者",
        "format": "EPUB",
    }
    assert job["statusCategory"] == "FAILED"
    assert job["metadataSources"] == []
    assert job["issueCodes"] == ["MISSING_AUTHOR", "SUGGEST_TITLE"]
    history_job = next(
        item for item in list_payload["jobs"] if item["id"] == "job-organized-history"
    )
    assert history_job["statusCategory"] == "SUCCESS"
    assert history_job["book"]["id"] == "work-organized-history"
    assert (
        next(
            item
            for item in list_payload["jobs"]
            if item["id"] == "job-recognizing-history"
        )["statusCategory"]
        == "RECOGNIZING"
    )
    assert (
        next(
            item for item in list_payload["jobs"] if item["id"] == "job-waiting-history"
        )["statusCategory"]
        == "WAITING"
    )

    second_page = client.get("/api/organize/jobs?page=2&pageSize=2").json()["data"]
    assert second_page["page"] == 2
    assert second_page["pageSize"] == 2
    assert second_page["total"] == 4
    assert second_page["totalPages"] == 2
    assert [item["id"] for item in second_page["jobs"]] == [
        "job-recognizing-history",
        "job-waiting-history",
    ]

    successful = client.get("/api/organize/jobs?status=SUCCESS&pageSize=2").json()[
        "data"
    ]
    assert successful["total"] == 1
    assert [item["id"] for item in successful["jobs"]] == ["job-organized-history"]

    searched = client.get("/api/organize/jobs?search=Recognizing&pageSize=2").json()[
        "data"
    ]
    assert searched["total"] == 1
    assert [item["id"] for item in searched["jobs"]] == ["job-recognizing-history"]

    searched_reason = client.get(
        "/api/organize/jobs?search=缺少作者&pageSize=2"
    ).json()["data"]
    assert searched_reason["total"] == 1
    assert [item["id"] for item in searched_reason["jobs"]] == ["job-contract"]

    detail = client.get("/api/organize/jobs/job-contract")
    assert detail.status_code == 200
    detail_job = detail.json()["data"]["job"]
    assert detail_job["book"]["title"] == "Contract Book"
    assert "suggestions" not in detail_job
    assert "duplicates" not in detail_job

    recognized = client.post("/api/organize/jobs/job-contract/recognize")
    assert recognized.status_code == 200
    assert recognized.json()["data"]["job"]["statusCategory"] == "WAITING"
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM MetadataSuggestion WHERE jobId = 'job-contract'")
        ).scalar()
        == 0
    )
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM DuplicateCandidate WHERE jobId = 'job-contract'")
        ).scalar()
        == 0
    )

    deleted = client.delete("/api/organize/jobs/job-contract")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM OrganizeJob WHERE id = 'job-contract'")
        ).scalar()
        == 0
    )
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryWork WHERE id = 'work-contract'")
        ).scalar()
        == 1
    )


def test_manual_organize_creation_routes_are_not_exposed(client, db_session):
    _login(client, db_session)
    assert client.post("/api/organize/runs", json={}).status_code == 405
    assert (
        client.post("/api/organize/jobs", json={"workIds": ["work-1"]}).status_code
        == 405
    )


def test_import_tasks_return_logs_summary_and_rescan_contract(client, db_session):
    create_worker_tables(db_session)
    _login(client, db_session)
    db_session.execute(
        text(
            """CREATE TABLE IF NOT EXISTS MonitorFolder (
                id TEXT PRIMARY KEY, name TEXT, rootPath TEXT, enabled BOOLEAN,
                ignorePatterns TEXT, ignoreHidden BOOLEAN, minFileSizeBytes INTEGER, description TEXT,
                createdAt TEXT, updatedAt TEXT
            )"""
        )
    )
    db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS SystemSetting (`key` TEXT PRIMARY KEY, `value` TEXT, `createdAt` TEXT, `updatedAt` TEXT)"
        )
    )
    db_session.execute(
        text(
            """INSERT INTO MonitorFolder (
                id, name, rootPath, enabled, ignoreHidden, minFileSizeBytes, createdAt, updatedAt
            ) VALUES (
                'folder-1', 'Inbox', '/books/inbox', 1, 1, 1024, '2026-06-11T00:00:00', '2026-06-11T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                mergeKey, createdAt, updatedAt
            ) VALUES (
                'work-import', 'Imported Book', 'importedbook', 'Author', 'author', 'EPUB', 'UNKNOWN',
                'NOT_TRACKING', '[]', 80, 'APPLIED', 'READY', 0, 1, 'epub:import:', '2026-06-11T00:00:00', '2026-06-11T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO ImportTask (
                id, monitorFolderId, workId, volumeId, origin, status, originalName, sourcePath,
                contentHash, progress, duplicate, errorSummary, message, createdAt, updatedAt
            ) VALUES (
                'import-1', 'folder-1', 'work-import', 'volume-import', 'WATCH', 'FAILED', 'bad.zip',
                '/books/inbox/bad.zip', 'hash-1', 100, 0,
                'invalid zip archive', '导入失败，详情见错误信息', '2026-06-11T00:00:00', '2026-06-11T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryMediaVersion (
                id, workId, mediaKind, createdAt, updatedAt
            ) VALUES (
                'media-import', 'work-import', 'EBOOK',
                '2026-06-11T00:00:00', '2026-06-11T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, mediaVersionId, origin, title, sortOrder, format, resourceKey,
                importStatus, sizeBytes, coverStatus, hidden, createdAt, updatedAt
            ) VALUES (
                'volume-import', 'media-import', 'WATCH', 'Imported source', 0,
                'TXT', 'import:bad-zip', 'FAILED', 0, 'PENDING', 0,
                '2026-06-11T00:00:00', '2026-06-11T00:00:00'
            )"""
        )
    )
    db_session.execute(
        text(
            "INSERT INTO ImportLog (id, importTaskId, level, message, createdAt) VALUES ('log-1', 'import-1', 'error', 'invalid zip archive', '2026-06-11T00:00:01')"
        )
    )
    db_session.add(
        BookConversionTask(
            id="conversion-1",
            import_task_id="import-1",
            source_volume_id="volume-import",
            idempotency_key="volume-import:hash-1:EPUB",
            source_format="TXT",
            target_format="EPUB",
            source_path="/books/inbox/bad.zip",
            options_json=json.dumps(
                {
                    "preserveOriginal": True,
                    "chapterCount": 6,
                    "detectedAuthor": None,
                    "detectedLanguage": "zh-CN",
                    "detectedTitle": "Converted title",
                    "formattingType": "heuristic",
                    "inputEncoding": "utf-8",
                    "resourceCount": 0,
                }
            ),
        )
    )
    db_session.commit()

    listed = client.get("/api/import-tasks")
    assert listed.status_code == 200
    data = listed.json()["data"]
    task = data["tasks"][0]
    assert data["page"] == 1
    assert data["pageSize"] == 10
    assert data["total"] == 1
    assert data["totalPages"] == 1
    assert data["summary"]["failed"] == 1
    assert task["sourcePath"] == "bad.zip"
    assert "managedFilePath" not in task
    assert (
        task["friendlyError"]
        == "压缩包可能损坏：请重新复制文件或用本地工具测试压缩包。"
    )
    assert task["monitorFolder"]["name"] == "Inbox"
    assert task["book"] == {"id": "work-import", "title": "Imported Book"}
    assert task["logs"][0]["message"] == "invalid zip archive"
    assert task["conversion"]["options"] == {"preserveOriginal": True}

    detail = client.get("/api/import-tasks/import-1")
    assert detail.status_code == 200
    assert isinstance(detail.json()["data"]["task"]["logs"], list)
    assert detail.json()["data"]["task"]["conversion"]["options"] == {
        "preserveOriginal": True
    }

    logs = client.get("/api/import-tasks/import-1/logs?pageSize=1")
    assert logs.status_code == 200
    assert logs.json()["data"]["total"] == 1

    rescan = client.post("/api/import-tasks/rescan")
    assert rescan.status_code == 202
    assert rescan.json()["data"]["requestedAt"]
    assert len(rescan.json()["data"]["jobs"]) == 1


def test_import_tasks_are_server_paginated_with_global_summary(client, db_session):
    create_worker_tables(db_session)
    _login(client, db_session)
    tasks = []
    for index in range(23):
        if index < 12:
            status = "COMPLETED"
        elif index < 17:
            status = "FAILED"
        else:
            status = "PENDING"
        tasks.append(
            {
                "id": f"import-{index:02d}",
                "status": status,
                "source_path": f"/books/import-{index:02d}.epub",
                "duplicate": 1 if status == "COMPLETED" and index % 4 == 0 else 0,
                "created_at": f"2026-07-{index + 1:02d}T00:00:00",
            }
        )
    db_session.execute(
        text(
            """INSERT INTO ImportTask (
                id, origin, status, originalName, sourcePath, progress, duplicate, createdAt, updatedAt
            ) VALUES (
                :id, 'WATCH', :status, :id, :source_path, 100, :duplicate, :created_at, :created_at
            )"""
        ),
        tasks,
    )
    db_session.commit()

    first = client.get("/api/import-tasks")
    assert first.status_code == 200
    first_data = first.json()["data"]
    assert first_data["page"] == 1
    assert first_data["pageSize"] == 10
    assert first_data["total"] == 23
    assert first_data["totalPages"] == 3
    assert [task["id"] for task in first_data["tasks"]] == [
        f"import-{index:02d}" for index in range(22, 12, -1)
    ]
    assert first_data["summary"] == {"completed": 12, "failed": 5}
    assert all("duplicate" not in task for task in first_data["tasks"])

    second = client.get("/api/import-tasks?page=2&pageSize=10")
    assert second.status_code == 200
    second_data = second.json()["data"]
    assert second_data["page"] == 2
    assert [task["id"] for task in second_data["tasks"]] == [
        f"import-{index:02d}" for index in range(12, 2, -1)
    ]
    assert second_data["summary"] == first_data["summary"]

    overflow = client.get("/api/import-tasks?page=99&pageSize=10")
    assert overflow.status_code == 200
    overflow_data = overflow.json()["data"]
    assert overflow_data["page"] == 3
    assert [task["id"] for task in overflow_data["tasks"]] == [
        "import-02",
        "import-01",
        "import-00",
    ]

    failed = client.get(
        "/api/import-tasks", params={"status": "FAILED", "keyword": "import-14"}
    )
    assert failed.status_code == 200
    failed_data = failed.json()["data"]
    assert failed_data["total"] == 1
    assert [task["id"] for task in failed_data["tasks"]] == ["import-14"]

    invalid_status = client.get("/api/import-tasks", params={"status": "DELETED"})
    assert invalid_status.status_code == 400


def test_import_tasks_display_reverse_of_worker_timestamp_id_order(client, db_session):
    create_worker_tables(db_session)
    _login(client, db_session)
    timestamp = 1784731371000
    db_session.execute(
        text(
            """INSERT INTO ImportTask (
                id, origin, status, originalName, sourcePath, progress, duplicate, createdAt, updatedAt
            ) VALUES (
                :id, 'WATCH', 'COMPLETED', :id, :source_path, 100, 0, :created_at, :created_at
            )"""
        ),
        [
            {
                "id": task_id,
                "source_path": f"/books/{task_id}.epub",
                "created_at": timestamp,
            }
            for task_id in ("task-c", "task-a", "task-b")
        ],
    )
    db_session.commit()

    response = client.get("/api/import-tasks")

    assert response.status_code == 200
    tasks = response.json()["data"]["tasks"]
    assert [task["id"] for task in tasks] == ["task-c", "task-b", "task-a"]
    assert {task["createdAt"] for task in tasks} == {"2026-07-22T14:42:51Z"}


def test_monitor_folder_and_system_settings_mutations(
    client, db_session, test_settings, monkeypatch
):
    test_settings.resolved_monitor_root.mkdir(parents=True)
    (test_settings.resolved_monitor_root / "zeta").mkdir()
    (test_settings.resolved_monitor_root / "alpha").mkdir()
    (test_settings.resolved_monitor_root / "book.epub").write_text(
        "demo", encoding="utf-8"
    )
    (test_settings.resolved_monitor_root / "alpha" / "nested").mkdir()
    second_root = test_settings.resolved_monitor_root.parent / "second-inbox"
    second_root.mkdir(parents=True)
    monitor_alias = test_settings.resolved_monitor_root.parent / "monitor-alias"
    monitor_alias.symlink_to(
        test_settings.resolved_monitor_root, target_is_directory=True
    )
    db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS Shelf (id TEXT PRIMARY KEY, ownerUserId TEXT, name TEXT NOT NULL, description TEXT, kind TEXT NOT NULL DEFAULT 'STATIC', rulesJson TEXT NOT NULL DEFAULT '{}', pinned INTEGER NOT NULL DEFAULT 0, createdAt TEXT NOT NULL, updatedAt TEXT NOT NULL)"
        )
    )
    db_session.execute(
        text(
            "INSERT INTO Shelf (id, name, createdAt, updatedAt) VALUES ('auto-shelf', '自动收录', 'now', 'now')"
        )
    )
    db_session.commit()
    _login(client, db_session)

    root_tree = client.get("/api/monitor-folders/tree")
    assert root_tree.status_code == 200
    assert root_tree.json()["data"]["node"]["path"] == "/"
    assert root_tree.json()["data"]["monitorRoot"] is None

    tree = client.get(
        "/api/monitor-folders/tree",
        params={"path": str(test_settings.resolved_monitor_root)},
    )
    assert tree.status_code == 200
    tree_data = tree.json()["data"]
    assert tree_data["monitorRoot"] is None
    assert tree_data["node"]["path"] == str(
        test_settings.resolved_monitor_root.resolve()
    )
    assert [child["name"] for child in tree_data["node"]["children"]] == [
        "alpha",
        "zeta",
    ]

    child_tree = client.get(
        "/api/monitor-folders/tree",
        params={"path": str(test_settings.resolved_monitor_root / "alpha")},
    )
    assert child_tree.status_code == 200
    assert child_tree.json()["data"]["node"]["children"][0]["name"] == "nested"

    alias_tree = client.get(
        "/api/monitor-folders/tree", params={"path": str(monitor_alias)}
    )
    assert alias_tree.status_code == 200
    assert alias_tree.json()["data"]["node"]["path"] == str(
        test_settings.resolved_monitor_root.resolve()
    )

    outside_tree = client.get(
        "/api/monitor-folders/tree", params={"path": str(second_root)}
    )
    assert outside_tree.status_code == 200
    assert outside_tree.json()["data"]["node"]["path"] == str(second_root.resolve())

    missing_tree = client.get(
        "/api/monitor-folders/tree",
        params={"path": str(test_settings.resolved_monitor_root / "missing")},
    )
    assert missing_tree.status_code == 404
    assert missing_tree.json()["ok"] is False

    file_tree = client.get(
        "/api/monitor-folders/tree",
        params={"path": str(test_settings.resolved_monitor_root / "book.epub")},
    )
    assert file_tree.status_code == 400
    assert file_tree.json()["ok"] is False

    created = client.post(
        "/api/monitor-folders",
        json={
            "name": "Inbox",
            "rootPath": str(test_settings.resolved_monitor_root),
            "enabled": True,
        },
    )
    assert created.status_code == 201
    folder_id = created.json()["data"]["folder"]["id"]
    assert created.json()["data"]["folder"]["shelfId"] is None
    assert created.json()["data"]["folder"]["minFileSizeBytes"] == 10240

    retired_shelf_binding = client.put(
        f"/api/monitor-folders/{folder_id}", json={"shelfId": "auto-shelf"}
    )
    assert retired_shelf_binding.status_code == 400
    assert (
        retired_shelf_binding.json()["error"]["code"] == "MONITOR_FOLDER_SHELF_RETIRED"
    )

    duplicate = client.post(
        "/api/monitor-folders",
        json={
            "name": "Duplicate Inbox",
            "rootPath": f"{test_settings.resolved_monitor_root}/",
            "enabled": True,
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["ok"] is False

    symlink_duplicate = client.post(
        "/api/monitor-folders",
        json={"name": "Alias", "rootPath": str(monitor_alias), "enabled": True},
    )
    assert symlink_duplicate.status_code == 409

    empty_path = client.post(
        "/api/monitor-folders", json={"name": "No Path", "rootPath": " "}
    )
    assert empty_path.status_code == 400
    assert empty_path.json()["ok"] is False

    relative_path = client.post(
        "/api/monitor-folders",
        json={"name": "Relative", "rootPath": "books"},
    )
    assert relative_path.status_code == 400
    assert relative_path.json()["error"]["code"] == "MONITOR_FOLDER_PATH_NOT_ABSOLUTE"

    unavailable_path = client.post(
        "/api/monitor-folders",
        json={"name": "Missing", "rootPath": str(second_root / "missing")},
    )
    assert unavailable_path.status_code == 404

    with monkeypatch.context() as scoped:
        scoped.setattr(
            "app.modules.imports.application.monitor_paths.os.access",
            lambda _path, _mode: False,
        )
        unreadable_path = client.post(
            "/api/monitor-folders",
            json={"name": "Unreadable", "rootPath": str(second_root)},
        )
    assert unreadable_path.status_code == 400
    assert unreadable_path.json()["error"]["code"] == "MONITOR_FOLDER_PATH_UNREADABLE"

    second = client.post(
        "/api/monitor-folders",
        json={"name": "Second Inbox", "rootPath": str(second_root), "enabled": True},
    )
    assert second.status_code == 201
    second_folder_id = second.json()["data"]["folder"]["id"]

    collision = client.put(
        f"/api/monitor-folders/{second_folder_id}",
        json={"rootPath": str(test_settings.resolved_monitor_root)},
    )
    assert collision.status_code == 409
    assert collision.json()["ok"] is False

    updated = client.put(f"/api/monitor-folders/{folder_id}", json={"enabled": False})
    assert updated.status_code == 200
    assert updated.json()["data"]["folder"]["enabled"] is False
    assert updated.json()["data"]["folder"]["shelfId"] is None
    assert updated.json()["data"]["folder"]["updatedAt"]

    settings = client.put(
        "/api/system-settings", json={"settings": {"readerTheme": "dark"}}
    )
    assert settings.status_code == 200
    assert settings.json()["data"]["settings"]["readerTheme"] == "dark"


def test_monitor_folder_delete_rolls_back_when_audit_event_fails(
    client,
    db_session,
    test_settings,
    monkeypatch,
):
    from sqlalchemy import select

    from app.bootstrap import system as system_bootstrap
    from app.models.settings import MonitorFolder

    test_settings.resolved_monitor_root.mkdir(parents=True)
    _login(client, db_session)
    created = client.post(
        "/api/monitor-folders",
        json={
            "name": "Rollback Inbox",
            "rootPath": str(test_settings.resolved_monitor_root),
            "enabled": True,
        },
    )
    folder_id = created.json()["data"]["folder"]["id"]

    def fail_event(*_args, **_kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(system_bootstrap, "_record_system_event", fail_event)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        client.delete(f"/api/monitor-folders/{folder_id}")

    assert (
        db_session.scalar(select(MonitorFolder.id).where(MonitorFolder.id == folder_id))
        == folder_id
    )


def test_import_preferences_are_normalized_and_persisted(client, db_session):
    _login(client, db_session)
    response = client.put(
        "/api/system-settings",
        json={
            "settings": {
                "import.stabilityCheck.enabled": False,
                "import.stabilityCheck.seconds": 999,
                "import.autoConvertToEpub": False,
                "import.allowedExtensions": ["EPUB", ".pdf", ".unsupported"],
                "import.ignorePatterns": "  *.tmp  \r\n\r\n草稿*  ",
            }
        },
    )
    assert response.status_code == 200
    saved = response.json()["data"]["settings"]
    assert saved["import.stabilityCheck.enabled"] is False
    assert saved["import.stabilityCheck.seconds"] == 300
    assert saved["import.autoConvertToEpub"] is False
    assert saved["import.allowedExtensions"] == [".epub", ".pdf"]
    assert saved["import.ignorePatterns"] == "*.tmp\n草稿*"

    loaded = client.get("/api/system-settings").json()["data"]["settings"]
    assert loaded["import.allowedExtensions"] == [".epub", ".pdf"]
    assert loaded["import.ignorePatterns"] == "*.tmp\n草稿*"


def test_system_settings_roll_back_when_audit_event_fails(
    client,
    db_session,
    monkeypatch,
):
    from app.modules.system.infrastructure.settings import get_setting
    from app.modules.system.presentation import http as system_http

    _login(client, db_session)

    def fail_event(*_args, **_kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(system_http, "record_system_event", fail_event)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        client.put("/api/system-settings", json={"settings": {"readerTheme": "dark"}})

    assert get_setting(db_session, "readerTheme") is None


def test_application_locale_is_public_validated_and_persisted(client, db_session):
    initial = client.get("/api/app-config")
    assert initial.status_code == 200
    assert initial.json()["data"] == {
        "language": "zh-CN",
        "supportedLocales": ["zh-CN", "en-US"],
    }

    _login(client, db_session)
    saved = client.patch(
        "/api/system-settings", json={"settings": {"language": "en-US"}}
    )
    assert saved.status_code == 200
    assert saved.json()["data"]["settings"]["language"] == "en-US"

    public = client.get("/api/app-config")
    assert public.status_code == 200
    assert public.json()["data"]["language"] == "en-US"

    rejected = client.patch(
        "/api/system-settings", json={"settings": {"language": "fr-FR"}}
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "INVALID_LOCALE"
    assert rejected.json()["error"]["params"]["supportedLocales"] == ["zh-CN", "en-US"]

    loaded = client.get("/api/system-settings")
    assert loaded.json()["data"]["settings"]["language"] == "en-US"


def test_raw_text_detail_exposes_deferred_epub_conversion(
    client, db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    _login(client, db_session)
    client.put(
        "/api/system-settings", json={"settings": {"import.autoConvertToEpub": False}}
    )
    source = tmp_path / "详情页后置转换.txt"
    source.write_text(
        "第一章\n原始文本先入库。\n\n第二章\n随后转换为 EPUB。", encoding="utf-8"
    )
    imported = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=source, origin="MANUAL", original_name=source.name
        ),
    )

    detail = client.get(
        f"/api/works/{imported.work_id}",
        params={"detailTab": "EBOOK", "volumeId": imported.volume_id},
    )
    assert detail.status_code == 200
    raw_media = detail.json()["data"]["book"]["mediaVersions"][0]
    raw_volume = raw_media["volumes"][0]
    assert raw_volume["format"] == "TXT"
    assert detail.json()["data"]["activeMedia"]["primaryAction"] is not None
    ebook_list = client.get("/api/works?type=ebook")
    assert [book["id"] for book in ebook_list.json()["data"]["books"]] == [
        imported.work_id
    ]

    queued = client.post(
        f"/api/works/{imported.work_id}/volumes/{imported.volume_id}/convert"
    )
    assert queued.status_code == 202
    queued_task = queued.json()["data"]["task"]
    completed = process_import_task(
        db_session,
        test_settings,
        ImportTaskContract.model_validate(queued_task).to_dto(),
    )

    converted_detail = client.get(f"/api/works/{imported.work_id}").json()["data"][
        "book"
    ]
    converted_volumes = converted_detail["mediaVersions"][0]["volumes"]
    assert [volume["format"] for volume in converted_volumes] == ["TXT", "EPUB"]
    assert converted_volumes[1]["derivedFromVolumeId"] == imported.volume_id
    assert converted_volumes[1]["id"] == completed.volume_id


def test_scan_selected_directory_reuses_monitor_rules_and_known_import_paths(
    client, db_session, test_settings
):
    create_worker_tables(db_session)
    _login(client, db_session)
    scan_root = test_settings.resolved_monitor_root / "scan-scope"
    selected = scan_root / "selected"
    selected.mkdir(parents=True)
    fresh = selected / "fresh.epub"
    known = selected / "known.epub"
    hidden = selected / ".hidden.epub"
    globally_ignored = selected / "ignore-me.epub"
    disabled_format = selected / "disabled.pdf"
    undersized = selected / "too-small.epub"
    fresh.write_bytes(b"fresh-enough")
    known.write_bytes(b"known-enough")
    hidden.write_bytes(b"hidden")
    globally_ignored.write_bytes(b"ignored")
    disabled_format.write_bytes(b"disabled")
    undersized.write_bytes(b"x")

    created = client.post(
        "/api/monitor-folders",
        json={
            "name": "Scan scope",
            "rootPath": str(scan_root),
            "enabled": True,
            "ignoreHidden": True,
            "minFileSizeBytes": 6,
        },
    )
    assert created.status_code == 201
    assert created.json()["data"]["folder"]["minFileSizeBytes"] == 6
    folder_id = created.json()["data"]["folder"]["id"]
    db_session.execute(
        text(
            "INSERT INTO SystemSetting (`key`, `value`, `createdAt`, `updatedAt`) VALUES "
            "('import.allowedExtensions', :extensions, 'now', 'now'), "
            "('import.ignorePatterns', :patterns, 'now', 'now')"
        ),
        {"extensions": json.dumps([".epub"]), "patterns": "ignore-me.epub"},
    )
    db_session.execute(
        text(
            """INSERT INTO ImportTask (
                id, monitorFolderId, origin, status, originalName, sourcePath,
                progress, duplicate, createdAt, updatedAt
            ) VALUES (
                'known-task', :folder_id, 'WATCH', 'COMPLETED', 'known.epub', :source_path,
                100, 0, '2026-07-20T00:00:00', '2026-07-20T00:00:00'
            )"""
        ),
        {"folder_id": folder_id, "source_path": str(known.resolve())},
    )
    db_session.commit()

    scanned = client.post(
        "/api/import-tasks/scan-directory", json={"path": str(selected)}
    )
    assert scanned.status_code == 202
    data = scanned.json()["data"]
    assert data["created"] is True
    assert data["job"]["status"] == "PENDING"
    runtime = ImportWorkerRuntime(lambda: nullcontext(db_session), test_settings)
    work_item = runtime.claim_work("scan-test", 900)
    assert work_item is not None and work_item.kind == "SCAN_DIRECTORY"
    assert runtime.process_scan(work_item) is True
    job = client.get(f"/api/import-scan-jobs/{data['job']['id']}")
    assert job.status_code == 200
    assert job.json()["data"]["job"]["queuedCount"] == 1
    assert job.json()["data"]["job"]["skippedCount"] == 5
    queued = (
        db_session.execute(
            text("SELECT * FROM ImportTask WHERE sourcePath = :path"),
            {"path": str(fresh.resolve())},
        )
        .mappings()
        .one()
    )
    assert queued["status"] == "PENDING"
    assert queued["monitorFolderId"] == folder_id
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM ImportTask WHERE sourcePath = :path"),
            {"path": str(known.resolve())},
        ).scalar()
        == 1
    )
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM ImportTask WHERE sourcePath = :path"),
            {"path": str(hidden.resolve())},
        ).scalar()
        == 0
    )

    outside = test_settings.resolved_monitor_root / "not-configured"
    outside.mkdir()
    rejected = client.post(
        "/api/import-tasks/scan-directory", json={"path": str(outside)}
    )
    assert rejected.status_code == 400


def test_scan_job_list_cancel_and_resubmit_contract(client, db_session, test_settings):
    create_worker_tables(db_session)
    _login(client, db_session)
    scan_root = test_settings.resolved_monitor_root / "scan-cancel"
    scan_root.mkdir(parents=True)
    created_folder = client.post(
        "/api/monitor-folders",
        json={
            "name": "Cancelable scan",
            "rootPath": str(scan_root),
            "enabled": True,
            "minFileSizeBytes": 0,
        },
    )
    assert created_folder.status_code == 201

    submitted = client.post(
        "/api/import-tasks/scan-directory", json={"path": str(scan_root)}
    )
    assert submitted.status_code == 202
    job_id = submitted.json()["data"]["job"]["id"]
    active = client.get("/api/import-scan-jobs?status=PENDING")
    assert active.status_code == 200
    assert [job["id"] for job in active.json()["data"]["jobs"]] == [job_id]

    cancelled = client.post(f"/api/import-scan-jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["job"]["status"] == "CANCELLED"
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ImportWorkItem)
            .where(ImportWorkItem.scan_job_id == job_id)
        )
        == 0
    )
    resubmitted = client.post(
        "/api/import-tasks/scan-directory", json={"path": str(scan_root)}
    )
    assert resubmitted.status_code == 202
    assert resubmitted.json()["data"]["created"] is True
    assert resubmitted.json()["data"]["job"]["id"] != job_id
    assert client.get("/api/import-scan-jobs?status=unknown").status_code == 400


def test_scan_selected_audiobook_directory_queues_one_directory_bundle(
    client, db_session, test_settings
):
    create_worker_tables(db_session)
    _login(client, db_session)
    scan_root = test_settings.resolved_monitor_root / "有声书"
    selected = scan_root / "鬼吹灯I-2-龙岭迷窟 (全42集)"
    selected.mkdir(parents=True)
    tracks = [
        selected / "28. 龙岭迷窟 28.mp3",
        selected / "40. 龙岭迷窟 40.mp3",
        selected / "41. 龙岭迷窟 41.mp3",
    ]
    for index, track in enumerate(tracks, start=1):
        track.write_bytes(f"track-{index}".encode())

    created = client.post(
        "/api/monitor-folders",
        json={
            "name": "Audiobooks",
            "rootPath": str(scan_root),
            "enabled": True,
            "minFileSizeBytes": 0,
        },
    )
    assert created.status_code == 201
    folder_id = created.json()["data"]["folder"]["id"]
    for index, track in enumerate(tracks, start=1):
        db_session.execute(
            text(
                """INSERT INTO ImportTask (
                    id, monitorFolderId, origin, status, originalName, sourcePath,
                    progress, duplicate, createdAt, updatedAt
                ) VALUES (
                    :id, :folder_id, 'WATCH', 'COMPLETED', :original_name, :source_path,
                    100, 0, '2026-07-24T00:00:00', '2026-07-24T00:00:00'
                )"""
            ),
            {
                "id": f"legacy-audio-{index}",
                "folder_id": folder_id,
                "original_name": track.name,
                "source_path": str(track.resolve()),
            },
        )
    db_session.commit()

    scanned = client.post(
        "/api/import-tasks/scan-directory", json={"path": str(selected)}
    )

    assert scanned.status_code == 202
    data = scanned.json()["data"]
    runtime = ImportWorkerRuntime(lambda: nullcontext(db_session), test_settings)
    work_item = runtime.claim_work("audio-scan-test", 900)
    assert work_item is not None and work_item.kind == "SCAN_DIRECTORY"
    assert runtime.process_scan(work_item) is True
    job = client.get(f"/api/import-scan-jobs/{data['job']['id']}").json()["data"]["job"]
    assert job["filesScanned"] == len(tracks)
    assert job["candidatesFound"] == 1
    assert job["queuedCount"] == 1
    tasks = (
        db_session.execute(
            text(
                "SELECT `sourcePath`, `originalName` FROM `ImportTask` "
                "WHERE `monitorFolderId` = :folder_id AND `status` = 'PENDING'"
            ),
            {"folder_id": folder_id},
        )
        .mappings()
        .all()
    )
    assert [dict(task) for task in tasks] == [
        {
            "sourcePath": str(selected.resolve()),
            "originalName": selected.name,
        }
    ]


def test_system_settings_hide_active_secrets_and_reject_retired_settings(
    client, db_session
):
    _login(client, db_session)
    secrets = {
        "metadata.bangumi.accessToken": "bangumi-secret",
        "metadata.ai.apiKey": "ai-secret",
    }

    saved = client.put("/api/system-settings", json={"settings": secrets})
    assert saved.status_code == 200
    saved_settings = saved.json()["data"]["settings"]
    for key, secret in secrets.items():
        assert key not in saved_settings
        assert saved_settings[f"{key}Configured"] is True
        assert secret not in saved.text

    loaded = client.get("/api/system-settings")
    assert loaded.status_code == 200
    loaded_settings = loaded.json()["data"]["settings"]
    for key, secret in secrets.items():
        assert key not in loaded_settings
        assert loaded_settings[f"{key}Configured"] is True
        assert secret not in loaded.text

    cleared_key = "metadata.ai.apiKey"
    cleared = client.patch(
        "/api/system-settings",
        json={"settings": {}, "clearSensitiveKeys": [cleared_key]},
    )
    assert cleared.status_code == 200
    assert cleared.json()["data"]["settings"][f"{cleared_key}Configured"] is False
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM SystemSetting WHERE `key` = :key"),
            {"key": cleared_key},
        ).scalar()
        == 0
    )

    reloaded = client.get("/api/system-settings").json()["data"]["settings"]
    assert reloaded[f"{cleared_key}Configured"] is False

    retired = client.put(
        "/api/system-settings",
        json={
            "settings": {
                "systemName": "自定义书房",
                "metadata.douban.apiKey": "removed-secret",
                "download.qbittorrent.password": "removed-secret",
            }
        },
    )
    assert retired.status_code == 400
    assert set(retired.json()["error"]["details"]["keys"]) == {
        "systemName",
        "metadata.douban.apiKey",
        "download.qbittorrent.password",
    }
    assert "removed-secret" not in retired.text


def test_management_overview_events_and_folders(client, db_session, test_settings):
    test_settings.resolved_monitor_root.mkdir(parents=True)
    (test_settings.resolved_monitor_root / "incoming.epub").write_text(
        "demo", encoding="utf-8"
    )
    _login(client, db_session)

    created = client.post(
        "/api/monitor-folders",
        json={
            "name": "Inbox",
            "rootPath": str(test_settings.resolved_monitor_root),
            "enabled": True,
        },
    )
    assert created.status_code == 201

    db_session.execute(
        text(
            "INSERT INTO SystemEvent (id, level, source, actorType, action, targetType, targetId, message, metadata, createdAt) "
            "VALUES ('event-1', 'warning', 'import', 'system', 'failed', 'importTask', 'task-1', '导入失败', '{\"reason\":\"bad file\"}', CURRENT_TIMESTAMP)"
        )
    )
    db_session.commit()

    overview = client.get("/api/management/overview")
    assert overview.status_code == 200
    assert overview.json()["data"]["cards"]["eventLogMaxBytes"] == 5 * 1024 * 1024

    events = client.get("/api/management/events?level=warning&source=import")
    assert events.status_code == 200
    assert events.json()["data"]["events"][0]["message"] == "导入失败"
    assert events.json()["data"]["events"][0]["metadata"]["reason"] == "bad file"

    future_events = client.get(
        "/api/management/events", params={"dateFrom": "2099-01-01"}
    )
    assert future_events.status_code == 200
    assert future_events.json()["data"]["events"] == []

    historical_events = client.get(
        "/api/management/events", params={"dateTo": "2000-01-01"}
    )
    assert historical_events.status_code == 200
    assert historical_events.json()["data"]["events"] == []

    folders = client.get("/api/management/folders")
    assert folders.status_code == 200
    assert folders.json()["data"]["disk"]["sources"][0]["name"] == "Inbox"
    assert folders.json()["data"]["disk"]["sources"][0]["readable"] is True


def test_monitor_folder_create_ignores_retired_import_mode(
    client, db_session, test_settings, monkeypatch
):
    from app.modules.imports.application import monitor_paths

    test_settings.resolved_monitor_root.mkdir(parents=True)
    _login(client, db_session)
    monkeypatch.setattr(
        monitor_paths.os,
        "access",
        lambda _path, mode: mode != monitor_paths.os.W_OK,
    )

    created = client.post(
        "/api/monitor-folders",
        json={
            "name": "Read Only Inbox",
            "rootPath": str(test_settings.resolved_monitor_root),
            "enabled": True,
            "importMode": "MOVE",
        },
    )

    assert created.status_code == 201
    assert created.json()["data"]["folder"]["rootPath"] == str(
        test_settings.resolved_monitor_root
    )
    assert "importMode" not in created.json()["data"]["folder"]


@pytest.mark.skip(reason="旧版外部来源已退出公开 API；底层解析器仅保留历史任务兼容")
def test_source_manual_and_http_providers_execute_search_and_save_records(
    client, db_session
):
    create_source_tables(db_session)
    _login(client, db_session)

    manual = client.post(
        "/api/sources",
        json={
            "name": "Manual shelf",
            "kind": "mixed",
            "providerType": "manual",
            "config": {
                "items": [
                    {
                        "externalId": "m-1",
                        "title": "Star Manual",
                        "author": "Guide",
                        "format": "EPUB",
                    },
                    {"externalId": "m-2", "title": "Other Book", "author": "Guide"},
                ]
            },
        },
    )
    assert manual.status_code == 201
    manual_id = manual.json()["data"]["source"]["id"]

    tested = client.post(f"/api/sources/{manual_id}/test")
    assert tested.status_code == 200
    assert tested.json()["data"]["result"]["status"] == "ok"
    assert "可搜索 2 条" in tested.json()["data"]["result"]["message"]

    searched = client.post(
        f"/api/sources/{manual_id}/search",
        json={"keyword": "star", "saveResults": True},
    )
    assert searched.status_code == 200
    search_data = searched.json()["data"]
    assert search_data["provider"]["providerType"] == "manual"
    assert len(search_data["results"]) == 1
    assert search_data["results"][0]["externalId"] == "m-1"
    assert search_data["records"][0]["status"] == "saved"

    repeated = client.post(
        f"/api/sources/{manual_id}/search",
        json={"keyword": "star", "saveResults": True},
    )
    assert repeated.status_code == 200
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM SourceSearchRecord WHERE sourceId = :source_id"),
            {"source_id": manual_id},
        ).scalar()
        == 1
    )

    saved_again = client.post(
        "/api/source-search-records",
        json={**search_data["results"][0], "status": "ignored"},
    )
    assert saved_again.status_code == 200
    assert saved_again.json()["data"]["record"]["status"] == "ignored"
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM SourceSearchRecord WHERE sourceId = :source_id"),
            {"source_id": manual_id},
        ).scalar()
        == 1
    )

    http_source = client.post(
        "/api/sources",
        json={
            "name": "HTTP shelf",
            "providerType": "http",
            "config": {
                "items": [
                    {
                        "externalId": "h-1",
                        "title": "Space PDF",
                        "downloadUrl": "https://example.com/space.pdf",
                        "format": "PDF",
                    },
                    {
                        "externalId": "h-2",
                        "title": "Bad URL",
                        "downloadUrl": "ftp://example.com/bad.pdf",
                    },
                ]
            },
        },
    )
    assert http_source.status_code == 201
    http_id = http_source.json()["data"]["source"]["id"]

    http_test = client.post(f"/api/sources/{http_id}/test")
    assert http_test.status_code == 200
    assert http_test.json()["data"]["result"]["status"] == "failed"
    assert "下载地址" in http_test.json()["data"]["result"]["message"]

    http_search = client.post(
        f"/api/sources/{http_id}/search", json={"keyword": "space"}
    )
    assert http_search.status_code == 200
    assert http_search.json()["data"]["results"][0]["downloadMeta"]["type"] == "http"


@pytest.mark.skip(reason="PT RSS 已退出公开来源 API")
def test_pt_rss_provider_search_saves_record_and_creates_download_task(
    client, db_session, tmp_path
):
    create_source_tables(db_session)
    create_download_tables(db_session)
    download_dir = tmp_path / "monitor" / "pt-downloads"
    download_dir.mkdir(parents=True)
    set_default_download_folder(db_session, download_dir)
    _login(client, db_session)
    feed_dir = tmp_path / "rss"
    feed_dir.mkdir()
    (feed_dir / "feed.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Star Volume 01</title>
      <link>http://tracker.example/details/1?passkey=secret&amp;view=full</link>
      <guid>torrent-1</guid>
      <pubDate>Tue, 01 Jan 2030 10:00:00 GMT</pubDate>
      <category>Manga</category>
      <enclosure url="http://tracker.example/download/1.torrent?passkey=secret" type="application/x-bittorrent" length="1234" />
    </item>
    <item>
      <title>Star Skip Volume</title>
      <link>http://tracker.example/details/skip</link>
      <guid>torrent-skip</guid>
      <category>Manga</category>
    </item>
    <item>
      <title>Star Volume Novel</title>
      <link>http://tracker.example/details/novel</link>
      <guid>torrent-novel</guid>
      <category>Novel</category>
    </item>
  </channel>
</rss>
""",
        encoding="utf-8",
    )
    server = serve_directory(feed_dir)
    try:
        source = client.post(
            "/api/sources",
            json={
                "name": "PT feed",
                "providerType": "pt_rss",
                "config": {
                    "rssUrl": f"http://127.0.0.1:{server.server_port}/feed.xml",
                    "keywordInclude": ["Star"],
                    "keywordExclude": ["Skip"],
                    "category": "Manga",
                    "defaultType": "comic",
                },
            },
        )
        assert source.status_code == 201
        source_id = source.json()["data"]["source"]["id"]

        tested = client.post(f"/api/sources/{source_id}/test")
        assert tested.status_code == 200
        test_result = tested.json()["data"]["result"]
        assert test_result["status"] == "ok"
        assert "RSS 可读取" in test_result["message"]
        assert len(test_result["details"]["preview"]) == 3

        searched = client.post(
            f"/api/sources/{source_id}/search",
            json={"keyword": "Star", "saveResults": True},
        )
        assert searched.status_code == 200
        data = searched.json()["data"]
        assert data["provider"]["providerType"] == "pt_rss"
        assert len(data["results"]) == 1
        result = data["results"][0]
        assert result["externalId"] == "torrent-1"
        assert result["format"] == "comic"
        assert (
            result["externalUrl"]
            == "http://tracker.example/details/1?passkey=REDACTED&view=full"
        )
        assert result["downloadAvailable"] is True
        assert result["downloadMeta"]["kind"] == "torrent"
        assert result["downloadMeta"]["downloadUrl"].endswith(
            "/1.torrent?passkey=secret"
        )

        record = data["records"][0]
        assert record["status"] == "saved"
        assert json.loads(record["downloadMeta"])["kind"] == "torrent"

        task_response = client.post(
            f"/api/source-search-records/{record['id']}/create-download-task",
            json={"targetPath": str(download_dir)},
        )
        assert task_response.status_code == 201
        task = task_response.json()["data"]["task"]
        assert task["type"] == "http"
        assert task["sourceId"] == source_id
        assert task["searchRecordId"] == record["id"]
        assert json.loads(task["remoteRef"])["downloadMeta"]["kind"] == "torrent"
    finally:
        server.shutdown()


@pytest.mark.skip(reason="RSS 与漫画 API 已退出公开来源 API")
def test_generic_rss_and_comic_api_providers_create_download_tasks(
    client, db_session, tmp_path
):
    create_source_tables(db_session)
    create_download_tables(db_session)
    download_dir = tmp_path / "monitor" / "generic-downloads"
    download_dir.mkdir(parents=True)
    set_default_download_folder(db_session, download_dir)
    _login(client, db_session)
    feed_dir = tmp_path / "generic-rss"
    feed_dir.mkdir()
    (feed_dir / "feed.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Orbital EPUB Dispatch</title>
      <link>http://example.test/books/orbital</link>
      <guid>rss-book-1</guid>
      <pubDate>Wed, 02 Jan 2030 10:00:00 GMT</pubDate>
      <category>Novel</category>
      <enclosure url="http://example.test/downloads/orbital.epub" type="application/epub+zip" length="4096" />
    </item>
    <item>
      <title>Other Dispatch</title>
      <link>http://example.test/books/other</link>
      <guid>rss-book-2</guid>
      <category>Novel</category>
    </item>
  </channel>
</rss>
""",
        encoding="utf-8",
    )
    server = serve_directory(feed_dir)
    try:
        rss_source = client.post(
            "/api/sources",
            json={
                "name": "Generic RSS",
                "kind": "novel",
                "providerType": "rss",
                "config": {"rssUrl": f"http://127.0.0.1:{server.server_port}/feed.xml"},
            },
        )
        assert rss_source.status_code == 201
        rss_id = rss_source.json()["data"]["source"]["id"]

        rss_test = client.post(f"/api/sources/{rss_id}/test")
        assert rss_test.status_code == 200
        assert rss_test.json()["data"]["result"]["status"] == "ok"

        rss_search = client.post(
            f"/api/sources/{rss_id}/search",
            json={"keyword": "Orbital", "saveResults": True},
        )
        assert rss_search.status_code == 200
        rss_data = rss_search.json()["data"]
        assert rss_data["provider"]["providerType"] == "rss"
        assert rss_data["results"][0]["format"] == "ebook"
        assert rss_data["results"][0]["downloadMeta"]["type"] == "http"
        assert rss_data["results"][0]["downloadMeta"]["downloadUrl"].endswith(
            "/orbital.epub"
        )

        rss_record = rss_data["records"][0]
        rss_task = client.post(
            f"/api/source-search-records/{rss_record['id']}/create-download-task",
            json={"targetPath": str(download_dir)},
        )
        assert rss_task.status_code == 201
        assert rss_task.json()["data"]["task"]["type"] == "http"

        comic_source = client.post(
            "/api/sources",
            json={
                "name": "Comic API",
                "kind": "comic",
                "providerType": "comic_api",
                "config": {
                    "items": [
                        {
                            "id": "comic-1",
                            "title": "Orbital Frames 01",
                            "series": "Orbital Frames",
                            "downloadUrl": "https://example.test/comics/orbital-01.cbz",
                        },
                        {
                            "id": "comic-2",
                            "title": "Quiet Frames",
                            "downloadUrl": "https://example.test/comics/quiet.cbz",
                        },
                    ]
                },
            },
        )
        assert comic_source.status_code == 201
        comic_id = comic_source.json()["data"]["source"]["id"]

        comic_test = client.post(f"/api/sources/{comic_id}/test")
        assert comic_test.status_code == 200
        assert comic_test.json()["data"]["result"]["status"] == "ok"

        comic_search = client.post(
            f"/api/sources/{comic_id}/search",
            json={"keyword": "Orbital", "saveResults": True},
        )
        assert comic_search.status_code == 200
        comic_data = comic_search.json()["data"]
        assert comic_data["provider"]["providerType"] == "comic_api"
        assert comic_data["provider"]["capabilities"]["api"] is True
        assert comic_data["results"][0]["externalId"] == "comic-1"
        assert comic_data["results"][0]["format"] == "comic"
        assert comic_data["results"][0]["downloadMeta"]["downloadUrl"].endswith(
            "/orbital-01.cbz"
        )

        comic_record = comic_data["records"][0]
        comic_task = client.post(
            f"/api/source-search-records/{comic_record['id']}/create-download-task",
            json={"targetPath": str(download_dir)},
        )
        assert comic_task.status_code == 201
        assert comic_task.json()["data"]["task"]["type"] == "http"
    finally:
        server.shutdown()


@pytest.mark.skip(reason="HTTP 来源已退出公开来源 API")
def test_create_download_task_only_queues_without_downloading(
    client, db_session, test_settings, tmp_path
):
    create_source_tables(db_session)
    create_download_tables(db_session)
    download_dir = tmp_path / "monitor" / "queue-downloads"
    download_dir.mkdir(parents=True)
    set_default_download_folder(db_session, download_dir)
    _login(client, db_session)
    source_dir = tmp_path / "queue-source"
    source_dir.mkdir()
    (source_dir / "book.epub").write_bytes(b"queued-book")
    server = serve_directory(source_dir)
    try:
        created = client.post(
            "/api/sources",
            json={
                "name": "HTTP queue source",
                "providerType": "http",
                "config": {
                    "items": [
                        {
                            "externalId": "queue-1",
                            "title": "Queue Book",
                            "downloadUrl": f"http://127.0.0.1:{server.server_port}/book.epub",
                        }
                    ]
                },
            },
        )
        assert created.status_code == 201
        source_id = created.json()["data"]["source"]["id"]

        searched = client.post(
            f"/api/sources/{source_id}/search",
            json={"keyword": "queue", "saveResults": True},
        )
        assert searched.status_code == 200
        record = searched.json()["data"]["records"][0]

        queued = client.post(
            f"/api/source-search-records/{record['id']}/create-download-task",
            json={"targetPath": str(download_dir)},
        )
        assert queued.status_code == 201
        task = queued.json()["data"]["task"]
        assert task["status"] == "queued"
        assert task["type"] == "http"
        assert not download_dir.joinpath("book.epub").exists()
    finally:
        server.shutdown()


@pytest.mark.skip(reason="HTTP 来源已退出公开来源 API")
def test_create_download_from_search_result_checks_monitor_folder_before_saving_record(
    client, db_session, tmp_path
):
    create_source_tables(db_session)
    create_download_tables(db_session)
    _login(client, db_session)

    created = client.post(
        "/api/sources",
        json={
            "name": "HTTP direct queue source",
            "providerType": "http",
            "config": {
                "items": [
                    {
                        "externalId": "direct-1",
                        "title": "Direct Queue Book",
                        "downloadUrl": "https://example.test/direct.epub",
                    }
                ]
            },
        },
    )
    assert created.status_code == 201
    source_id = created.json()["data"]["source"]["id"]

    searched = client.post(
        f"/api/sources/{source_id}/search", json={"keyword": "direct"}
    )
    assert searched.status_code == 200
    result = searched.json()["data"]["results"][0]

    missing_folder = client.post(
        "/api/source-search-records/create-download-task", json=result
    )
    assert missing_folder.status_code == 400
    assert "请选择下载目录" in missing_folder.json()["error"]["message"]
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM SourceSearchRecord WHERE sourceId = :source_id"),
            {"source_id": source_id},
        ).scalar()
        == 1
    )

    download_dir = tmp_path / "monitor" / "direct-downloads"
    download_dir.mkdir(parents=True)
    set_default_download_folder(db_session, download_dir)

    queued = client.post(
        "/api/source-search-records/create-download-task",
        json={**result, "targetPath": str(download_dir)},
    )
    assert queued.status_code == 201
    queued_data = queued.json()["data"]
    assert queued_data["record"]["status"] == "download_created"
    assert queued_data["task"]["searchRecordId"] == queued_data["record"]["id"]
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM SourceSearchRecord WHERE sourceId = :source_id"),
            {"source_id": source_id},
        ).scalar()
        == 1
    )

    repeated = client.post(
        "/api/source-search-records/create-download-task",
        json={**result, "targetPath": str(download_dir)},
    )
    assert repeated.status_code == 200
    assert repeated.json()["data"]["alreadyQueued"] is True
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM SourceSearchRecord WHERE sourceId = :source_id"),
            {"source_id": source_id},
        ).scalar()
        == 1
    )


def test_external_source_capability_is_removed(client, db_session):
    create_source_tables(db_session)
    _login(client, db_session)

    created = client.post(
        "/api/sources",
        json={
            "name": "Retired source",
            "kind": "novel",
            "providerType": "manual",
            "config": {},
        },
    )

    assert created.status_code == 410
    assert created.json()["error"]["message"] == "外部资源功能已移除"
    assert client.get("/api/sources").json()["data"]["sources"] == []


def test_download_task_http_start_downloads_file(
    client, db_session, test_settings, tmp_path
):
    create_download_tables(db_session)
    _download_inbox(test_settings)
    _login(client, db_session)
    source_dir = tmp_path / "http"
    source_dir.mkdir()
    (source_dir / "book.epub").write_bytes(b"downloaded-book")
    server = serve_directory(source_dir)
    try:
        url = f"http://127.0.0.1:{server.server_port}/book.epub"
        created = _post_download_task(
            client,
            test_settings,
            {
                "type": "http",
                "displayName": "book.epub",
                "remoteRef": {"downloadUrl": url},
            },
        )
        assert created.status_code == 201
        task_id = created.json()["data"]["task"]["id"]

        started = client.post(f"/api/download-tasks/{task_id}/start")
        assert started.status_code == 200
        task = started.json()["data"]["task"]
        assert task["status"] == "downloaded"
        assert task["progress"] == 100
        assert task["filePath"].endswith("book.epub")
        assert (
            _download_inbox(test_settings).joinpath("book.epub").read_bytes()
            == b"downloaded-book"
        )
    finally:
        server.shutdown()


def test_download_queue_worker_downloads_and_uses_the_unified_importer(
    client, db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    create_download_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _download_inbox(test_settings)
    _login(client, db_session)
    source_dir = tmp_path / "queue-http"
    source_dir.mkdir()
    write_epub_fixture(source_dir / "queued.epub")
    server = serve_directory(source_dir)
    try:
        created = _post_download_task(
            client,
            test_settings,
            {
                "type": "http",
                "displayName": "queued.epub",
                "remoteRef": {
                    "downloadUrl": f"http://127.0.0.1:{server.server_port}/queued.epub"
                },
            },
        )
        assert created.status_code == 201
        task_id = created.json()["data"]["task"]["id"]

        assert process_next_download_task(db_session, test_settings) is True

        task = (
            db_session.execute(
                text("SELECT * FROM DownloadTask WHERE id = :id"), {"id": task_id}
            )
            .mappings()
            .first()
        )
        assert task["status"] == "importing"
        pending = dict(
            db_session.execute(
                text("SELECT * FROM ImportTask WHERE origin = 'DOWNLOAD'")
            )
            .mappings()
            .one()
        )
        process_import_task(
            db_session,
            test_settings,
            import_task_dto_from_row(pending),
        )
        task = (
            db_session.execute(
                text("SELECT * FROM DownloadTask WHERE id = :id"), {"id": task_id}
            )
            .mappings()
            .first()
        )
        assert task["status"] == "completed"
        assert task["bookId"] is not None
        assert task["filePath"].endswith("queued.epub")
        assert _download_inbox(test_settings).joinpath("queued.epub").exists()
        assert (
            db_session.execute(text("SELECT COUNT(*) FROM LibraryWork")).scalar() == 1
        )
        assert (
            db_session.execute(
                text("SELECT status FROM ImportTask WHERE origin = 'DOWNLOAD'")
            ).scalar()
            == "COMPLETED"
        )
    finally:
        server.shutdown()


def test_download_queue_worker_marks_download_failures(
    client, db_session, test_settings
):
    create_download_tables(db_session)
    _download_inbox(test_settings)
    _login(client, db_session)
    created = _post_download_task(
        client,
        test_settings,
        {
            "type": "http",
            "displayName": "bad.epub",
            "remoteRef": {"downloadUrl": "ftp://example.com/bad.epub"},
        },
    )
    assert created.status_code == 201
    task_id = created.json()["data"]["task"]["id"]

    assert process_next_download_task(db_session, test_settings) is True

    task = (
        db_session.execute(
            text("SELECT status, errorMessage FROM DownloadTask WHERE id = :id"),
            {"id": task_id},
        )
        .mappings()
        .first()
    )
    assert task["status"] == "failed"
    assert "http/https" in task["errorMessage"]


def test_download_task_retry_requeues_cancelled_task(client, db_session, tmp_path):
    create_download_tables(db_session)
    _login(client, db_session)
    download_dir = tmp_path / "monitor" / "retry-downloads"
    download_dir.mkdir(parents=True)
    created = client.post(
        "/api/download-tasks",
        json={
            "type": "http",
            "displayName": "retry.epub",
            "remoteRef": {"downloadUrl": "https://example.com/retry.epub"},
            "targetPath": str(download_dir),
        },
    )
    assert created.status_code == 201
    task_id = created.json()["data"]["task"]["id"]

    cancelled = client.post(f"/api/download-tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["task"]["status"] == "cancelled"

    retried = client.post(f"/api/download-tasks/{task_id}/retry")
    assert retried.status_code == 200
    payload = retried.json()["data"]["task"]
    assert payload["status"] == "queued"
    assert payload["progress"] == 0


def test_download_task_torrent_execution(client, db_session, test_settings, tmp_path):
    create_download_tables(db_session)
    _download_inbox(test_settings)
    _login(client, db_session)
    torrent_dir = tmp_path / "torrent"
    torrent_dir.mkdir()
    (torrent_dir / "book.torrent").write_bytes(b"d8:announce")
    server = serve_directory(torrent_dir)
    try:
        torrent_url = f"http://127.0.0.1:{server.server_port}/book.torrent"
        torrent_task = _post_download_task(
            client,
            test_settings,
            {
                "type": "torrent",
                "displayName": "book",
                "remoteRef": {"torrentUrl": torrent_url, "filename": "book.torrent"},
            },
        )
        assert torrent_task.status_code == 201
        torrent_started = client.post(
            f"/api/download-tasks/{torrent_task.json()['data']['task']['id']}/start"
        )
        assert torrent_started.status_code == 200
        torrent_payload = torrent_started.json()["data"]["task"]
        assert torrent_payload["status"] == "downloaded"
        assert torrent_payload["filePath"].endswith("book.torrent")
        assert (
            _download_inbox(test_settings).joinpath("book.torrent").read_bytes()
            == b"d8:announce"
        )

        magnet_task = _post_download_task(
            client,
            test_settings,
            {
                "type": "torrent",
                "displayName": "magnet-book",
                "remoteRef": {"magnetUrl": "magnet:?xt=urn:btih:abc123"},
            },
        )
        assert magnet_task.status_code == 201
        magnet_started = client.post(
            f"/api/download-tasks/{magnet_task.json()['data']['task']['id']}/start"
        )
        assert magnet_started.status_code == 200
        magnet_payload = magnet_started.json()["data"]["task"]
        assert magnet_payload["status"] == "downloaded"
        assert magnet_payload["filePath"].endswith(".magnet")
        assert "magnet:?xt=urn:btih:abc123" in _download_inbox(test_settings).joinpath(
            "magnet-book.magnet"
        ).read_text(encoding="utf-8")
    finally:
        server.shutdown()


def test_download_task_torrent_submits_to_qbittorrent_when_configured(
    client, db_session, test_settings
):
    create_download_tables(db_session)
    _download_inbox(test_settings)
    _login(client, db_session)
    qbit = serve_qbittorrent_api()
    test_settings.qbittorrent_url = f"http://127.0.0.1:{qbit.server_port}"
    test_settings.qbittorrent_username = "admin"
    test_settings.qbittorrent_password = "secret"
    test_settings.qbittorrent_category = "shuku"
    test_settings.qbittorrent_save_path = "/downloads/books"
    try:
        magnet_task = _post_download_task(
            client,
            test_settings,
            {
                "type": "torrent",
                "displayName": "magnet-book",
                "remoteRef": {"magnetUrl": "magnet:?xt=urn:btih:abc123"},
            },
        )

        assert magnet_task.status_code == 201
        magnet_started = client.post(
            f"/api/download-tasks/{magnet_task.json()['data']['task']['id']}/start"
        )

        assert magnet_started.status_code == 200
        task = magnet_started.json()["data"]["task"]
        assert task["status"] == "downloaded"
        assert task["filePath"].endswith(".qbittorrent.json")
        assert qbit.requests[0]["path"] == "/api/v2/auth/login"
        assert qbit.requests[0]["form"] == {"username": "admin", "password": "secret"}
        assert qbit.requests[1]["path"] == "/api/v2/torrents/add"
        assert qbit.requests[1]["cookie"] == "SID=test-session"
        assert qbit.requests[1]["form"]["urls"] == "magnet:?xt=urn:btih:abc123"
        assert qbit.requests[1]["form"]["category"] == "shuku"
        assert qbit.requests[1]["form"]["savepath"] == "/downloads/books"
        manifest = json.loads(
            _download_inbox(test_settings)
            .joinpath("magnet-book.qbittorrent.json")
            .read_text(encoding="utf-8")
        )
        assert manifest["type"] == "qbittorrent_submission"
        assert manifest["refType"] == "magnetUrl"
        assert manifest["category"] == "shuku"
    finally:
        qbit.shutdown()


def test_download_task_manual_import_is_retired_for_qbittorrent_completion(
    client, db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    create_download_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _download_inbox(test_settings)
    qbit_save = tmp_path / "qbit-completed"
    qbit_save.mkdir()
    test_settings.qbittorrent_save_path = str(qbit_save)
    _login(client, db_session)
    completed = qbit_save / "magnet-book.epub"
    write_epub_fixture(completed)
    manifest = _download_inbox(test_settings) / "magnet-book.qbittorrent.json"
    manifest.write_text(
        json.dumps(
            {
                "type": "qbittorrent_submission",
                "taskId": "task-qbit",
                "title": "magnet-book",
                "refType": "magnetUrl",
                "ref": "magnet:?xt=urn:btih:abc123",
                "savePath": str(qbit_save),
                "expectedName": "magnet-book",
            }
        ),
        encoding="utf-8",
    )

    created = _post_download_task(
        client,
        test_settings,
        {
            "type": "torrent",
            "status": "downloaded",
            "displayName": "magnet-book",
            "filePath": str(manifest),
        },
    )
    assert created.status_code == 201
    task_id = created.json()["data"]["task"]["id"]

    imported = client.post(f"/api/download-tasks/{task_id}/import")

    assert imported.status_code == 400
    assert "监控文件夹自动识别" in imported.json()["error"]["message"]
    assert (
        db_session.execute(
            text("SELECT status FROM DownloadTask WHERE id = :id"), {"id": task_id}
        ).scalar()
        == "downloaded"
    )
    assert db_session.execute(text("SELECT COUNT(*) FROM LibraryWork")).scalar() == 0


def test_download_task_manual_import_is_retired_for_epub(
    client, db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    create_download_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _download_inbox(test_settings)
    _login(client, db_session)
    epub = _download_inbox(test_settings) / "downloaded.epub"
    write_epub_fixture(epub)

    created = _post_download_task(
        client,
        test_settings,
        {
            "type": "http",
            "status": "downloaded",
            "displayName": "downloaded.epub",
            "filePath": str(epub),
        },
    )
    assert created.status_code == 201
    task_id = created.json()["data"]["task"]["id"]

    imported = client.post(f"/api/download-tasks/{task_id}/import")
    assert imported.status_code == 400
    assert "监控文件夹自动识别" in imported.json()["error"]["message"]
    assert (
        db_session.execute(
            text("SELECT status FROM DownloadTask WHERE id = :id"), {"id": task_id}
        ).scalar()
        == "downloaded"
    )
    assert db_session.execute(text("SELECT COUNT(*) FROM LibraryWork")).scalar() == 0


def test_download_task_manual_import_is_retired_for_pdf(
    client, db_session, test_settings
):
    create_worker_tables(db_session)
    create_download_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _download_inbox(test_settings)
    _login(client, db_session)
    pdf = _download_inbox(test_settings) / "downloaded.pdf"
    write_pdf_fixture(pdf)

    created = _post_download_task(
        client,
        test_settings,
        {
            "type": "http",
            "status": "downloaded",
            "displayName": "downloaded.pdf",
            "filePath": str(pdf),
        },
    )
    assert created.status_code == 201
    task_id = created.json()["data"]["task"]["id"]

    imported = client.post(f"/api/download-tasks/{task_id}/import")
    assert imported.status_code == 400
    assert "监控文件夹自动识别" in imported.json()["error"]["message"]
    assert (
        db_session.execute(
            text("SELECT status FROM DownloadTask WHERE id = :id"), {"id": task_id}
        ).scalar()
        == "downloaded"
    )
    assert db_session.execute(text("SELECT COUNT(*) FROM LibraryWork")).scalar() == 0


def test_legacy_organize_suggestion_apply_route_is_removed(client, db_session):
    create_worker_tables(db_session)
    create_organize_detail_tables(db_session)
    _login(client, db_session)
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                mergeKey, createdAt, updatedAt
            ) VALUES (
                'work-1', 'old.pdf', 'oldpdf', '', '', 'PDF', 'UNKNOWN', 'NOT_TRACKING',
                '[]', 0, 'REVIEWING', 'PENDING', 0, 0, 'pdf:old:', 'now', 'now'
            )"""
        )
    )
    db_session.execute(
        text(
            "INSERT INTO OrganizeJob (id, workId, status, issueCodes, createdAt, updatedAt) VALUES ('job-1', 'work-1', 'REVIEWING', '[]', 'now', 'now')"
        )
    )
    db_session.execute(
        text(
            "INSERT INTO MetadataSuggestion (id, jobId, field, currentValue, suggestedValue, source, confidence, reason, status, createdAt, updatedAt) VALUES ('s-title', 'job-1', 'title', 'old.pdf', 'New Title', 'filename', 0.95, 'clean filename', 'PENDING', 'now', 'now')"
        )
    )
    db_session.execute(
        text(
            "INSERT INTO MetadataSuggestion (id, jobId, field, currentValue, suggestedValue, source, confidence, reason, status, createdAt, updatedAt) VALUES ('s-author', 'job-1', 'author', '', 'Author A', 'embedded', 0.90, 'metadata', 'PENDING', 'now', 'now')"
        )
    )
    db_session.commit()

    applied = client.post(
        "/api/organize/jobs/job-1/apply",
        json={"highConfidenceOnly": True, "markOrganized": True},
    )

    assert applied.status_code == 404
    work = (
        db_session.execute(
            text(
                "SELECT title, author, organized, organizeStatus FROM LibraryWork WHERE id = 'work-1'"
            )
        )
        .mappings()
        .first()
    )
    assert dict(work) == {
        "title": "old.pdf",
        "author": "",
        "organized": 0,
        "organizeStatus": "REVIEWING",
    }
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM MetadataSuggestion WHERE status = 'PENDING'")
        ).scalar()
        == 2
    )


def test_legacy_duplicate_candidate_apply_route_is_removed(client, db_session):
    create_worker_tables(db_session)
    _login(client, db_session)

    response = client.post(
        "/api/organize/jobs/removed-job/apply",
        json={"duplicateIds": ["removed-candidate"]},
    )

    assert response.status_code == 404


def test_legacy_organize_duplicate_refresh_route_is_removed(client, db_session):
    create_worker_tables(db_session)
    _login(client, db_session)

    response = client.post("/api/organize/jobs/removed-job/duplicates/refresh")

    assert response.status_code == 404


def test_removed_work_metadata_refresh_route_returns_not_found(client, db_session):
    create_worker_tables(db_session)
    _login(client, db_session)

    response = client.post(
        "/api/works/removed-work/metadata/refresh",
        json={"providers": ["external"]},
    )

    assert response.status_code == 404


def test_ebook_metadata_search_returns_all_douban_crawler_candidates_and_proxy_cover(
    client, db_session
):
    create_worker_tables(db_session)
    create_organize_detail_tables(db_session)
    db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS SystemSetting (`key` TEXT PRIMARY KEY, `value` TEXT, `createdAt` TEXT, `updatedAt` TEXT)"
        )
    )
    douban = serve_douban_crawler_gateway()
    try:
        for key, value in {
            "metadata.douban.enabled": "true",
            "metadata.douban.mode": "crawler",
            "metadata.douban.baseUrl": f"http://127.0.0.1:{douban.server_port}",
            "metadata.douban.userAgent": "ShukuCrawlerTest/1.0",
        }.items():
            db_session.execute(
                text(
                    "INSERT INTO SystemSetting (`key`, `value`, `createdAt`, `updatedAt`) VALUES (:key, :value, 'now', 'now')"
                ),
                {"key": key, "value": value},
            )
        db_session.execute(
            text(
                """INSERT INTO LibraryWork (
                    id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                    trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                    mergeKey, createdAt, updatedAt
                ) VALUES (
                    'work-douban-search', '活着', '活着', '', '', 'EPUB', 'UNKNOWN',
                    'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING', 0, 0, 'epub:douban-search', 'now', 'now'
                )"""
            )
        )
        db_session.commit()
        _login(client, db_session)

        searched = client.post(
            "/api/works/work-douban-search/metadata/search",
            json={"source": "douban", "query": "活着"},
        )

        assert searched.status_code == 200
        search_payload = searched.json()["data"]
        assert [item["title"] for item in search_payload["candidates"]] == [
            "活着",
            "活着：新版",
        ]
        assert (
            search_payload["candidates"][0]["description"]
            == "这是一本关于生命韧性的小说。"
        )
        assert search_payload["candidates"][0]["coverUrl"].startswith(
            f"http://127.0.0.1:{douban.server_port}/covers/"
        )
        assert search_payload["candidates"][1]["coverUrl"].startswith(
            f"http://127.0.0.1:{douban.server_port}/covers/"
        )
        assert search_payload["candidates"][1]["raw"]["topics"] == []
        assert search_payload["candidates"][1]["raw"]["rating"] == {
            "count": 21,
            "value": 7.9,
        }

        proxied = client.get(
            f"/api/metadata/cover-proxy?url={quote(search_payload['candidates'][0]['coverUrl'], safe='')}"
        )

        assert proxied.status_code == 200
        assert proxied.headers["content-type"] == "image/jpeg"
        assert proxied.content == b"\xff\xd8\xff\xd9"
    finally:
        douban.shutdown()


def test_metadata_cover_proxy_rejects_unconfigured_private_network_targets(
    client, db_session
):
    _login(client, db_session)

    response = client.get(
        "/api/metadata/cover-proxy",
        params={"url": "http://127.0.0.1:8080/internal-cover.jpg"},
    )

    assert response.status_code == 400
    assert response.json()["ok"] is False


def test_ebook_metadata_search_and_apply_can_use_bangumi_without_suggestion_refresh(
    client, db_session
):
    create_worker_tables(db_session)
    create_organize_detail_tables(db_session)
    db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS SystemSetting (`key` TEXT PRIMARY KEY, `value` TEXT, `createdAt` TEXT, `updatedAt` TEXT)"
        )
    )
    bangumi = serve_bangumi_api_gateway()
    try:
        for key, value in {
            "metadata.bangumi.enabled": "true",
            "metadata.bangumi.baseUrl": f"http://127.0.0.1:{bangumi.server_port}",
            "metadata.bangumi.userAgent": "ShukuEbookTest/1.0",
        }.items():
            db_session.execute(
                text(
                    "INSERT INTO SystemSetting (`key`, `value`, `createdAt`, `updatedAt`) VALUES (:key, :value, 'now', 'now')"
                ),
                {"key": key, "value": value},
            )
        db_session.execute(
            text(
                """INSERT INTO LibraryWork (
                    id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                    trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                    mergeKey, createdAt, updatedAt
                ) VALUES (
                    'work-ebook-bangumi', 'Messy Ebook', 'messyebook', '', '', 'EPUB', 'UNKNOWN',
                    'NOT_TRACKING', '[]', 0, 'REVIEWING', 'PENDING', 0, 0, 'epub:bangumi', 'now', 'now'
                )"""
            )
        )
        db_session.execute(
            text(
                """INSERT INTO LibraryMediaVersion (
                    id, workId, mediaKind, createdAt, updatedAt
                ) VALUES ('media-ebook-bangumi', 'work-ebook-bangumi', 'EBOOK', 'now', 'now')"""
            )
        )
        db_session.execute(
            text(
                """INSERT INTO LibraryVolume (
                    id, mediaVersionId, origin, title, sortOrder, format, resourceKey,
                    importStatus, sizeBytes, coverStatus, hidden, createdAt, updatedAt
                ) VALUES (
                    'volume-ebook-bangumi', 'media-ebook-bangumi', 'MANUAL', '正文', 0,
                    'EPUB', 'bangumi:source', 'COMPLETED', 10, 'PENDING', 0, 'now', 'now'
                )"""
            )
        )
        db_session.commit()
        _login(client, db_session)

        searched = client.post(
            "/api/works/work-ebook-bangumi/metadata/search",
            json={"source": "bangumi", "query": "星舰"},
        )

        assert searched.status_code == 200
        search_payload = searched.json()["data"]
        assert search_payload["candidates"][0]["source"] == "bangumi"
        assert search_payload["candidates"][0]["title"] == "星舰漫画"
        assert search_payload["candidates"][0]["titleAliases"] == [
            "Star Comic",
            "星舰漫画",
            "星舰漫游",
        ]
        assert bangumi.requests[0]["body"] == {
            "keyword": "星舰",
            "sort": "match",
            "filter": {"type": [1]},
        }

        applied = client.post(
            "/api/works/work-ebook-bangumi/metadata/apply",
            json={
                "source": "bangumi",
                "candidate": search_payload["candidates"][0],
                "fields": ["title", "author", "description", "tags"],
            },
        )

        assert applied.status_code == 200, applied.text
        applied_book = applied.json()["data"]["book"]
        assert applied_book["title"] == "星舰漫画"
        assert applied_book["author"] == "漫画作者"
        assert applied_book["tags"] == ["漫画", "科幻"]
        assert applied.json()["data"]["finishedOrganizeJobIds"]
        work_state = (
            db_session.execute(
                text(
                    "SELECT organized, organizeStatus FROM LibraryWork WHERE id = 'work-ebook-bangumi'"
                )
            )
            .mappings()
            .first()
        )
        assert dict(work_state) == {"organized": 1, "organizeStatus": "APPLIED"}
        assert (
            db_session.execute(
                text(
                    "SELECT COUNT(*) FROM OrganizeJob WHERE workId = 'work-ebook-bangumi' AND status IN ('PENDING', 'REVIEWING', 'FAILED')"
                )
            ).scalar()
            == 0
        )
        history = client.get("/api/organize/jobs?pageSize=100")
        applied_history = next(
            job
            for job in history.json()["data"]["jobs"]
            if job["book"]["id"] == "work-ebook-bangumi"
        )
        assert applied_history["statusCategory"] == "SUCCESS"

        refreshed = client.post(
            "/api/works/work-ebook-bangumi/metadata/refresh",
            json={"providers": ["bangumi"]},
        )

        assert refreshed.status_code == 404
        work_state = (
            db_session.execute(
                text(
                    "SELECT organized, organizeStatus FROM LibraryWork WHERE id = 'work-ebook-bangumi'"
                )
            )
            .mappings()
            .first()
        )
        assert dict(work_state) == {"organized": 1, "organizeStatus": "APPLIED"}
        assert (
            db_session.execute(
                text(
                    "SELECT COUNT(*) FROM OrganizeJob WHERE workId = 'work-ebook-bangumi' AND status IN ('PENDING', 'REVIEWING', 'FAILED')"
                )
            ).scalar()
            == 0
        )
        assert (
            db_session.execute(text("SELECT COUNT(*) FROM MetadataSuggestion")).scalar()
            == 0
        )
    finally:
        bangumi.shutdown()


def test_backup_create_download_and_restore_database_export(
    client, db_session, test_settings
):
    Base.metadata.create_all(db_session.get_bind())
    create_worker_tables(db_session)
    apply_schema(db_session.get_bind())
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    stored_file = (
        test_settings.resolved_storage_root
        / "books"
        / "backup-work"
        / "volume-1"
        / "book.epub"
    )
    stored_file.parent.mkdir(parents=True)
    stored_file.write_bytes(b"backup-file-content")
    db_session.execute(
        text(
            """INSERT INTO LibraryWork (
                id, title, normalizedTitle, author, normalizedAuthor, workType, publicationStatus,
                trackingStatus, tags, metadataQuality, organizeStatus, coverStatus, hidden, organized,
                mergeKey, createdAt, updatedAt
            ) VALUES (
                'backup-work', 'Backup Book', 'backupbook', 'Author', 'author', 'EPUB', 'UNKNOWN',
                'NOT_TRACKING', '[]', 80, 'APPLIED', 'PENDING', 0, 1, 'epub:backup:author', 'now', 'now'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryMediaVersion (
                id, workId, mediaKind, createdAt, updatedAt
            ) VALUES (
                'backup-media-version', 'backup-work', 'EBOOK', 'now', 'now'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, mediaVersionId, origin, title, sortOrder, format, resourceKey,
                importStatus, sizeBytes, chapterCount, coverStatus, hidden, createdAt, updatedAt
            ) VALUES (
                'backup-volume', 'backup-media-version', 'MANUAL', '正文', 0, 'EPUB',
                'backup:volume', 'COMPLETED', 19, 1, 'PENDING', 0, 'now', 'now'
            )"""
        )
    )
    db_session.execute(
        text(
            """INSERT INTO LibraryFile (
                id, volumeId, path, filePathHash, hashStatus, mtimeMs, kind, mimeType,
                sizeBytes, sortOrder, createdAt, updatedAt
            ) VALUES (
                'backup-file', 'backup-volume', :path, 'hash', 'PARTIAL_PENDING',
                1, 'EPUB', 'application/epub+zip', 19, 0, 'now', 'now'
            )"""
        ),
        {"path": str(stored_file)},
    )
    db_session.execute(
        text(
            "INSERT INTO SystemSetting (`key`, `value`, `createdAt`, `updatedAt`) VALUES ('backup.scope', :value, 'now', 'now')"
        ),
        {"value": json.dumps({"mode": "manual"})},
    )
    user_id = db_session.execute(
        text("SELECT id FROM User WHERE email = 'admin@example.com'")
    ).scalar()
    db_session.execute(
        text(
            """INSERT INTO ReaderProgressCursor (
                id, userId, workId, clientId, highWater, lastMutationId, createdAt, updatedAt
            ) VALUES (
                'backup-cursor', :user_id, 'backup-work', 'backup-client', 12, 'backup-mutation', 'now', 'now'
            )"""
        ),
        {"user_id": user_id},
    )
    db_session.commit()

    created = client.post("/api/backups")

    assert created.status_code == 201
    backup = created.json()["data"]["backup"]
    assert backup["counts"]["works"] == 1
    assert backup["counts"]["systemSettings"] == 1
    assert backup["counts"]["readerProgressCursors"] == 1
    assert backup["counts"]["libraryFiles"] == 0
    backup_path = test_settings.resolved_storage_root / "backups" / backup["filename"]
    with zipfile.ZipFile(backup_path) as archive:
        names = set(archive.namelist())
        assert {"metadata.json", "database-export.json", "settings.json"}.issubset(
            names
        )
        assert "library-files.json" not in names
        assert all(not name.startswith("library-files/") for name in names)
        metadata = json.loads(archive.read("metadata.json").decode("utf-8"))
        database_export = json.loads(
            archive.read("database-export.json").decode("utf-8")
        )
        settings_export = json.loads(archive.read("settings.json").decode("utf-8"))
        assert metadata["kind"] == "manual"
        assert metadata["counts"]["libraryFiles"] == 0
        assert "reader-content-files" in metadata["excludes"]
        assert database_export["systemSettings"][0]["key"] == "backup.scope"
        assert database_export["readerProgressCursors"][0]["highWater"] == 12
        assert settings_export["backupMode"] == "manual"

    downloaded = client.get(
        f"/api/backups/{backup['id']}/download", headers={"Range": "bytes=0-3"}
    )
    assert downloaded.status_code == 206
    assert downloaded.content == b"PK\x03\x04"

    stored_file.unlink()
    db_session.execute(
        text("DELETE FROM ReaderProgressCursor WHERE id = 'backup-cursor'")
    )
    db_session.execute(text("DELETE FROM LibraryWork WHERE id = 'backup-work'"))
    db_session.commit()
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryWork WHERE id = 'backup-work'")
        ).scalar()
        == 0
    )
    assert not stored_file.exists()

    restored = client.post(f"/api/backups/{backup['id']}/restore")

    assert restored.status_code == 200
    assert restored.json()["data"]["restored"] is True
    assert restored.json()["data"]["restoredCounts"]["works"] == 1
    assert restored.json()["data"]["restoredCounts"]["systemSettings"] == 1
    assert restored.json()["data"]["restoredCounts"]["readerProgressCursors"] == 1
    assert restored.json()["data"]["restoredCounts"]["libraryFiles"] == 0
    assert restored.json()["data"]["actualCounts"]["works"] == 1
    db_session.commit()
    restored_rows = (
        db_session.execute(text("SELECT id, title FROM LibraryWork")).mappings().all()
    )
    assert restored_rows
    assert (
        db_session.execute(
            text("SELECT title FROM LibraryWork WHERE id = 'backup-work'")
        ).scalar()
        == "Backup Book"
    )
    assert db_session.execute(
        text("SELECT `value` FROM SystemSetting WHERE `key` = 'backup.scope'")
    ).scalar() == json.dumps({"mode": "manual"})
    assert (
        db_session.execute(
            text(
                "SELECT highWater FROM ReaderProgressCursor WHERE id = 'backup-cursor'"
            )
        ).scalar()
        == 12
    )
    assert not stored_file.exists()


def test_backup_listing_keeps_legacy_automatic_files_manual_only(
    client, db_session, test_settings
):
    from app.services.backup_service import list_backups

    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    backup_root = test_settings.resolved_storage_root / "backups"
    backup_root.mkdir(parents=True)
    manual_id = "manual-20260612-030000-keepme"
    automatic_id = "automatic-20260612-030000-legacy"
    with zipfile.ZipFile(backup_root / f"{manual_id}.zip", "w") as archive:
        archive.writestr(
            "metadata.json",
            json.dumps(
                {
                    "id": manual_id,
                    "kind": "manual",
                    "app": "ermao-books",
                    "version": 2,
                    "createdAt": "2026-06-12T03:00:00+00:00",
                    "counts": {},
                }
            ),
        )
    with zipfile.ZipFile(backup_root / f"{automatic_id}.zip", "w") as archive:
        archive.writestr(
            "metadata.json",
            json.dumps(
                {
                    "id": automatic_id,
                    "kind": "automatic",
                    "app": "ermao-books",
                    "version": 2,
                    "createdAt": "2026-06-11T03:00:00+00:00",
                    "counts": {},
                }
            ),
        )

    backups = list_backups(test_settings)
    assert {backup["id"] for backup in backups} == {manual_id, automatic_id}

    deleted = client.delete(f"/api/backups/{automatic_id}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True
    assert not (backup_root / f"{automatic_id}.zip").exists()


def test_upload_saves_to_monitored_directory_without_creating_import_task(
    client, db_session, test_settings, tmp_path
):
    from sqlalchemy import func, select

    from app.models.import_pipeline import ImportTask

    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    epub = tmp_path / "manual.epub"
    write_epub_fixture(epub)
    upload_dir = _managed_fixture_dir(test_settings, "uploads")
    monitored = client.post(
        "/api/monitor-folders",
        json={"name": "Upload monitor", "rootPath": str(upload_dir), "enabled": True},
    )
    assert monitored.status_code == 201

    with epub.open("rb") as handle:
        response = client.post(
            "/api/works/import",
            data={"targetPath": str(upload_dir)},
            files={"file": ("manual.epub", handle, "application/epub+zip")},
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["saved"] == 1
    assert payload["autoImport"] is True
    assert payload["results"][0]["monitoringStatus"] == "WATCHING"
    assert Path(payload["results"][0]["sourcePath"]).read_bytes() == epub.read_bytes()
    assert db_session.scalar(select(func.count()).select_from(ImportTask)) == 0

    works = client.get("/api/works")
    assert works.status_code == 200
    assert works.json()["data"]["total"] == 0


def test_upload_to_unmonitored_directory_only_saves_files(
    client, db_session, test_settings, tmp_path
):
    from sqlalchemy import func, select

    from app.models.import_pipeline import ImportTask

    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    epub = tmp_path / "unmonitored.epub"
    write_epub_fixture(epub)
    upload_dir = _managed_fixture_dir(test_settings, "unmonitored-uploads")

    with epub.open("rb") as handle:
        response = client.post(
            "/api/works/import",
            data={"targetPath": str(upload_dir)},
            files={"file": ("unmonitored.epub", handle, "application/epub+zip")},
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["saved"] == 1
    assert payload["autoImport"] is False
    assert payload["results"][0]["monitoringStatus"] == "NOT_MONITORED"
    assert Path(payload["results"][0]["sourcePath"]).read_bytes() == epub.read_bytes()
    assert db_session.scalar(select(func.count()).select_from(ImportTask)) == 0


def test_upload_allows_a_visible_directory_outside_configured_monitor_folders(
    client,
    db_session,
    test_settings,
    tmp_path,
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    epub = tmp_path / "outside.epub"
    write_epub_fixture(epub)
    outside_directory = tmp_path / "outside-monitor-root"
    outside_directory.mkdir()

    with epub.open("rb") as handle:
        response = client.post(
            "/api/works/import",
            data={"targetPath": str(outside_directory)},
            files={"file": ("outside.epub", handle, "application/epub+zip")},
        )

    assert response.status_code == 200
    assert [path.name for path in outside_directory.iterdir()] == ["outside.epub"]


def test_upload_requires_access_to_the_covering_monitor_folder(
    client,
    db_session,
    test_settings,
    tmp_path,
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    upload_dir = _managed_fixture_dir(test_settings, "restricted-uploads")
    monitored = client.post(
        "/api/monitor-folders",
        json={
            "name": "Restricted uploads",
            "rootPath": str(upload_dir),
            "enabled": True,
        },
    )
    assert monitored.status_code == 201
    member = User(
        email="upload-member@example.com",
        name="upload-member",
        password_hash=hash_password("starshipnas"),
        role="member",
    )
    db_session.add(member)
    db_session.commit()
    assert (
        client.post(
            "/api/auth/login",
            json={"email": member.email, "password": "starshipnas"},
        ).status_code
        == 200
    )
    epub = tmp_path / "restricted.epub"
    write_epub_fixture(epub)

    with epub.open("rb") as handle:
        response = client.post(
            "/api/works/import",
            data={"targetPath": str(upload_dir)},
            files={"file": ("restricted.epub", handle, "application/epub+zip")},
        )

    assert response.status_code == 403
    assert list(upload_dir.iterdir()) == []


def test_upload_uses_a_numbered_name_when_the_target_already_exists(
    client,
    db_session,
    test_settings,
    tmp_path,
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    first = tmp_path / "first.epub"
    second = tmp_path / "second.epub"
    write_epub_fixture(first)
    write_epub_fixture(second)
    upload_dir = _managed_fixture_dir(test_settings, "duplicate-uploads")

    with first.open("rb") as first_handle, second.open("rb") as second_handle:
        response = client.post(
            "/api/works/import",
            data={"targetPath": str(upload_dir)},
            files=[
                ("file", ("same.epub", first_handle, "application/epub+zip")),
                ("file", ("same.epub", second_handle, "application/epub+zip")),
            ],
        )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert [item["file"] for item in payload["results"]] == ["same.epub", "same-1.epub"]
    assert (upload_dir / "same.epub").read_bytes() == first.read_bytes()
    assert (upload_dir / "same-1.epub").read_bytes() == second.read_bytes()


def test_upload_rolls_back_files_when_atomic_publication_fails(
    client,
    db_session,
    test_settings,
    tmp_path,
    monkeypatch,
):
    from sqlalchemy import func, select

    from app.models.import_pipeline import ImportTask
    from app.modules.imports.infrastructure.uploaded_file_publication import (
        AtomicUploadedFilePublisher,
    )

    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    first = tmp_path / "first.epub"
    second = tmp_path / "second.epub"
    write_epub_fixture(first)
    write_epub_fixture(second)
    upload_dir = _managed_fixture_dir(test_settings, "atomic-uploads")
    original_copy = AtomicUploadedFilePublisher._copy_stream
    call_count = 0

    def fail_second_copy(source, target, *, max_bytes):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            target.write_bytes(b"partial")
            raise OSError("injected publication failure")
        return original_copy(source, target, max_bytes=max_bytes)

    monkeypatch.setattr(
        AtomicUploadedFilePublisher,
        "_copy_stream",
        staticmethod(fail_second_copy),
    )
    with first.open("rb") as first_handle, second.open("rb") as second_handle:
        response = client.post(
            "/api/works/import",
            data={"targetPath": str(upload_dir)},
            files=[
                ("file", ("first.epub", first_handle, "application/epub+zip")),
                ("file", ("second.epub", second_handle, "application/epub+zip")),
            ],
        )

    assert response.status_code == 500
    assert db_session.scalar(select(func.count()).select_from(ImportTask)) == 0
    assert list(upload_dir.iterdir()) == []


def test_epub_volume_file_and_bootstrap_use_requested_volume(
    client, db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    series_dir = (
        _managed_fixture_dir(test_settings, "epub-series")
        / "[星舰小说][作者甲][Vol.01-Vol.02]"
    )
    series_dir.mkdir()
    first = series_dir / "星舰小说 01.epub"
    second = series_dir / "星舰小说 02.epub"
    write_epub_fixture(first)
    with zipfile.ZipFile(second, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?><container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0"?><package><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:title>第二卷</dc:title><dc:creator>作者甲</dc:creator>
            </metadata><manifest>
            <item id="c1" href="three.xhtml" media-type="application/xhtml+xml"/>
            </manifest><spine><itemref idref="c1"/></spine></package>""",
        )
        archive.writestr(
            "OEBPS/three.xhtml", "<html><body><h1>第三节</h1></body></html>"
        )

    first_result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=first,
            origin="WATCH",
            original_name=first.name,
            monitor_folder_id="folder-1",
        ),
    )
    second_result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=second,
            origin="WATCH",
            original_name=second.name,
            monitor_folder_id="folder-1",
        ),
    )

    bootstrap = client.get(
        f"/api/reader/v3/volumes/{second_result.volume_id}/bootstrap"
    )
    assert bootstrap.status_code == 200
    data = bootstrap.json()["data"]
    assert data["readerType"] == "reflowable"
    assert data["sourceFormat"] == "epub"
    assert data["volume"]["id"] == second_result.volume_id
    assert data["volume"]["title"] == "第 2 卷"
    assert data["volume"]["chapterCount"] == 1
    assert [
        (item["id"], item["title"], item["chapterCount"])
        for item in data["availableVolumes"]
    ] == [
        (first_result.volume_id, "第 1 卷", 2),
        (second_result.volume_id, "第 2 卷", 1),
    ]
    assert [unit["title"] for unit in data["units"]] == ["第三节"]

    second_file = client.get(
        f"/api/volumes/{second_result.volume_id}/file",
        headers={"Range": "bytes=0-3"},
    )
    assert second_file.status_code == 206
    assert second_file.content == second.read_bytes()[:4]


def test_reader_v3_bootstrap_is_volume_scoped_and_reader_v2_is_retired(
    client, db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    fixture_dir = _managed_fixture_dir(test_settings, "reader-shapes")
    epub = fixture_dir / "manual.epub"
    comic = fixture_dir / "comic.zip"
    write_epub_fixture(epub)
    write_comic_fixture(comic)

    epub_imported = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=epub, origin="MANUAL", original_name=epub.name),
    )
    comic_imported = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=comic, origin="MANUAL", original_name=comic.name
        ),
    )
    epub_payload = {
        "volumeId": epub_imported.volume_id,
        "workId": epub_imported.work_id,
    }
    epub_bootstrap = client.get(
        f"/api/reader/v3/volumes/{epub_payload['volumeId']}/bootstrap"
    )
    assert epub_bootstrap.status_code == 200
    epub_data = epub_bootstrap.json()["data"]
    assert epub_data["readerType"] == "reflowable"
    assert epub_data["sourceFormat"] == "epub"
    assert epub_data["volume"]["id"] == epub_payload["volumeId"]
    assert epub_data["mediaVersion"]["workId"] == epub_payload["workId"]
    assert "edition" not in epub_data
    assert len(epub_data["units"]) == 2
    assert [unit["title"] for unit in epub_data["units"]] == ["第一节", "第二节"]
    retired = client.get(
        f"/api/reader/v2/editions/{epub_payload['volumeId']}/bootstrap"
    )
    assert retired.status_code == 410
    assert retired.json()["error"]["code"] == "RESOURCE_RETIRED"
    return
    epub_detail = client.get(f"/api/works/{epub_payload['workId']}")
    assert epub_detail.status_code == 200
    epub_detail_data = epub_detail.json()["data"]
    assert epub_detail_data["book"]["volumeId"] == epub_payload["volumeId"]
    assert [unit["title"] for unit in epub_detail_data["readingUnits"]] == [
        "第一节",
        "第二节",
    ]
    assert epub_detail_data["volumeSections"] == []

    comic_payload = {
        "volumeId": comic_imported.volume_id,
        "workId": comic_imported.work_id,
    }
    comic_bootstrap = client.get(
        f"/api/reader/v3/volumes/{comic_payload['volumeId']}/bootstrap"
    )
    assert comic_bootstrap.status_code == 200
    comic_data = comic_bootstrap.json()["data"]
    assert comic_data["readerType"] == "comic"
    assert comic_data["edition"]["id"] == comic_payload["volumeId"]
    assert comic_data["edition"]["format"] == "comic"
    assert comic_data["selectedVolume"]["id"] == comic_payload["volumeId"]
    assert [
        (item["id"], item["title"], item["pageCount"]) for item in comic_data["volumes"]
    ] == [(comic_payload["volumeId"], "第1卷", 2)]
    assert comic_data["totalPages"] == 2
    assert [page["pageIndex"] for page in comic_data["pages"]] == [1, 2]
    comic_detail = client.get(f"/api/works/{comic_payload['workId']}")
    assert comic_detail.status_code == 200
    comic_detail_data = comic_detail.json()["data"]
    assert comic_detail_data["book"]["volumeId"] == comic_payload["volumeId"]
    assert comic_detail_data["readingUnits"] == []
    assert len(comic_detail_data["volumeSections"]) == 1
    volume_section = comic_detail_data["volumeSections"][0]
    assert {
        key: volume_section[key]
        for key in ["id", "title", "index", "fileId", "pageCount"]
    } == {
        "id": comic_payload["volumeId"],
        "title": "第1卷",
        "index": 0,
        "fileId": comic_payload["volumeId"],
        "pageCount": 2,
    }
    assert volume_section["coverUrl"].startswith(
        f"/api/volumes/{comic_payload['volumeId']}/cover?volumeId={comic_payload['volumeId']}&v="
    )

    db_session.execute(
        text(
            """
            INSERT INTO LibraryVolume (
                id, workId, monitorFolderId, origin, format, versionName, versionKey, sourceGroupKey,
                description, language, publisher, publishedAt, identifier, isbn, importStatus, importError,
                sizeBytes, pageCount, chapterCount, coverPath, coverStatus, "primary", hidden, createdAt, updatedAt
            ) VALUES (
                'comic-edition-alt', :work_id, NULL, 'MANUAL', 'COMIC', '备用版本', 'alt', NULL,
                NULL, NULL, NULL, NULL, NULL, NULL, 'COMPLETED', NULL,
                0, 5, NULL, NULL, 'PENDING', 0, 0, 'now', 'now'
            )
            """
        ),
        {"work_id": comic_payload["workId"]},
    )
    db_session.execute(
        text(
            """
            INSERT INTO LibraryVolume (
                id, volumeId, title, volumeIndex, sortOrder, pageCount, chapterCount, coverPath, createdAt, updatedAt
            ) VALUES
                ('comic-alt-volume-1', 'comic-edition-alt', '第 1 话', 1, 0, 2, NULL, NULL, 'now', 'now'),
                ('comic-alt-volume-2', 'comic-edition-alt', '第 2 话', 2, 1, 3, NULL, NULL, 'now', 'now')
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO LibraryReadingUnit (
                id, volumeId, volumeId, fileId, unitType, title, href, mediaType, sortOrder,
                width, height, size, metadataJson, createdAt, updatedAt
            ) VALUES
                ('comic-alt-page-1', 'comic-edition-alt', 'comic-alt-volume-1', NULL, 'page', '001.jpg', '001.jpg', 'image/jpeg', 0, NULL, NULL, NULL, '{}', 'now', 'now'),
                ('comic-alt-page-2', 'comic-edition-alt', 'comic-alt-volume-1', NULL, 'page', '002.jpg', '002.jpg', 'image/jpeg', 1, NULL, NULL, NULL, '{}', 'now', 'now'),
                ('comic-alt-page-3', 'comic-edition-alt', 'comic-alt-volume-2', NULL, 'page', '001.jpg', '001.jpg', 'image/jpeg', 0, NULL, NULL, NULL, '{}', 'now', 'now'),
                ('comic-alt-page-4', 'comic-edition-alt', 'comic-alt-volume-2', NULL, 'page', '002.jpg', '002.jpg', 'image/jpeg', 1, NULL, NULL, NULL, '{}', 'now', 'now'),
                ('comic-alt-page-5', 'comic-edition-alt', 'comic-alt-volume-2', NULL, 'page', '003.jpg', '003.jpg', 'image/jpeg', 2, NULL, NULL, NULL, '{}', 'now', 'now')
            """
        )
    )
    db_session.commit()

    multi_detail = client.get(f"/api/works/{comic_payload['workId']}")
    assert multi_detail.status_code == 200
    multi_book = multi_detail.json()["data"]["book"]
    assert multi_book["versionCount"] == 2
    assert [edition["versionName"] for edition in multi_book["mediaVersions"]] == [
        "漫画版本",
        "备用版本",
    ]
    assert [
        volume["title"] for volume in multi_book["mediaVersions"][1]["volumes"]
    ] == [
        "第 1 话",
        "第 2 话",
    ]

    alt_bootstrap = client.get(
        "/api/reader/v3/volumes/comic-edition-alt/bootstrap?volume=comic-alt-volume-2"
    )
    assert alt_bootstrap.status_code == 200
    alt_data = alt_bootstrap.json()["data"]
    assert alt_data["readerType"] == "comic"
    assert alt_data["edition"]["id"] == "comic-edition-alt"
    assert alt_data["selectedVolume"]["id"] == "comic-alt-volume-2"
    assert alt_data["selectedVolume"]["title"] == "第 2 话"
    assert alt_data["selectedVolume"]["pageCount"] == 3
    assert [
        (item["id"], item["title"], item["pageCount"]) for item in alt_data["volumes"]
    ] == [
        ("comic-alt-volume-1", "第 1 话", 2),
        ("comic-alt-volume-2", "第 2 话", 3),
    ]
    assert [page["pageIndex"] for page in alt_data["pages"]] == [1, 2, 3]


def legacy_multi_volume_comic_progress_is_volume_scoped_and_bootstrap_opens_next_target(
    client, db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    db_session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS LibraryReadingProgress (
                id TEXT PRIMARY KEY, userId TEXT, workId TEXT, volumeId TEXT, volumeId TEXT,
                readerType TEXT, position TEXT, page INTEGER, percent REAL, extra TEXT,
                schemaVersion INTEGER DEFAULT 1, locationType TEXT, locationJson TEXT,
                contentFingerprint TEXT, mutationId TEXT, clientId TEXT, clientSequence INTEGER,
                createdAt TEXT, updatedAt TEXT
            )
            """
        )
    )
    db_session.commit()
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    comic = _managed_fixture_dir(test_settings, "comic-progress") / "comic.zip"
    write_comic_fixture(comic)
    imported = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=comic, origin="MANUAL", original_name=comic.name
        ),
    )
    payload = {
        "volumeId": imported.volume_id,
        "workId": imported.work_id,
    }
    volume_id = payload["volumeId"]
    work_id = payload["workId"]
    first_volume_id = payload["volumeId"]
    second_volume_id = "comic-volume-2"
    db_session.execute(
        text(
            """
            INSERT INTO LibraryVolume (
                id, volumeId, title, volumeIndex, sortOrder, pageCount, chapterCount, coverPath, createdAt, updatedAt
            ) VALUES (:id, :volume_id, '第 2 卷', 2, 2000, 3, NULL, NULL, 'now', 'now')
            """
        ),
        {"id": second_volume_id, "volume_id": volume_id},
    )
    db_session.execute(
        text(
            """
            INSERT INTO LibraryReadingUnit (
                id, volumeId, volumeId, fileId, unitType, title, href, mediaType, sortOrder,
                width, height, size, metadataJson, createdAt, updatedAt
            ) VALUES
                ('comic-v2-page-1', :volume_id, :volume_id, NULL, 'page', '001.jpg', '001.jpg', 'image/jpeg', 0, NULL, NULL, NULL, '{}', 'now', 'now'),
                ('comic-v2-page-2', :volume_id, :volume_id, NULL, 'page', '002.jpg', '002.jpg', 'image/jpeg', 1, NULL, NULL, NULL, '{}', 'now', 'now'),
                ('comic-v2-page-3', :volume_id, :volume_id, NULL, 'page', '003.jpg', '003.jpg', 'image/jpeg', 2, NULL, NULL, NULL, '{}', 'now', 'now')
            """
        ),
        {"volume_id": second_volume_id},
    )
    db_session.execute(
        text("UPDATE LibraryVolume SET pageCount = 5 WHERE id = :volume_id"),
        {"volume_id": volume_id},
    )
    db_session.commit()

    first_progress = _save_reader_progress_v3(
        client,
        volume_id,
        {
            "readerType": "comic",
            "volumeId": first_volume_id,
            "page": 2,
            "position": "2",
            "percent": 100,
            "extra": {"volumeId": first_volume_id, "pageIndex": 2},
        },
    )
    assert first_progress.status_code == 200
    first_detail = client.get(f"/api/works/{work_id}").json()["data"]["book"]
    assert first_detail["progress"] == 0
    assert first_detail["recentVolumeId"] == second_volume_id
    assert first_detail["chapter"] == "未开始"

    second_progress = _save_reader_progress_v3(
        client,
        volume_id,
        {
            "readerType": "comic",
            "volumeId": second_volume_id,
            "page": 1,
            "position": "1",
            "percent": 20,
            "extra": {"volumeId": second_volume_id, "pageIndex": 1},
        },
    )
    assert second_progress.status_code == 200
    second_detail = client.get(f"/api/works/{work_id}").json()["data"]["book"]
    assert second_detail["progress"] == 20
    assert second_detail["recentVolumeId"] == second_volume_id
    assert second_detail["chapter"] == "第 2 卷 · 第 1 页"

    continue_item = client.get("/api/dashboard/continue-reading").json()["data"]["item"]
    assert set(continue_item) == {
        "workId",
        "title",
        "author",
        "coverUrl",
        "mediaKind",
        "resumeEditionId",
        "resumeVolumeId",
        "progress",
        "chapter",
        "lastReadAt",
        "versionName",
        "narrator",
    }
    assert continue_item["workId"] == work_id
    assert continue_item["mediaKind"] == "COMIC"
    assert continue_item["resumeEditionId"] == volume_id
    assert continue_item["resumeVolumeId"] == second_volume_id
    assert continue_item["progress"] == 20
    assert continue_item["chapter"] == "第 2 卷 · 第 1 页"

    resumed = client.get(f"/api/reader/v3/volumes/{volume_id}/bootstrap").json()["data"]
    assert resumed["selectedVolume"]["id"] == second_volume_id
    assert resumed["progressPercent"] == 20
    assert resumed["resumeLocation"] == {
        "type": "comic",
        "volumeId": second_volume_id,
        "pageIndex": 1,
    }
    explicit = client.get(
        f"/api/reader/v3/volumes/{volume_id}/bootstrap?volume={first_volume_id}"
    ).json()["data"]
    assert explicit["selectedVolume"]["id"] == first_volume_id
    assert explicit["progressPercent"] == 100
    assert explicit["resumeLocation"] == {
        "type": "comic",
        "volumeId": first_volume_id,
        "pageIndex": 2,
    }

    completed = _save_reader_progress_v3(
        client,
        volume_id,
        {
            "readerType": "comic",
            "volumeId": second_volume_id,
            "page": 3,
            "position": "3",
            "percent": 100,
            "extra": {"volumeId": second_volume_id, "pageIndex": 3},
        },
    )
    assert completed.status_code == 200
    complete_detail = client.get(f"/api/works/{work_id}").json()["data"]["book"]
    assert complete_detail["progress"] == 100
    assert complete_detail["recentVolumeId"] == second_volume_id
    assert complete_detail["chapter"] == "第 2 卷 · 第 3 页"


def legacy_multi_volume_epub_detail_returns_selected_volume_chapters_and_scoped_progress(
    client, db_session
):
    create_worker_tables(db_session)
    db_session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS LibraryReadingProgress (
                id TEXT PRIMARY KEY, userId TEXT, workId TEXT, volumeId TEXT, volumeId TEXT,
                readerType TEXT, position TEXT, page INTEGER, percent REAL, extra TEXT,
                schemaVersion INTEGER DEFAULT 1, locationType TEXT, locationJson TEXT,
                contentFingerprint TEXT, mutationId TEXT, clientId TEXT, clientSequence INTEGER,
                createdAt TEXT, updatedAt TEXT
            )
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO LibraryWork (
                id, monitorFolderId, origin, title, normalizedTitle, author, normalizedAuthor, description,
                workType, publicationStatus, trackingStatus, tags, metadataQuality, organizeStatus,
                coverPath, coverStatus, hidden, organized, continueVolumeId, mergeKey, createdAt, updatedAt
            ) VALUES (
                'epub-work', NULL, 'MANUAL', '多卷 EPUB', '多卷 epub', '作者', '作者', NULL,
                'EPUB', 'UNKNOWN', 'NOT_TRACKING', '[]', 0, 'REVIEWING',
                NULL, 'PENDING', 0, 0, 'epub-edition', 'epub-work', 'now', 'now'
            )
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO LibraryVolume (
                id, workId, monitorFolderId, origin, format, versionName, versionKey, sourceGroupKey,
                description, language, publisher, publishedAt, identifier, isbn, importStatus, importError,
                sizeBytes, pageCount, chapterCount, coverPath, coverStatus, "primary", hidden, createdAt, updatedAt
            ) VALUES (
                'epub-edition', 'epub-work', NULL, 'MANUAL', 'EPUB', '默认版本', 'default', NULL,
                NULL, NULL, NULL, NULL, NULL, NULL, 'COMPLETED', NULL,
                0, NULL, 4, NULL, 'PENDING', 1, 0, 'now', 'now'
            )
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO LibraryVolume (
                id, volumeId, title, volumeIndex, sortOrder, pageCount, chapterCount, coverPath, createdAt, updatedAt
            ) VALUES
                ('epub-volume-1', 'epub-edition', '第 1 卷', 1, 1, NULL, 2, NULL, 'now', 'now'),
                ('epub-volume-2', 'epub-edition', '第 2 卷', 2, 2, NULL, 2, NULL, 'now', 'now')
            """
        )
    )
    db_session.execute(
        text(
            """
            INSERT INTO LibraryReadingUnit (
                id, volumeId, volumeId, fileId, unitType, title, href, mediaType, sortOrder,
                width, height, size, metadataJson, createdAt, updatedAt
            ) VALUES
                ('epub-v1-c1', 'epub-edition', 'epub-volume-1', NULL, 'chapter', '第一卷 第一章', 'v1-c1.xhtml', NULL, 1, NULL, NULL, NULL, '{}', 'now', 'now'),
                ('epub-v1-c2', 'epub-edition', 'epub-volume-1', NULL, 'chapter', '第一卷 第二章', 'v1-c2.xhtml', NULL, 2, NULL, NULL, NULL, '{}', 'now', 'now'),
                ('epub-v2-c1', 'epub-edition', 'epub-volume-2', NULL, 'chapter', '第二卷 第一章', 'v2-c1.xhtml', NULL, 1, NULL, NULL, NULL, '{}', 'now', 'now'),
                ('epub-v2-c2', 'epub-edition', 'epub-volume-2', NULL, 'chapter', '第二卷 第二章', 'v2-c2.xhtml', NULL, 2, NULL, NULL, NULL, '{}', 'now', 'now')
            """
        )
    )
    db_session.commit()
    _login(client, db_session)

    first_progress = _save_reader_progress_v3(
        client,
        "epub-edition",
        {
            "readerType": "epub",
            "volumeId": "epub-volume-1",
            "page": 2,
            "position": "cfi-1",
            "percent": 100,
            "extra": {"volumeId": "epub-volume-1"},
        },
    )
    assert first_progress.status_code == 200
    second_progress = _save_reader_progress_v3(
        client,
        "epub-edition",
        {
            "readerType": "epub",
            "volumeId": "epub-volume-2",
            "page": 1,
            "position": "cfi-2",
            "percent": 20,
            "extra": {"volumeId": "epub-volume-2"},
        },
    )
    assert second_progress.status_code == 200

    detail = client.get("/api/works/epub-work").json()["data"]
    assert detail["book"]["recentVolumeId"] == "epub-volume-2"
    assert detail["book"]["progress"] == 20
    assert [unit["title"] for unit in detail["readingUnits"]] == [
        "第二卷 第一章",
        "第二卷 第二章",
    ]
    assert [
        (volume["id"], volume["progress"]) for volume in detail["volumeSections"]
    ] == [("epub-volume-1", 100), ("epub-volume-2", 20)]

    first_volume_detail = client.get(
        "/api/works/epub-work?volumeId=epub-volume-1"
    ).json()["data"]
    assert [unit["title"] for unit in first_volume_detail["readingUnits"]] == [
        "第一卷 第一章",
        "第一卷 第二章",
    ]


def legacy_volume_move_reorders_epub_and_comic_volumes_and_rejects_cross_work(
    client, db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    series_dir = (
        _managed_fixture_dir(test_settings, "epub-series")
        / "[星舰小说][作者甲][Vol.01-Vol.02]"
    )
    series_dir.mkdir()
    first = series_dir / "星舰小说 01.epub"
    second = series_dir / "星舰小说 02.epub"
    write_epub_fixture(first)
    write_epub_fixture(second)
    first_result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=first,
            origin="WATCH",
            original_name=first.name,
            monitor_folder_id="folder-1",
        ),
    )
    second_result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=second,
            origin="WATCH",
            original_name=second.name,
            monitor_folder_id="folder-1",
        ),
    )

    moved_epub = client.post(
        f"/api/works/{first_result.work_id}/volumes/{second_result.volume_id}/move",
        json={"direction": "up"},
    )
    assert moved_epub.status_code == 200
    epub_order = (
        db_session.execute(
            text(
                "SELECT id FROM LibraryVolume WHERE volumeId = :volume_id ORDER BY sortOrder ASC"
            ),
            {"volume_id": first_result.volume_id},
        )
        .scalars()
        .all()
    )
    assert epub_order == [second_result.volume_id, first_result.volume_id]

    comic = _managed_fixture_dir(test_settings, "volume-move-comic") / "comic.zip"
    write_comic_fixture(comic)
    comic_imported = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=comic, origin="MANUAL", original_name=comic.name
        ),
    )
    comic_payload = {
        "volumeId": comic_imported.volume_id,
        "workId": comic_imported.work_id,
    }
    db_session.execute(
        text(
            """INSERT INTO LibraryVolume (
                id, volumeId, title, volumeIndex, sortOrder, pageCount, chapterCount, coverPath, createdAt, updatedAt
            ) VALUES ('comic-extra-volume', :volume_id, '第 2 卷', 2, 2000, 1, NULL, NULL, 'now', 'now')"""
        ),
        {"volume_id": comic_payload["volumeId"]},
    )
    db_session.commit()

    moved_comic = client.post(
        f"/api/works/{comic_payload['workId']}/volumes/comic-extra-volume/move",
        json={"direction": "up"},
    )
    assert moved_comic.status_code == 200
    comic_order = (
        db_session.execute(
            text(
                "SELECT id FROM LibraryVolume WHERE volumeId = :volume_id ORDER BY sortOrder ASC"
            ),
            {"volume_id": comic_payload["volumeId"]},
        )
        .scalars()
        .all()
    )
    assert comic_order == ["comic-extra-volume", comic_payload["volumeId"]]

    cross_work = client.post(
        f"/api/works/{first_result.work_id}/volumes/comic-extra-volume/move",
        json={"direction": "up"},
    )
    assert cross_work.status_code == 404


def test_file_streams_are_limited_per_user(
    client, db_session, test_settings, tmp_path, monkeypatch
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    epub = _managed_fixture_dir(test_settings, "stream-limit") / "manual.epub"
    write_epub_fixture(epub)
    imported = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=epub, origin="MANUAL", original_name=epub.name),
    )
    volume_id = imported.volume_id
    user_id = db_session.execute(
        text("SELECT id FROM User WHERE email = 'admin@example.com'")
    ).scalar()
    monkeypatch.setattr(media_streaming, "STREAMS_PER_USER_LIMIT", 1)
    with media_streaming._active_file_streams_lock:
        media_streaming._active_file_streams_by_user[user_id] = 1
    try:
        limited = client.get(f"/api/volumes/{volume_id}/file")
        assert limited.status_code == 429
        assert limited.json()["error"]["message"] == "同时文件流请求过多，请稍后重试"
    finally:
        with media_streaming._active_file_streams_lock:
            media_streaming._active_file_streams_by_user.pop(user_id, None)


def test_file_streams_log_slow_requests(
    client, db_session, test_settings, tmp_path, monkeypatch, caplog
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    epub = _managed_fixture_dir(test_settings, "stream-logging") / "manual.epub"
    write_epub_fixture(epub)
    imported = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=epub, origin="MANUAL", original_name=epub.name),
    )
    volume_id = imported.volume_id
    monkeypatch.setattr(media_streaming, "SLOW_REQUEST_LOG_THRESHOLD_MS", 0)
    with caplog.at_level(
        "WARNING", logger="app.modules.media.infrastructure.http_streaming"
    ):
        streamed = client.get(
            f"/api/volumes/{volume_id}/file", headers={"Range": "bytes=0-3"}
        )

    assert streamed.status_code == 206
    assert any(
        "[slow-file-request]" in record.message
        and "route=volume-file" in record.message
        for record in caplog.records
    )


def test_imported_pdf_supports_stream_bootstrap_and_v3_progress(
    client, db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    db_session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS LibraryReadingProgress (
                id TEXT PRIMARY KEY, userId TEXT, workId TEXT, volumeId TEXT, volumeId TEXT,
                readerType TEXT, position TEXT, page INTEGER, percent REAL, extra TEXT,
                schemaVersion INTEGER DEFAULT 1, locationType TEXT, locationJson TEXT,
                contentFingerprint TEXT, mutationId TEXT, clientId TEXT, clientSequence INTEGER,
                createdAt TEXT, updatedAt TEXT
            )
            """
        )
    )
    db_session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ReaderPreference (
                id TEXT PRIMARY KEY, userId TEXT, readerType TEXT, settings TEXT,
                createdAt TEXT, updatedAt TEXT
            )
            """
        )
    )
    db_session.commit()
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    pdf = _managed_fixture_dir(test_settings, "pdf-reader") / "manual.pdf"
    write_pdf_fixture(pdf)
    imported = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=pdf, origin="MANUAL", original_name=pdf.name),
    )
    assert imported.format == "pdf"
    volume_id = imported.volume_id

    file_response = client.get(
        f"/api/volumes/{volume_id}/file", headers={"Range": "bytes=0-4"}
    )
    assert file_response.status_code == 206
    assert file_response.headers["content-type"].startswith("application/pdf")
    assert file_response.content == b"%PDF-"

    bootstrap = client.get(f"/api/reader/v3/volumes/{volume_id}/bootstrap")
    assert bootstrap.status_code == 200
    data = bootstrap.json()["data"]
    assert data["readerType"] == "pdf"
    assert data["mediaVersion"]["mediaKind"] == "COMIC"
    assert data["volume"]["format"] == "PDF"
    assert data["volume"]["pageCount"] >= 1
    assert len(data["units"]) == 1

    saved = _save_reader_progress_v3(
        client,
        volume_id,
        {
            "readerType": "pdf",
            "position": "1",
            "page": 1,
            "percent": 0,
            "extra": {"pageIndex": 1, "totalPages": data["volume"]["pageCount"]},
        },
    )
    assert saved.status_code == 200
    assert saved.json()["data"]["progress"]["readerType"] == "pdf"
    resumed = client.get(f"/api/reader/v3/volumes/{volume_id}/bootstrap").json()["data"]
    assert resumed["resumeLocation"] == {
        "type": "pdf",
        "volumeId": volume_id,
        "pageNumber": 1,
    }
    assert resumed["progressPercent"] == 0


def test_imported_comic_serves_archive_page(
    client, db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    comic = _managed_fixture_dir(test_settings, "comic-pages") / "comic.zip"
    write_comic_fixture(comic)
    imported = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=comic, origin="MANUAL", original_name=comic.name
        ),
    )
    volume_id = imported.volume_id
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryReadingUnit WHERE volumeId = :volume_id"),
            {"volume_id": volume_id},
        ).scalar()
        == 0
    )
    page = client.get(f"/api/volumes/{volume_id}/pages/1")

    assert page.status_code == 200
    assert page.content == b"one"
    assert page.headers["content-type"].startswith("image/jpeg")
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryReadingUnit WHERE volumeId = :volume_id"),
            {"volume_id": volume_id},
        ).scalar()
        == 2
    )

    ranged = client.get(
        f"/api/volumes/{volume_id}/pages/1", headers={"Range": "bytes=1-2"}
    )
    assert ranged.status_code == 206
    assert ranged.content == b"ne"
    assert ranged.headers["content-range"] == "bytes 1-2/3"

    cached = client.get(
        f"/api/volumes/{volume_id}/pages/1",
        headers={"If-None-Match": page.headers["etag"]},
    )
    assert cached.status_code == 304


def test_comic_page_data_saver_returns_extreme_avif_for_archive_page(
    client, db_session, test_settings
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    source_jpeg = _comic_page_jpeg_bytes()
    archive_path = (
        test_settings.resolved_storage_root / "books" / "archive" / "comic.zip"
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("001.jpg", source_jpeg)
    relative_archive_path = str(
        archive_path.relative_to(test_settings.resolved_storage_root)
    )
    volume_id = "archive-volume"
    _add_comic_volume(db_session, volume_id)
    db_session.execute(
        text(
            """
            INSERT INTO LibraryFile (
                id, volumeId, path, kind, mimeType, sizeBytes, sortOrder, createdAt, updatedAt
            ) VALUES (
                'archive-file', :volume_id, :path, 'COMIC', 'application/zip', :size, 1, 'now', 'now'
            )
            """
        ),
        {
            "volume_id": volume_id,
            "path": relative_archive_path,
            "size": archive_path.stat().st_size,
        },
    )
    db_session.execute(
        text(
            """
            INSERT INTO LibraryReadingUnit (
                id, volumeId, fileId, unitType, title, href, mediaType, sortOrder, size, metadataJson, createdAt, updatedAt
            ) VALUES (
                'archive-page-1', :volume_id, 'archive-file', 'page', '第 1 页', '001.jpg', 'image/jpeg', 1, :size, :metadata, 'now', 'now'
            )
            """
        ),
        {
            "volume_id": volume_id,
            "size": len(source_jpeg),
            "metadata": json.dumps({"zipEntryName": "001.jpg"}),
        },
    )
    db_session.commit()

    original = client.get(f"/api/volumes/{volume_id}/pages/1?imageVariant=original")
    assert original.status_code == 200
    assert original.content == source_jpeg
    assert original.headers["content-type"].startswith("image/jpeg")
    assert original.headers["x-comic-image-variant"] == "original"

    data_saver = client.get(f"/api/volumes/{volume_id}/pages/1?imageVariant=data-saver")
    assert data_saver.status_code == 200
    assert data_saver.content[4:12] == b"ftypavif"
    assert data_saver.headers["content-type"].startswith("image/avif")
    assert data_saver.headers["x-comic-image-variant"] == "data-saver"
    assert (
        data_saver.headers["x-comic-image-quality"] == "avif;q=12;speed=9;mode=extreme"
    )
    assert float(data_saver.headers["x-comic-image-compression-ratio"]) < 1
    assert len(data_saver.content) < len(source_jpeg)
    assert data_saver.headers["etag"] != original.headers["etag"]

    ranged = client.get(
        f"/api/volumes/{volume_id}/pages/1?imageVariant=data-saver",
        headers={"Range": "bytes=0-3"},
    )
    assert ranged.status_code == 206
    assert ranged.content == data_saver.content[:4]
    assert ranged.headers["content-range"] == f"bytes 0-3/{len(data_saver.content)}"

    cached = client.get(
        f"/api/volumes/{volume_id}/pages/1?imageVariant=data-saver",
        headers={"If-None-Match": data_saver.headers["etag"]},
    )
    assert cached.status_code == 304


def test_comic_page_data_saver_returns_extreme_avif_for_stored_page_file(
    client, db_session, test_settings
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    source_jpeg = _comic_page_jpeg_bytes()
    page_path = (
        test_settings.resolved_storage_root / "books" / "direct" / "page-001.jpg"
    )
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_bytes(source_jpeg)
    relative_page_path = str(page_path.relative_to(test_settings.resolved_storage_root))
    _add_comic_volume(db_session, "direct-volume")
    db_session.execute(
        text(
            """
            INSERT INTO LibraryReadingUnit (
                id, volumeId, fileId, unitType, title, href, mediaType, sortOrder, size, metadataJson, createdAt, updatedAt
            ) VALUES (
                'direct-page-1', 'direct-volume', NULL, 'page', '第 1 页', :href, 'image/jpeg', 1, :size, '{}', 'now', 'now'
            )
            """
        ),
        {"href": relative_page_path, "size": len(source_jpeg)},
    )
    db_session.commit()

    original = client.get("/api/volumes/direct-volume/pages/1?imageVariant=original")
    assert original.status_code == 200
    assert original.content == source_jpeg
    assert original.headers["x-comic-image-variant"] == "original"

    data_saver = client.get(
        "/api/volumes/direct-volume/pages/1?imageVariant=data-saver"
    )
    assert data_saver.status_code == 200
    assert data_saver.content[4:12] == b"ftypavif"
    assert data_saver.headers["content-type"].startswith("image/avif")
    assert data_saver.headers["x-comic-image-variant"] == "data-saver"
    assert (
        data_saver.headers["x-comic-image-quality"] == "avif;q=12;speed=9;mode=extreme"
    )
    assert float(data_saver.headers["x-comic-image-compression-ratio"]) < 1
    assert len(data_saver.content) < len(source_jpeg)


def test_comic_page_data_saver_never_returns_a_larger_transcode():
    output = BytesIO()
    Image.new("L", (1, 1), "white").save(output, format="PNG", optimize=True)
    source = output.getvalue()

    assert media_streaming._comic_page_avif_bytes(source) is None


def test_comic_page_data_saver_uses_one_fixed_avif_encode(monkeypatch):
    source = _comic_page_jpeg_bytes()
    original_save = Image.Image.save
    calls: list[dict] = []

    def capture_save(image, output, format=None, **options):
        calls.append({"format": format, **options})
        return original_save(image, output, format=format, **options)

    monkeypatch.setattr(Image.Image, "save", capture_save)

    optimized = media_streaming._comic_page_avif_bytes(source)

    assert optimized is not None
    assert calls == [{"format": "AVIF", "quality": 12, "speed": 9}]


def test_volume_pages_rebuilds_missing_comic_page_index(
    client, db_session, test_settings, tmp_path
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    comic = _managed_fixture_dir(test_settings, "comic-index") / "comic.zip"
    write_comic_fixture(comic)
    imported = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=comic, origin="MANUAL", original_name=comic.name
        ),
    )
    volume_id = imported.volume_id
    db_session.execute(
        text("UPDATE LibraryVolume SET pageCount = NULL WHERE id = :volume_id"),
        {"volume_id": volume_id},
    )
    db_session.commit()

    listed = client.get(f"/api/volumes/{volume_id}/pages")
    assert listed.status_code == 200
    pages = listed.json()["data"]["pages"]
    assert [page["href"] for page in pages] == ["001.jpg", "002.jpg"]
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM LibraryReadingUnit WHERE volumeId = :volume_id"),
            {"volume_id": volume_id},
        ).scalar()
        == 2
    )
    assert (
        db_session.execute(
            text("SELECT pageCount FROM LibraryVolume WHERE id = :volume_id"),
            {"volume_id": volume_id},
        ).scalar()
        == 2
    )

    page = client.get(f"/api/volumes/{volume_id}/pages/2")
    assert page.status_code == 200
    assert page.content == b"two"


def test_file_stream_limit_zero_disables_slot_rejection(monkeypatch):
    user_id = "limit-disabled-user"
    monkeypatch.setattr(media_streaming, "STREAMS_PER_USER_LIMIT", 0)
    with media_streaming._active_file_streams_lock:
        media_streaming._active_file_streams_by_user[user_id] = 999
    try:
        release = media_streaming._acquire_file_stream_slot(user_id)
        assert release is not None
        release()
        with media_streaming._active_file_streams_lock:
            assert media_streaming._active_file_streams_by_user[user_id] == 999
    finally:
        with media_streaming._active_file_streams_lock:
            media_streaming._active_file_streams_by_user.pop(user_id, None)

    monkeypatch.setattr(media_streaming, "STREAMS_PER_USER_LIMIT", 1)
    release = media_streaming._acquire_file_stream_slot(user_id)
    try:
        assert release is not None
        assert media_streaming._acquire_file_stream_slot(user_id) is None
    finally:
        release()
        with media_streaming._active_file_streams_lock:
            media_streaming._active_file_streams_by_user.pop(user_id, None)


def test_file_stream_limit_has_safe_configured_default(monkeypatch):
    monkeypatch.setattr(media_streaming, "STREAMS_PER_USER_LIMIT", None)
    settings = get_settings()
    assert settings.file_streams_per_user_limit > 0

    user_id = "configured-default-limit-user"
    releases = []
    try:
        for _ in range(settings.file_streams_per_user_limit):
            release = media_streaming._acquire_file_stream_slot(user_id)
            assert release is not None
            releases.append(release)
        assert media_streaming._acquire_file_stream_slot(user_id) is None
    finally:
        for release in releases:
            release()
        with media_streaming._active_file_streams_lock:
            media_streaming._active_file_streams_by_user.pop(user_id, None)


def test_archive_page_streams_are_limited_and_logged(
    client, db_session, test_settings, tmp_path, monkeypatch, caplog
):
    create_worker_tables(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True)
    _login(client, db_session)
    comic = _managed_fixture_dir(test_settings, "archive-streams") / "comic.zip"
    write_comic_fixture(comic)
    imported = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=comic, origin="MANUAL", original_name=comic.name
        ),
    )
    volume_id = imported.volume_id
    user_id = db_session.execute(
        text("SELECT id FROM User WHERE email = 'admin@example.com'")
    ).scalar()
    monkeypatch.setattr(media_streaming, "STREAMS_PER_USER_LIMIT", 1)
    with media_streaming._active_file_streams_lock:
        media_streaming._active_file_streams_by_user[user_id] = 1
    try:
        limited = client.get(f"/api/volumes/{volume_id}/pages/1")
        assert limited.status_code == 429
    finally:
        with media_streaming._active_file_streams_lock:
            media_streaming._active_file_streams_by_user.pop(user_id, None)

    monkeypatch.setattr(media_streaming, "SLOW_REQUEST_LOG_THRESHOLD_MS", 0)
    with caplog.at_level(
        "WARNING", logger="app.modules.media.infrastructure.http_streaming"
    ):
        streamed = client.get(
            f"/api/volumes/{volume_id}/pages/1", headers={"Range": "bytes=0-1"}
        )

    assert streamed.status_code == 206
    assert streamed.content == b"on"
    assert any(
        "[slow-file-request]" in record.message
        and "route=volume-page-zip" in record.message
        for record in caplog.records
    )
