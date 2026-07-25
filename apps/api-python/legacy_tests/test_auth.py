from io import BytesIO
import re
from urllib.parse import unquote

from PIL import Image
from sqlalchemy import event, text

from app.core.auth import hash_password
from app.models.auth import PasswordResetToken, Session as UserSession, User


def _create_user(db_session, email="admin@example.com", password="starshipnas"):
    user = User(email=email, name="账户", password_hash=hash_password(password), role="admin")
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, email="admin@example.com", password="starshipnas"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_first_run_setup_creates_only_one_admin_and_signs_in(client, db_session):
    status = client.get("/api/auth/setup/status")
    assert status.status_code == 200
    assert status.json()["data"] == {"initialized": False}
    assert status.headers["cache-control"] == "no-store"

    created = client.post(
        "/api/auth/setup",
        json={
            "name": "  二毛  ",
            "email": " OWNER@EXAMPLE.COM ",
            "password": "initial-password-123",
            "locale": "en-US",
        },
    )
    assert created.status_code == 201
    assert created.json()["data"]["initialized"] is True
    assert created.json()["data"]["user"]["email"] == "owner@example.com"
    assert created.json()["data"]["user"]["name"] == "二毛"
    assert created.json()["data"]["user"]["role"] == "admin"
    assert created.json()["data"]["user"]["locale"] == "en-US"
    assert "shuku_session" in created.cookies
    assert created.cookies["shuku_locale"] == "en-US"
    assert client.get("/api/auth/setup/status").json()["data"] == {"initialized": True}
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["user"]["locale"] == "en-US"

    duplicate = client.post(
        "/api/auth/setup",
        json={"email": "other@example.com", "password": "another-password-123"},
    )
    assert duplicate.status_code == 409
    users = db_session.query(User).all()
    assert [(user.email, user.name, user.role) for user in users] == [("owner@example.com", "二毛", "admin")]


def test_first_run_setup_validates_account_fields(client):
    short_password = client.post(
        "/api/auth/setup",
        json={"email": "owner@example.com", "password": "short"},
    )
    assert short_password.status_code == 422


def test_login_me_and_logout(client, db_session):
    _create_user(db_session)

    login = _login(client, email="ADMIN@EXAMPLE.COM")
    assert login.status_code == 200
    assert login.json()["ok"] is True
    assert login.json()["data"]["user"]["email"] == "admin@example.com"
    assert "shuku_session" in login.cookies

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["user"]["role"] == "admin"

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert logout.json()["data"]["loggedOut"] is True


def test_login_rejects_bad_password(client, db_session):
    _create_user(db_session)

    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong"})

    assert response.status_code == 401
    assert response.json()["ok"] is False
    assert response.json()["error"]["message"] == "邮箱或密码不正确"


def test_login_requires_first_run_setup_when_no_account_exists(client):
    response = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "not-created-yet"})

    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"code": "SETUP_REQUIRED"}


def test_login_cookie_respects_gateway_path(client, db_session, test_settings):
    test_settings.cookie_path = "/app/shuku-starship"
    test_settings.secure_cookies = True
    _create_user(db_session)

    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "starshipnas"})

    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"]
    assert "Path=/app/shuku-starship" in set_cookie
    assert "Secure" in set_cookie


def test_login_session_insert_sends_updated_at(client, db_session):
    _create_user(db_session)
    statements: list[str] = []

    def capture_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", capture_statement)
    try:
        response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "starshipnas"})
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture_statement)

    assert response.status_code == 200
    session_inserts = [statement for statement in statements if "INSERT INTO" in statement and "Session" in statement]
    assert session_inserts
    assert "updatedAt" in session_inserts[-1]


def test_me_requires_session(client):
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["ok"] is False


def test_me_clears_invalid_session_cookie(client):
    client.cookies.set("shuku_session", "invalid-session")

    response = client.get("/api/auth/me")

    assert response.status_code == 401
    set_cookie = response.headers["set-cookie"]
    assert 'shuku_session=""' in set_cookie
    assert "Max-Age=0" in set_cookie


def test_account_email_change_requires_password_and_rejects_case_insensitive_duplicate(client, db_session):
    user = _create_user(db_session)
    _create_user(db_session, email="other@example.com", password="another-password")
    _login(client)

    bad_password = client.patch(
        "/api/auth/account/email",
        json={"email": "new@example.com", "currentPassword": "wrong"},
    )
    assert bad_password.status_code == 400

    duplicate = client.patch(
        "/api/auth/account/email",
        json={"email": "OTHER@EXAMPLE.COM", "currentPassword": "starshipnas"},
    )
    assert duplicate.status_code == 409

    changed = client.patch(
        "/api/auth/account/email",
        json={"email": " New@Example.COM ", "currentPassword": "starshipnas"},
    )
    assert changed.status_code == 200
    assert changed.json()["data"]["user"]["email"] == "new@example.com"
    assert db_session.get(User, user.id).email == "new@example.com"
    assert client.get("/api/auth/me").json()["data"]["user"]["email"] == "new@example.com"


