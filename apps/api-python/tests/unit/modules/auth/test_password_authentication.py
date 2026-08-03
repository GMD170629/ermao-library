from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

from app.models.auth import User
from app.modules.auth.application.password_authentication import (
    AuthenticatePassword,
    PasswordAuthenticated,
    PasswordAuthenticationInvalid,
    PasswordAuthenticationThrottled,
    PasswordCredentials,
)
from app.modules.auth.application.ports import (
    PasswordVerificationRequest,
    PasswordVerificationResult,
    StoredPasswordCredential,
)
from app.modules.auth.infrastructure.password_authentication import (
    BoundedPasswordVerificationGateway,
    SqlAlchemyUserCredentialReader,
)


class CredentialReaderFake:
    def __init__(self, stored: StoredPasswordCredential | None) -> None:
        self.stored = stored
        self.requested_email: str | None = None

    def find_by_normalized_email(
        self, normalized_email: str
    ) -> StoredPasswordCredential | None:
        self.requested_email = normalized_email
        return self.stored


class VerificationGatewayFake:
    def __init__(self, result: PasswordVerificationResult) -> None:
        self.result = result
        self.request: PasswordVerificationRequest | None = None

    def verify(
        self, request: PasswordVerificationRequest
    ) -> PasswordVerificationResult:
        self.request = request
        return self.result


def _stored(
    *, status: str = "active", password_hash: str = "hash-a"
) -> StoredPasswordCredential:
    return StoredPasswordCredential(
        user_id="user-1",
        email="owner@example.com",
        password_hash=password_hash,
        status=status,
    )


def test_authenticate_password_normalizes_email_and_returns_principal() -> None:
    reader = CredentialReaderFake(_stored())
    gateway = VerificationGatewayFake(PasswordVerificationResult(matched=True))
    authenticate = AuthenticatePassword(reader, gateway)

    result = authenticate.execute(
        PasswordCredentials(
            email=" OWNER@EXAMPLE.COM ",
            password="secret",
            client_address="192.0.2.1",
        )
    )

    assert isinstance(result, PasswordAuthenticated)
    assert result.principal.user_id == "user-1"
    assert reader.requested_email == "owner@example.com"
    assert gateway.request is not None
    assert gateway.request.cache_allowed is True


def test_authenticate_password_hides_missing_and_disabled_accounts() -> None:
    for stored in (None, _stored(status="disabled")):
        gateway = VerificationGatewayFake(PasswordVerificationResult(matched=True))
        result = AuthenticatePassword(CredentialReaderFake(stored), gateway).execute(
            PasswordCredentials("owner@example.com", "secret", "192.0.2.1")
        )

        assert isinstance(result, PasswordAuthenticationInvalid)
        assert gateway.request is not None
        assert gateway.request.cache_allowed is False


def test_authenticate_password_preserves_throttle_result() -> None:
    gateway = VerificationGatewayFake(
        PasswordVerificationResult(matched=False, retry_after_seconds=17)
    )

    result = AuthenticatePassword(CredentialReaderFake(_stored()), gateway).execute(
        PasswordCredentials("owner@example.com", "secret", "192.0.2.1")
    )

    assert result == PasswordAuthenticationThrottled(retry_after_seconds=17)


def test_success_cache_skips_repeated_verification_and_hash_change_misses() -> None:
    calls: list[str] = []

    def verifier(password: str, stored_hash: str) -> bool:
        calls.append(stored_hash)
        return password == "secret"

    runtime = BoundedPasswordVerificationGateway(
        password_verifier=verifier,
        dummy_password_hash="dummy",
        secret=b"test-secret",
    )
    request = PasswordVerificationRequest(
        normalized_email="owner@example.com",
        password="secret",
        stored_password_hash="hash-a",
        client_address="192.0.2.1",
        cache_allowed=True,
    )

    assert runtime.verify(request).matched is True
    assert runtime.verify(request).matched is True
    changed = PasswordVerificationRequest(
        normalized_email=request.normalized_email,
        password=request.password,
        stored_password_hash="hash-b",
        client_address=request.client_address,
        cache_allowed=request.cache_allowed,
    )
    assert runtime.verify(changed).matched is True
    assert calls == ["hash-a", "hash-b"]


