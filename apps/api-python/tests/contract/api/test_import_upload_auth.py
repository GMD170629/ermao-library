def test_import_upload_requires_an_authenticated_backend_session(client):
    response = client.post(
        "/api/books/import",
        data={"targetPath": "/library/uploads"},
        files={"file": ("unauthorized.epub", b"not-an-epub", "application/epub+zip")},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
