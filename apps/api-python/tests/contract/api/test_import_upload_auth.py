def test_import_upload_requires_an_authenticated_backend_session(client):
    response = client.post(
        "/api/books/import",
        data={"targetPath": "/library/uploads"},
        files={"file": ("unauthorized.epub", b"not-an-epub", "application/epub+zip")},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_import_upload_reports_shared_limit_as_413_and_cleans_staging(
    client, db_session, tmp_path, monkeypatch
):
    from app.models.library import Library
    from app.modules.imports.application import import_file_size
    from tests.contract.api.test_book_resource_detail_queries import _login

    _login(client, db_session, email="upload-limit@example.com")
    root = tmp_path / "uploads"
    root.mkdir()
    db_session.get(Library, "test-library").root_path = str(root)
    db_session.commit()
    monkeypatch.setattr(import_file_size, "reader_safety_budget", lambda _: 4)
    response = client.post(
        "/api/books/import",
        data={"targetPath": str(root)},
        files={"file": ("book.epub", b"12345", "application/epub+zip")},
    )
    assert response.status_code == 413, response.text
    assert response.json()["error"]["code"] == "IMPORT_FILE_TOO_LARGE"
    assert "2 GiB" in response.json()["error"]["message"]
    assert list(root.iterdir()) == []