def test_success_cache_expires_and_is_capacity_bounded() -> None:
    now = [10.0]
    calls: list[str] = []

    def verifier(_password: str, stored_hash: str) -> bool:
        calls.append(stored_hash)
        return True

    runtime = BoundedPasswordVerificationGateway(
        success_ttl_seconds=5,
        success_capacity=1,
        clock=lambda: now[0],
        password_verifier=verifier,
        dummy_password_hash="dummy",
        secret=b"test-secret",
    )

    def request(password_hash: str) -> PasswordVerificationRequest:
        return PasswordVerificationRequest(
            "owner@example.com", "secret", password_hash, "192.0.2.1", True
        )

    runtime.verify(request("hash-a"))
    runtime.verify(request("hash-b"))
    runtime.verify(request("hash-a"))
    now[0] = 16
    runtime.verify(request("hash-a"))

    assert calls == ["hash-a", "hash-b", "hash-a", "hash-a"]


def test_pair_and_address_attempt_limits_return_retry_after() -> None:
    now = [0.0]
    runtime = BoundedPasswordVerificationGateway(
        pair_attempt_limit=2,
        pair_window_seconds=10,
        address_attempt_limit=3,
        address_window_seconds=20,
        clock=lambda: now[0],
        password_verifier=lambda _password, _stored: False,
        dummy_password_hash="dummy",
        secret=b"test-secret",
    )

    def request(email: str) -> PasswordVerificationRequest:
        return PasswordVerificationRequest(email, "wrong", "hash", "192.0.2.1", False)

    assert runtime.verify(request("a@example.com")).retry_after_seconds is None
    assert runtime.verify(request("a@example.com")).retry_after_seconds is None
    assert runtime.verify(request("a@example.com")).retry_after_seconds == 10
    assert runtime.verify(request("b@example.com")).retry_after_seconds is None
    assert runtime.verify(request("c@example.com")).retry_after_seconds == 20
    now[0] = 21
    assert runtime.verify(request("c@example.com")).retry_after_seconds is None


def test_unknown_account_uses_dummy_hash() -> None:
    seen: list[str] = []

    def verifier(_password: str, stored: str) -> bool:
        seen.append(stored)
        return False

    runtime = BoundedPasswordVerificationGateway(
        password_verifier=verifier,
        dummy_password_hash="dummy-hash",
        secret=b"test-secret",
    )

    result = runtime.verify(
        PasswordVerificationRequest(
            "missing@example.com", "wrong", None, "192.0.2.1", False
        )
    )

    assert result.matched is False
    assert seen == ["dummy-hash"]


def test_single_flight_shares_first_successful_verification() -> None:
    entered = Event()
    release = Event()
    call_lock = Lock()
    calls = 0

    def verifier(_password: str, _stored: str) -> bool:
        nonlocal calls
        with call_lock:
            calls += 1
        entered.set()
        assert release.wait(timeout=2)
        return True

    runtime = BoundedPasswordVerificationGateway(
        password_verifier=verifier,
        dummy_password_hash="dummy",
        secret=b"test-secret",
    )
    request = PasswordVerificationRequest(
        "owner@example.com", "secret", "hash", "192.0.2.1", True
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(runtime.verify, request)
        assert entered.wait(timeout=2)
        second = executor.submit(runtime.verify, request)
        release.set()
        assert first.result(timeout=2).matched is True
        assert second.result(timeout=2).matched is True

    assert calls == 1


def test_sqlalchemy_credential_reader_matches_email_case_insensitively(
    db_session,
) -> None:
    db_session.add(
        User(
            id="user-1",
            email="owner@example.com",
            name="Owner",
            password_hash="stored-hash",
            status="active",
        )
    )
    db_session.commit()

    stored = SqlAlchemyUserCredentialReader(db_session).find_by_normalized_email(
        "OWNER@EXAMPLE.COM".lower()
    )

    assert stored == StoredPasswordCredential(
        user_id="user-1",
        email="owner@example.com",
        password_hash="stored-hash",
        status="active",
    )
