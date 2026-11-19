from app.core.auth import hash_password
from app.models.auth import User


def test_storage_http_authorization_and_category_cleanup(
    client, db_session, test_settings
):
    assert client.get("/api/system/storage").status_code == 401
    assert client.delete("/api/system/storage/cache").status_code == 401
    user = User(
        email="storage@example.com",
        name="Storage",
        role="admin",
        password_hash=hash_password("storage-password"),
    )
    db_session.add(user)
    db_session.commit()
    assert (
        client.post(
            "/api/auth/login",
            json={"email": user.email, "password": "storage-password"},
        ).status_code
        == 200
    )
    root = test_settings.resolved_storage_root
    (root / "cache").mkdir(exist_ok=True)
    (root / "cache/item").write_bytes(b"cache")
    result = client.get("/api/system/storage")
    assert result.status_code == 200
    assert len(result.json()["data"]["categories"]) == 9
    assert not db_session.in_transaction()
    result = client.delete("/api/system/storage/cache")
    assert result.status_code == 200
    assert result.json()["data"]["categories"] == [
        {"id": "cache", "sizeBytes": 0, "clearable": True}
    ]
    assert not (root / "cache").exists()
    assert client.delete("/api/system/storage/database").status_code == 422
    assert client.get("/api/system/storage?category=cache").json()["data"][
        "categories"
    ] == [{"id": "cache", "sizeBytes": 0, "clearable": True}]


def test_storage_http_preserves_system_manager_requirement(client, db_session):
    user = User(
        email="reader-storage@example.com",
        name="Reader",
        role="member",
        password_hash=hash_password("storage-password"),
    )
    db_session.add(user)
    db_session.commit()
    assert (
        client.post(
            "/api/auth/login",
            json={"email": user.email, "password": "storage-password"},
        ).status_code
        == 200
    )
    assert client.get("/api/system/storage").status_code == 403
    assert client.delete("/api/system/storage/cache").status_code == 403