def test_account_name_change_is_trimmed_and_returned_by_session(client, db_session):
    user = _create_user(db_session)
    _login(client)

    blank = client.patch("/api/auth/account/name", json={"name": "   "})
    assert blank.status_code == 422

    changed = client.patch("/api/auth/account/name", json={"name": "  二毛  "})
    assert changed.status_code == 200
    assert changed.json()["data"]["user"]["name"] == "二毛"
    assert db_session.get(User, user.id).name == "二毛"
    assert client.get("/api/auth/me").json()["data"]["user"]["name"] == "二毛"


def test_account_password_change_revokes_all_sessions(client, db_session):
    user = _create_user(db_session)
    _login(client)
    assert db_session.query(UserSession).filter(UserSession.user_id == user.id).count() == 1

    changed = client.patch(
        "/api/auth/account/password",
        json={"currentPassword": "starshipnas", "newPassword": "new-password-123"},
    )
    assert changed.status_code == 200
    assert changed.json()["data"]["requiresLogin"] is True
    assert db_session.query(UserSession).filter(UserSession.user_id == user.id).count() == 0
    assert client.get("/api/auth/me").status_code == 401
    assert _login(client).status_code == 401
    assert _login(client, password="new-password-123").status_code == 200


def test_avatar_upload_is_validated_resized_and_removable(client, db_session, test_settings):
    _create_user(db_session)
    _login(client)
    image_buffer = BytesIO()
    Image.new("RGB", (900, 600), color=(245, 245, 245)).save(image_buffer, format="PNG")

    uploaded = client.post(
        "/api/auth/avatar",
        files={"avatar": ("avatar.png", image_buffer.getvalue(), "image/png")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["data"]["user"]["avatarUrl"].startswith("/api/auth/avatar?v=")
    stored = test_settings.resolved_storage_root / "profiles" / uploaded.json()["data"]["user"]["id"] / "avatar.webp"
    assert stored.is_file()
    with Image.open(stored) as processed:
        assert processed.format == "WEBP"
        assert processed.size == (512, 512)

    served = client.get("/api/auth/avatar")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"

    invalid = client.post(
        "/api/auth/avatar",
        files={"avatar": ("fake.png", b"not-an-image", "image/png")},
    )
    assert invalid.status_code == 400

    removed = client.delete("/api/auth/avatar")
    assert removed.status_code == 200
    assert removed.json()["data"]["user"]["avatarUrl"] is None
    assert not stored.exists()


def test_password_reset_writes_local_file_is_hashed_single_use_and_revokes_sessions(client, db_session, test_settings):
    user = _create_user(db_session)
    _login(client)
    test_settings.resolved_monitor_root.mkdir(parents=True)
    db_session.execute(text(
        "INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`) "
        "VALUES ('language', 'en-US', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
        "ON CONFLICT (`key`) DO UPDATE SET `value` = excluded.`value`, `updatedAt` = excluded.`updatedAt`"
    ))
    db_session.commit()

    missing = client.post("/api/auth/password-reset/request", json={"email": "missing@example.com"})
    requested = client.post(
        "/api/auth/password-reset/request",
        json={"email": "ADMIN@EXAMPLE.COM"},
        headers={"referer": "https://books.example.test/app/shuku-starship/forgot-password"},
    )
    assert missing.status_code == requested.status_code == 202
    assert missing.json()["data"]["message"] == requested.json()["data"]["message"]
    reset_file = test_settings.resolved_monitor_root / "reset-password.html"
    assert requested.json()["data"]["filePath"] == str(reset_file)
    document = reset_file.read_text(encoding="utf-8")
    assert '<html lang="en-US">' in document
    assert "Reset your Ermao Books password" in document
    match = re.search(r"https://books\.example\.test/app/shuku-starship/reset-password#token=([^\"]+)", document)
    assert match is not None
    raw_token = unquote(match.group(1))
    stored_token = db_session.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).one()
    assert raw_token not in stored_token.token_hash
    assert len(stored_token.token_hash) == 64

    confirmed = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": raw_token, "newPassword": "reset-password-123"},
    )
    assert confirmed.status_code == 200
    assert not reset_file.exists()
    assert db_session.query(UserSession).filter(UserSession.user_id == user.id).count() == 0
    assert client.post(
        "/api/auth/password-reset/confirm",
        json={"token": raw_token, "newPassword": "second-password-123"},
    ).status_code == 400
    assert _login(client).status_code == 401
    assert _login(client, password="reset-password-123").status_code == 200


def test_password_reset_capability_reports_local_file_path(client, test_settings):
    payload = client.get("/api/auth/capabilities").json()["data"]
    assert payload["localPasswordReset"] is True
    assert payload["passwordResetFilePath"] == str(test_settings.resolved_monitor_root / "reset-password.html")
