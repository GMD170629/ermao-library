from __future__ import annotations

from pathlib import Path

from app.core.auth import hash_password
from app.core.config import Settings
from app.models.auth import User
from app.models.library import (
    LibraryFile,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.modules.library.domain.version_identity import IMPLICIT_VERSION_SOURCE_KEY
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_fb2_publication_manifest_and_resources_use_direct_adapter(
    client: TestClient,
    db_session: Session,
    test_settings: Settings,
) -> None:
    user = User(
        email="fb2-publication@example.com",
        name="FB2 Publication Reader",
        password_hash=hash_password("starshipnas"),
        role="admin",
    )
    relative_path = Path("library") / "direct.fb2"
    source_path = test_settings.resolved_storage_root / relative_path
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        """<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
        <description><title-info><book-title>直接读取 FB2</book-title><lang>zh-CN</lang>
        </title-info></description><body><section><title><p>第一部</p></title>
        <section><title><p>第一章</p></title><p>正文内容</p></section>
        </section></body></FictionBook>""",
        encoding="utf-8",
    )
    work = LibraryWork(
        library_id="test-library",
        id="work-fb2-publication",
        origin="MANUAL",
        title="直接读取 FB2",
        normalized_title="直接读取 fb2",
        tags="[]",
    )
    version = LibraryVersion(
        id="version-fb2-publication",
        work_id=work.id,
        source_key=IMPLICIT_VERSION_SOURCE_KEY,
    )
    volume = LibraryVolume(
        id="volume-fb2-publication",
        version_id=version.id,
        title=work.title,
        sort_order=0,
        format="FB2",
        resource_key="manual:fb2-publication",
        import_status="COMPLETED",
    )
    source = LibraryFile(
        id="file-fb2-publication",
        volume_id=volume.id,
        path=str(relative_path),
        mtime_ms=int(source_path.stat().st_mtime * 1000),
        kind="FB2",
        mime_type="application/x-fictionbook+xml",
        size_bytes=source_path.stat().st_size,
        sort_order=0,
    )
    db_session.add_all([user, work])
    db_session.flush()
    db_session.add_all([version, volume])
    db_session.flush()
    db_session.add(source)
    db_session.commit()
    login = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "starshipnas"},
    )
    assert login.status_code == 200

    manifest_response = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/manifest.json"
    )

    assert manifest_response.status_code == 200
    manifest = manifest_response.json()
    assert manifest["metadata"]["title"] == "直接读取 FB2"
    assert manifest["readingOrder"] == [
        {
            "href": "fb2/section-0001.xhtml",
            "type": "application/xhtml+xml",
            "title": "第一部",
        }
    ]
    assert manifest["toc"][0]["title"] == "第一部"
    assert manifest["toc"][0]["children"][0]["title"] == "第一章"
    source = db_session.get(LibraryFile, "file-fb2-publication")
    assert source is not None
    assert manifest["https://shuku.app/reader/runtime"] == {
        "sourceSizeBytes": source.size_bytes,
        "sourceMtimeMs": source.mtime_ms,
        "parser": "shuku-fb2-parser-v1",
        "normalization": "shuku-fb2-publication-v1",
        "positionPageLength": 1024,
    }

    resource_response = client.get(
        f"/api/reader/v4/volumes/{volume.id}/publication/fb2/section-0001.xhtml"
    )
    assert resource_response.status_code == 200
    assert "正文内容" in resource_response.text
    assert 'data-shuku-security-profile="web-v2"' in resource_response.text
