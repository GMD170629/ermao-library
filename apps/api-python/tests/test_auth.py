import re
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import monotonic
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import event, select, text, update
from sqlalchemy.orm import Session, sessionmaker

import app.bootstrap.auth as auth_bootstrap
import app.modules.auth.infrastructure.transactions as auth_transactions
from app.bootstrap.system import prepare_system_event
from app.core.auth import SESSION_REFRESH_DAYS, hash_password, utcnow
from app.core.config import Settings, get_settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.main import create_app
from app.models.auth import PasswordResetToken, User
from app.models.auth import Session as UserSession
from app.models.settings import SystemSetting


def _create_user(db_session, email="admin@example.com", password="starshipnas"):
    user = User(
        email=email, name="账户", password_hash=hash_password(password), role="admin"
    )
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
    assert [(user.email, user.name, user.role) for user in users] == [
        ("owner@example.com", "二毛", "admin")
    ]


def test_admin_user_and_audit_event_roll_back_atomically(db_session, monkeypatch):
    prepared_at = utcnow()
    user = User(
        id="atomic-auth-user",
        email="atomic-auth@example.com",
        name="Atomic auth",
        password_hash=hash_password("atomic-password-123"),
        role="member",
        status="active",
        can_manage_system=False,
        can_view_manual_imports=False,
        authz_version=1,
        created_at=prepared_at,
        updated_at=prepared_at,
    )
    prepared_event = prepare_system_event(
        source="authorization",
        action="user.created",
        message="Atomic user create",
        target_type="user",
        target_id=user.id,
    )

    def fail_event_write(db, events):
        raise RuntimeError("event persistence failed")

    monkeypatch.setattr(
        auth_transactions,
        "write_prepared_system_events",
        fail_event_write,
    )
    with pytest.raises(RuntimeError, match="event persistence failed"):
        auth_bootstrap.persist_admin_user_create(
            db_session,
            user=user,
            locale="zh-CN",
            folder_ids=[],
            prepared_at=prepared_at,
            event=prepared_event,
        )

    assert db_session.get(User, user.id) is None


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

    response = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "wrong"}
    )

    assert response.status_code == 401
    assert response.json()["ok"] is False
    assert response.json()["error"]["message"] == "邮箱或密码不正确"


def test_login_requires_first_run_setup_when_no_account_exists(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "owner@example.com", "password": "not-created-yet"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"code": "SETUP_REQUIRED"}


def test_login_cookie_respects_gateway_path(client, db_session, test_settings):
    test_settings.cookie_path = "/app/ermao-books"
    test_settings.secure_cookies = True
    _create_user(db_session)

    response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "starshipnas"},
    )

    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"]
    assert "Path=/app/ermao-books" in set_cookie
    assert "Secure" in set_cookie


def test_login_session_insert_sends_updated_at(client, db_session):
    _create_user(db_session)
    statements: list[str] = []

    def capture_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", capture_statement)
    try:
        response = client.post(
            "/api/auth/login",
            json={"email": "admin@example.com", "password": "starshipnas"},
        )
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture_statement)

    assert response.status_code == 200
    session_inserts = [
        statement
        for statement in statements
        if "INSERT INTO" in statement and "Session" in statement
    ]
    assert session_inserts
    assert "updatedAt" in session_inserts[-1]


def test_me_requires_session(client):
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["ok"] is False


def test_me_never_writes_and_requests_explicit_refresh(client, db_session):
    user = _create_user(db_session)
    _login(client)
    current_session = (
        db_session.query(UserSession).filter(UserSession.user_id == user.id).one()
    )
    original_expiry = utcnow() + timedelta(days=SESSION_REFRESH_DAYS - 1)
    db_session.execute(
        update(UserSession)
        .where(UserSession.id == current_session.id)
        .values(expires_at=original_expiry)
    )
    db_session.commit()
    statements: list[str] = []

    def capture_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().upper())

    event.listen(db_session.bind, "before_cursor_execute", capture_statement)
    try:
        response = client.get("/api/auth/me")
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture_statement)

    assert response.status_code == 200
    assert response.headers["x-shuku-session-refresh"] == "required"
    assert not any(
        statement.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE"))
        for statement in statements
    )
    db_session.expire_all()
    stored = db_session.get(UserSession, current_session.id)
    assert stored is not None
    assert abs((stored.expires_at - original_expiry).total_seconds()) < 0.001


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/me",
        "/api/auth/preferences",
        "/api/admin/users",
        "/api/system-settings",
        "/api/management/events",
        "/api/backups",
    ],
)
def test_authenticated_get_surfaces_never_execute_dml(
    client,
    db_session,
    path,
):
    user = _create_user(db_session)
    _login(client)
    db_session.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id)
        .values(expires_at=utcnow() + timedelta(days=SESSION_REFRESH_DAYS - 1))
    )
    db_session.commit()
    statements: list[str] = []

    def capture_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().upper())

    event.listen(db_session.bind, "before_cursor_execute", capture_statement)
    try:
        response = client.get(path)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture_statement)

    assert response.status_code == 200, response.text
    assert not any(
        statement.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE"))
        for statement in statements
    )


