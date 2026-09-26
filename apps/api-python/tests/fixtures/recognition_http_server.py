"""Isolated HTTP smoke fixture: real app/SQLite, fixture Google transport only.

Run from apps/api-python with STORAGE_ROOT pointing to an empty temporary folder:
python tests/fixtures/recognition_http_server.py
No production credentials or external network requests are used.
"""

import io
import json
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn
from sqlalchemy.orm import sessionmaker

from app.core.auth import hash_password
from app.core.config import get_settings
from app.db.base import Base
from app.db.sqlite import create_sqlite_engine
from app.main import create_app
from app.models import LibraryReadableResourceMetadata, LibrarySourceNode
from app.models.auth import User
from app.models.library import Library
from app.modules.metadata.domain.providers import BUILTIN_MANIFESTS
from app.modules.metadata.infrastructure import bibliographic_providers
from app.modules.metadata.infrastructure.sources import (
    prepare_builtin_provider_seed_rows,
    write_builtin_provider_seed_rows,
)
from app.services.metadata_provider_registry import update_metadata_provider_order


def main() -> None:
    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(settings.database_path)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    helpers = runpy.run_path("tests/contract/api/test_recognized_metadata_api.py")
    with factory() as db:
        if db.get(User, "smoke-admin") is None:
            root = settings.resolved_storage_root / "library"
            root.mkdir(parents=True, exist_ok=True)
            db.add(Library(id="test-library", name="Recognition smoke", root_path=str(root), organization_mode="FLAT"))
            db.add(User(id="smoke-admin", email="recognition@example.com", name="Recognition smoke", role="admin", password_hash=hash_password(helpers["PASSWORD"])))
            db.commit()
            resource_id = helpers["_add_book"](db, book_id="recognition-smoke")
            node = db.get(LibrarySourceNode, resource_id + "-node")
            node.parent_id = "recognition-smoke-root"
            node.parent_physical_kind = "DIRECTORY"
            db.get(LibraryReadableResourceMetadata, resource_id).title = "示例书 第1卷"
            write_builtin_provider_seed_rows(db, prepare_builtin_provider_seed_rows(BUILTIN_MANIFESTS))
            db.commit()
            update_metadata_provider_order(db, [{"providerId": value.id, "enabled": False} for value in BUILTIN_MANIFESTS])
    requests = []

    def fixture_google(request, *, timeout):
        assert request.full_url.startswith("https://www.googleapis.com/books/v1/volumes")
        requests.append("google-books")
        return io.BytesIO(json.dumps({"items": [{"id": "fixture-edition-1", "volumeInfo": {
            "title": "示例书 第1卷", "authors": ["旧作者"], "publisher": "Fixture Press", "publishedDate": "1980",
            "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780306406157"}],
            "description": "Verified fixture description", "language": "zh"}}]}).encode())

    bibliographic_providers.urlopen = fixture_google
    app = create_app(settings, session_factory=factory)
    app.dependency_overrides[get_settings] = lambda: settings

    @app.get("/_fixture/requests")
    def request_count():
        return {"requests": len(requests)}

    @app.post("/_fixture/reset")
    def reset_target():
        with factory() as db:
            target = db.get(LibraryReadableResourceMetadata, "recognition-smoke-resource")
            target.description = target.publisher = target.published_at = target.language = target.isbn = None
            target.protected_fields = "[]"
            db.commit()
        requests.clear()
        return {"reset": True}

    uvicorn.run(app, host="127.0.0.1", port=8106)


if __name__ == "__main__":
    main()
