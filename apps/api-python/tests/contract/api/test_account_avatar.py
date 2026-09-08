from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.models.auth import User


def test_server_owns_default_upload_and_delete_display(client: TestClient) -> None:
    assert client.get("/api/auth/avatar").status_code == 401
    setup = client.post(
        "/api/auth/setup",
        json={
            "name": "Avatar test",
            "email": "avatar@example.com",
            "password": "avatar-test-password",
            "locale": "en-US",
        },
    )
    assert setup.status_code == 201
    account = setup.json()["data"]["user"]
    assert account["avatarUrl"] is None
    default_url = account["avatarImageUrl"]
    default = client.get(default_url)
    assert default.status_code == 200
    assert default.headers["content-type"] == "image/webp"
    assert default.headers["cache-control"] == "private, no-cache"
    with Image.open(BytesIO(default.content)) as decoded:
        assert decoded.format == "WEBP"
        assert decoded.size == (192, 192)
    photo = BytesIO()
    Image.new("RGB", (64, 64), "red").save(photo, format="PNG")
    uploaded = client.post(
        "/api/auth/avatar",
        files={
            "avatar": ("photo.png", photo.getvalue(), "image/png"),
        },
    )
    assert uploaded.status_code == 200
    custom = uploaded.json()["data"]["user"]
    assert custom["avatarImageUrl"] == custom["avatarUrl"]
    assert client.get(custom["avatarImageUrl"]).content != default.content
    deleted = client.delete("/api/auth/avatar")
    assert deleted.status_code == 200
    restored = deleted.json()["data"]["user"]
    assert restored["avatarUrl"] is None
    assert client.get(restored["avatarImageUrl"]).content == default.content
    reopened = client.get("/api/auth/me").json()["data"]["user"]
    assert reopened["avatarImageUrl"] == default_url


def test_missing_or_escaping_upload_uses_server_default(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    setup = client.post(
        "/api/auth/setup",
        json={
            "name": "Avatar test",
            "email": "avatar@example.com",
            "password": "avatar-test-password",
            "locale": "zh-CN",
        },
    )
    assert setup.status_code == 201
    account = setup.json()["data"]["user"]
    original = client.get(account["avatarImageUrl"]).content
    user = db_session.get(User, account["id"])
    assert user is not None
    outside = tmp_path / "outside.webp"
    outside.write_bytes(b"private-outside-content")
    for reference in ("missing.webp", str(outside)):
        user.avatar_path = reference
        db_session.commit()
        response = client.get("/api/auth/avatar")
        assert response.status_code == 200
        assert response.content == original
    assert outside.read_bytes() == b"private-outside-content"