def test_explicit_session_refresh_updates_current_and_cleans_invalid_sessions(
    client, db_session
):
    current_user = _create_user(db_session)
    disabled_user = _create_user(
        db_session,
        email="disabled@example.com",
        password="disabled-password",
    )
    disabled_user.status = "disabled"
    _login(client)
    now = utcnow()
    expired_session = UserSession(
        token_hash="expired-session",
        user_id=current_user.id,
        expires_at=now - timedelta(minutes=1),
    )
    disabled_session = UserSession(
        token_hash="disabled-session",
        user_id=disabled_user.id,
        expires_at=now + timedelta(days=10),
    )
    db_session.add_all([expired_session, disabled_session])
    db_session.commit()
    expired_session_id = expired_session.id
    disabled_session_id = disabled_session.id

    response = client.post("/api/auth/session/refresh")

    assert response.status_code == 200
    assert "shuku_session" in response.cookies
    db_session.expire_all()
    assert db_session.get(UserSession, expired_session_id) is None
    assert db_session.get(UserSession, disabled_session_id) is None
    current = (
        db_session.query(UserSession)
        .filter(UserSession.user_id == current_user.id)
        .one()
    )
    assert current.expires_at > now + timedelta(days=29)


def test_session_refresh_defers_in_250ms_when_another_engine_holds_writer_lock(
    tmp_path: Path,
) -> None:
    settings = Settings(
        storage_root=str(tmp_path / "storage"),
        secure_cookies=False,
        download_queue_enabled=False,
        kindle_send_queue_enabled=False,
    )
    regular_engine = create_sqlite_engine(settings.database_path)
    short_write_engine = create_sqlite_engine(
        settings.database_path,
        timeout_seconds=0.25,
        transaction_time_budget_seconds=0.25,
    )
    bootstrap_database(regular_engine, settings)
    with Session(regular_engine) as seed_db:
        seed_db.add(
            User(
                email="refresh-lock@example.com",
                name="Refresh lock",
                password_hash=hash_password("starshipnas"),
                role="admin",
            )
        )
        seed_db.commit()

    factory = sessionmaker(
        bind=short_write_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    app = create_app(settings, session_factory=factory)
    app.dependency_overrides[get_settings] = lambda: settings
    blocker = Session(regular_engine)
    try:
        with TestClient(app) as client:
            login = client.post(
                "/api/auth/login",
                json={
                    "email": "refresh-lock@example.com",
                    "password": "starshipnas",
                },
            )
            assert login.status_code == 200
            blocker.execute(
                update(SystemSetting)
                .where(SystemSetting.key == "systemName")
                .values(value="writer lock held")
            )

            started_at = monotonic()
            response = client.post("/api/auth/session/refresh")
            elapsed = monotonic() - started_at

            assert response.status_code == 503
            assert response.json()["error"] == {
                "code": "SESSION_REFRESH_DEFERRED",
                "message": "SESSION_REFRESH_DEFERRED",
            }
            assert 0.15 <= elapsed < 1.0

            blocker.rollback()
            assert client.post("/api/auth/session/refresh").status_code == 200
    finally:
        blocker.rollback()
        blocker.close()
        short_write_engine.dispose()
        regular_engine.dispose()


def test_me_clears_invalid_session_cookie(client):
    client.cookies.set("shuku_session", "invalid-session")

    response = client.get("/api/auth/me")

    assert response.status_code == 401
    set_cookie = response.headers["set-cookie"]
    assert 'shuku_session=""' in set_cookie
    assert "Max-Age=0" in set_cookie


def test_account_email_change_requires_password_and_rejects_case_insensitive_duplicate(
    client, db_session
):
    user = _create_user(db_session)
    _create_user(db_session, email="other@example.com", password="another-password")
    _login(client)

    bad_password = client.patch(
        "/api/auth/account/email",
        json={"email": "new@example.com", "currentPassword": "wrong"},
    )
    assert bad_password.status_code == 400
    assert bad_password.json()["error"]["code"] == "CURRENT_PASSWORD_INCORRECT"

    duplicate = client.patch(
        "/api/auth/account/email",
        json={"email": "OTHER@EXAMPLE.COM", "currentPassword": "starshipnas"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "EMAIL_IN_USE"

    changed = client.patch(
        "/api/auth/account/email",
        json={"email": " New@Example.COM ", "currentPassword": "starshipnas"},
    )
    assert changed.status_code == 200
    assert changed.json()["data"]["user"]["email"] == "new@example.com"
    assert db_session.get(User, user.id).email == "new@example.com"
    assert (
        client.get("/api/auth/me").json()["data"]["user"]["email"] == "new@example.com"
    )


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
    assert (
        db_session.query(UserSession).filter(UserSession.user_id == user.id).count()
        == 1
    )

    bad_password = client.patch(
        "/api/auth/account/password",
        json={"currentPassword": "wrong-password", "newPassword": "new-password-123"},
    )
    assert bad_password.status_code == 400
    assert bad_password.json()["error"]["code"] == "CURRENT_PASSWORD_INCORRECT"

    unchanged = client.patch(
        "/api/auth/account/password",
        json={"currentPassword": "starshipnas", "newPassword": "starshipnas"},
    )
    assert unchanged.status_code == 400
    assert unchanged.json()["error"]["code"] == "NEW_PASSWORD_MUST_DIFFER"

    changed = client.patch(
        "/api/auth/account/password",
        json={"currentPassword": "starshipnas", "newPassword": "new-password-123"},
    )
    assert changed.status_code == 200
    assert changed.json()["data"]["requiresLogin"] is True
    assert (
        db_session.query(UserSession).filter(UserSession.user_id == user.id).count()
        == 0
    )
    assert client.get("/api/auth/me").status_code == 401
    assert _login(client).status_code == 401
    assert _login(client, password="new-password-123").status_code == 200


def test_avatar_upload_is_validated_resized_and_removable(
    client, db_session, test_settings
):
    _create_user(db_session)
    _login(client)
    image_buffer = BytesIO()
    Image.new("RGB", (900, 600), color=(245, 245, 245)).save(image_buffer, format="PNG")

    uploaded = client.post(
        "/api/auth/avatar",
        files={"avatar": ("avatar.png", image_buffer.getvalue(), "image/png")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["data"]["user"]["avatarUrl"].startswith(
        "/api/auth/avatar?v="
    )
    user_id = uploaded.json()["data"]["user"]["id"]
    db_session.expire_all()
    avatar_path = db_session.get(User, user_id).avatar_path
    assert avatar_path is not None
    stored = test_settings.resolved_storage_root / avatar_path
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


def test_avatar_write_contention_preserves_published_file_and_database_reference(
    tmp_path: Path,
) -> None:
    settings = Settings(
        storage_root=str(tmp_path / "storage"),
        secure_cookies=False,
        download_queue_enabled=False,
        kindle_send_queue_enabled=False,
    )
    regular_engine = create_sqlite_engine(settings.database_path)
    short_write_engine = create_sqlite_engine(
        settings.database_path,
        timeout_seconds=0.25,
        transaction_time_budget_seconds=0.25,
    )
    bootstrap_database(regular_engine, settings)
    with Session(regular_engine) as seed_db:
        user = User(
            email="avatar-lock@example.com",
            name="Avatar lock",
            password_hash=hash_password("starshipnas"),
            role="admin",
        )
        seed_db.add(user)
        seed_db.commit()
        user_id = user.id

    factory = sessionmaker(
        bind=short_write_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    app = create_app(settings, session_factory=factory)
    app.dependency_overrides[get_settings] = lambda: settings
    blocker = Session(regular_engine)
    try:
        with TestClient(app) as client:
            login = client.post(
                "/api/auth/login",
                json={
                    "email": "avatar-lock@example.com",
                    "password": "starshipnas",
                },
            )
            assert login.status_code == 200

            red_image = BytesIO()
            Image.new("RGB", (640, 480), color=(220, 20, 30)).save(
                red_image,
                format="PNG",
            )
            baseline_upload = client.post(
                "/api/auth/avatar",
                files={"avatar": ("red.png", red_image.getvalue(), "image/png")},
            )
            assert baseline_upload.status_code == 200
            baseline_response = client.get("/api/auth/avatar")
            assert baseline_response.status_code == 200
            baseline_hash = sha256(baseline_response.content).hexdigest()
            with Session(regular_engine) as inspection_db:
                baseline_path = inspection_db.scalar(
                    select(User.avatar_path).where(User.id == user_id)
                )
            assert baseline_path is not None

            blocker.execute(
                update(SystemSetting)
                .where(SystemSetting.key == "systemName")
                .values(value="avatar writer lock held")
            )
            blue_image = BytesIO()
            Image.new("RGB", (640, 480), color=(20, 30, 220)).save(
                blue_image,
                format="PNG",
            )

            started_at = monotonic()
            failed_upload = client.post(
                "/api/auth/avatar",
                files={"avatar": ("blue.png", blue_image.getvalue(), "image/png")},
            )
            elapsed = monotonic() - started_at

            assert failed_upload.status_code == 503
            assert failed_upload.json()["error"] == {
                "code": "AVATAR_UPDATE_DEFERRED",
                "message": "AVATAR_UPDATE_DEFERRED",
            }
            assert 0.15 <= elapsed < 1.0
            with Session(regular_engine) as inspection_db:
                assert (
                    inspection_db.scalar(
                        select(User.avatar_path).where(User.id == user_id)
                    )
                    == baseline_path
                )
            still_visible = client.get("/api/auth/avatar")
            assert still_visible.status_code == 200
            assert sha256(still_visible.content).hexdigest() == baseline_hash
            profile_directory = settings.resolved_storage_root / "profiles" / user_id
            assert sorted(path.name for path in profile_directory.iterdir()) == [
                Path(baseline_path).name
            ]

            failed_delete = client.delete("/api/auth/avatar")
            assert failed_delete.status_code == 503
            assert failed_delete.json()["error"]["code"] == "AVATAR_UPDATE_DEFERRED"
            assert (
                sha256(client.get("/api/auth/avatar").content).hexdigest()
                == baseline_hash
            )

            blocker.rollback()
            replaced = client.post(
                "/api/auth/avatar",
                files={"avatar": ("blue.png", blue_image.getvalue(), "image/png")},
            )
            assert replaced.status_code == 200
            with Session(regular_engine) as inspection_db:
                replaced_path = inspection_db.scalar(
                    select(User.avatar_path).where(User.id == user_id)
                )
            assert replaced_path is not None
            assert replaced_path != baseline_path
            assert not (settings.resolved_storage_root / baseline_path).exists()
            assert (
                sha256(client.get("/api/auth/avatar").content).hexdigest()
                != baseline_hash
            )
    finally:
        blocker.rollback()
        blocker.close()
        short_write_engine.dispose()
        regular_engine.dispose()


def test_password_reset_writes_local_file_is_hashed_single_use_and_revokes_sessions(
    client, db_session, test_settings
):
    user = _create_user(db_session)
    _login(client)
    test_settings.resolved_library_root.mkdir(parents=True)
    db_session.execute(
        text(
            "INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`) "
            "VALUES ('language', 'en-US', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
            "ON CONFLICT (`key`) DO UPDATE SET `value` = excluded.`value`, "
            "`updatedAt` = excluded.`updatedAt`"
        )
    )
    db_session.commit()

    missing = client.post(
        "/api/auth/password-reset/request", json={"email": "missing@example.com"}
    )
    requested = client.post(
        "/api/auth/password-reset/request",
        json={"email": "ADMIN@EXAMPLE.COM"},
        headers={
            "referer": "https://books.example.test/app/ermao-books/forgot-password"
        },
    )
    assert missing.status_code == requested.status_code == 202
    assert missing.json()["data"]["message"] == requested.json()["data"]["message"]
    reset_file = (
        test_settings.resolved_storage_root / "password-reset" / "reset-password.html"
    )
    assert requested.json()["data"]["filePath"] == str(reset_file)
    document = reset_file.read_text(encoding="utf-8")
    assert '<html lang="en-US">' in document
    assert "Reset your Ermao Books password" in document
    match = re.search(
        r"https://books\.example\.test/app/ermao-books/reset-password#token=([^\"]+)",
        document,
    )
    assert match is not None
    raw_token = unquote(match.group(1))
    stored_token = (
        db_session.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user.id)
        .one()
    )
    assert raw_token not in stored_token.token_hash
    assert len(stored_token.token_hash) == 64

    confirmed = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": raw_token, "newPassword": "reset-password-123"},
    )
    assert confirmed.status_code == 200
    assert not reset_file.exists()
    assert (
        db_session.query(UserSession).filter(UserSession.user_id == user.id).count()
        == 0
    )
    assert (
        client.post(
            "/api/auth/password-reset/confirm",
            json={"token": raw_token, "newPassword": "second-password-123"},
        ).status_code
        == 400
    )
    assert _login(client).status_code == 401
    assert _login(client, password="reset-password-123").status_code == 200


def test_password_reset_capability_reports_local_file_path(client, test_settings):
    payload = client.get("/api/auth/capabilities").json()["data"]
    assert payload["localPasswordReset"] is True
    assert payload["passwordResetFilePath"] == str(
        test_settings.resolved_storage_root / "password-reset" / "reset-password.html"
    )
