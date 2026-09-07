"""Duplicate roots retain their conflict envelope without creating more work."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Library, LibraryImportTask
from app.modules.imports.presentation.schemas import ImportErrorBody


def test_duplicate_library_root_returns_conflict_without_writes(
    client: TestClient, db_session: Session, tmp_path: Path
) -> None:
    response = client.post(
        "/api/auth/setup",
        json={
            "name": "Library owner",
            "email": "library-owner@example.com",
            "password": "library-contract-password",
        },
    )
    assert response.status_code == 201
    library_root = tmp_path / "library-root"
    library_root.mkdir()
    payload = {
        "name": "Contract library",
        "rootPath": str(library_root),
        "organizationMode": "FLAT",
    }
    created = client.post("/api/libraries", json=payload)
    assert created.status_code == 201
    library_ids = set(db_session.scalars(select(Library.id)))
    task_ids = set(db_session.scalars(select(LibraryImportTask.id)))

    duplicate = client.post("/api/libraries", json=payload)

    assert duplicate.status_code == 409
    assert duplicate.json() == {
        "ok": False,
        "error": {
            "message": "书库路径已存在",
            "details": {"rootPath": str(library_root.resolve())},
        },
    }
    assert set(db_session.scalars(select(Library.id))) == library_ids
    assert set(db_session.scalars(select(LibraryImportTask.id))) == task_ids


def test_import_file_error_details_remain_strict() -> None:
    body = ImportErrorBody.model_validate(
        {"message": "Unsupported files", "details": {"files": ["book.bad"]}}
    )
    assert body.model_dump(by_alias=True, exclude_none=True) == {
        "message": "Unsupported files",
        "details": {"files": ["book.bad"]},
    }
    with pytest.raises(ValidationError):
        ImportErrorBody.model_validate(
            {"message": "Bad details", "details": {"unknown": "value"}}
        )
