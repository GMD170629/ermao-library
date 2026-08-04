"""ORM and process-local adapters for password authentication."""

from __future__ import annotations

import hmac
from collections import OrderedDict, deque
from collections.abc import Callable
from hashlib import sha256
from math import ceil
from secrets import token_bytes, token_urlsafe
from threading import BoundedSemaphore, Lock
from time import monotonic

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import hash_password, verify_password
from app.models.auth import User
from app.modules.auth.application.ports import (
    PasswordVerificationRequest,
    PasswordVerificationResult,
    StoredPasswordCredential,
)


class SqlAlchemyUserCredentialReader:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_by_normalized_email(
        self, normalized_email: str
    ) -> StoredPasswordCredential | None:
        user = self._session.scalar(
            select(User).where(func.lower(User.email) == normalized_email)
        )
        if user is None:
            return None
        return StoredPasswordCredential(
            user_id=user.id,
            email=user.email,
            password_hash=user.password_hash,
            status=user.status,
        )


class BoundedPasswordVerificationGateway:
    """Bound expensive scrypt work without retaining credentials in plaintext."""

    def __init__(
        self,
        *,
        success_ttl_seconds: float = 300,
        success_capacity: int = 4096,
        pair_attempt_limit: int = 5,
        pair_window_seconds: float = 300,
        address_attempt_limit: int = 30,
        address_window_seconds: float = 60,
        limiter_capacity: int = 10_000,
        single_flight_stripes: int = 64,
        max_concurrent_verifications: int = 4,
        clock: Callable[[], float] = monotonic,
        password_verifier: Callable[[str, str], bool] = verify_password,
        secret: bytes | None = None,
        dummy_password_hash: str | None = None,
    ) -> None:
        if success_ttl_seconds <= 0 or success_capacity <= 0:
            raise ValueError("success cache limits must be positive")
        if pair_attempt_limit <= 0 or address_attempt_limit <= 0:
            raise ValueError("attempt limits must be positive")
        if pair_window_seconds <= 0 or address_window_seconds <= 0:
            raise ValueError("attempt windows must be positive")
        if limiter_capacity <= 0 or single_flight_stripes <= 0:
            raise ValueError("runtime capacities must be positive")
        if max_concurrent_verifications <= 0:
            raise ValueError("verification concurrency must be positive")
        self._success_ttl_seconds = success_ttl_seconds
        self._success_capacity = success_capacity
        self._pair_attempt_limit = pair_attempt_limit
        self._pair_window_seconds = pair_window_seconds
        self._address_attempt_limit = address_attempt_limit
        self._address_window_seconds = address_window_seconds
        self._limiter_capacity = limiter_capacity
        self._clock = clock
        self._password_verifier = password_verifier
        self._secret = secret or token_bytes(32)
        self._dummy_password_hash = dummy_password_hash or hash_password(
            token_urlsafe(32)
        )
        self._successes: OrderedDict[str, float] = OrderedDict()
        self._attempts: OrderedDict[str, deque[float]] = OrderedDict()
        self._state_lock = Lock()
        self._single_flight = tuple(Lock() for _ in range(single_flight_stripes))
        self._verification_slots = BoundedSemaphore(max_concurrent_verifications)

    def verify(
        self, request: PasswordVerificationRequest
    ) -> PasswordVerificationResult:
        stored_hash = request.stored_password_hash or self._dummy_password_hash
        credential_key = self._digest(
            "credential",
            request.normalized_email,
            request.password,
            stored_hash,
        )
        now = self._clock()
        if request.cache_allowed and self._is_cached(credential_key, now):
            return PasswordVerificationResult(matched=True)

        stripe = self._single_flight[
            int(credential_key[:16], 16) % len(self._single_flight)
        ]
        with stripe:
            now = self._clock()
            if request.cache_allowed and self._is_cached(credential_key, now):
                return PasswordVerificationResult(matched=True)
            retry_after = self._retry_after_failure_limit(request, now)
            if retry_after is not None:
                return PasswordVerificationResult(
                    matched=False, retry_after_seconds=retry_after
                )
            with self._verification_slots:
                matched = self._password_verifier(request.password, stored_hash)
            if matched and request.cache_allowed:
                self._record_success(credential_key, self._clock())
                self._clear_pair_attempts(request)
            elif not matched:
                self._record_failure(request, self._clock())
            return PasswordVerificationResult(matched=matched)

    def _digest(self, namespace: str, *values: str) -> str:
        message = bytearray(namespace.encode("utf-8"))
        for value in values:
            encoded = value.encode("utf-8")
            message.extend(len(encoded).to_bytes(8, "big"))
            message.extend(encoded)
        return hmac.new(self._secret, bytes(message), sha256).hexdigest()

    def _is_cached(self, key: str, now: float) -> bool:
        with self._state_lock:
            expires_at = self._successes.get(key)
            if expires_at is None:
                return False
            if expires_at <= now:
                self._successes.pop(key, None)
                return False
            self._successes.move_to_end(key)
            return True

    def _record_success(self, key: str, now: float) -> None:
        with self._state_lock:
            self._successes[key] = now + self._success_ttl_seconds
            self._successes.move_to_end(key)
            while len(self._successes) > self._success_capacity:
                self._successes.popitem(last=False)

    def _retry_after_failure_limit(
        self, request: PasswordVerificationRequest, now: float
    ) -> int | None:
        address = request.client_address or "unknown"
        address_key = self._digest("address", address)
        pair_key = self._digest("pair", address, request.normalized_email)
        with self._state_lock:
            address_retry = self._retry_after(
                address_key,
                now,
                self._address_attempt_limit,
                self._address_window_seconds,
            )
            pair_retry = self._retry_after(
                pair_key,
                now,
                self._pair_attempt_limit,
                self._pair_window_seconds,
            )
            retry_after = max(address_retry or 0, pair_retry or 0)
            if retry_after > 0:
                return retry_after
            return None

    def _record_failure(self, request: PasswordVerificationRequest, now: float) -> None:
        address = request.client_address or "unknown"
        address_key = self._digest("address", address)
        pair_key = self._digest("pair", address, request.normalized_email)
        with self._state_lock:
            self._append_attempt(address_key, now)
            self._append_attempt(pair_key, now)

    def _retry_after(
        self, key: str, now: float, limit: int, window_seconds: float
    ) -> int | None:
        attempts = self._attempts.get(key)
        if attempts is None:
            return None
        cutoff = now - window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            self._attempts.pop(key, None)
            return None
        self._attempts.move_to_end(key)
        if len(attempts) < limit:
            return None
        return max(1, ceil(attempts[0] + window_seconds - now))

    def _append_attempt(self, key: str, now: float) -> None:
        """Append while the caller holds the state lock."""

        attempts = self._attempts.setdefault(key, deque())
        attempts.append(now)
        self._attempts.move_to_end(key)
        while len(self._attempts) > self._limiter_capacity:
            self._attempts.popitem(last=False)

    def _clear_pair_attempts(self, request: PasswordVerificationRequest) -> None:
        address = request.client_address or "unknown"
        pair_key = self._digest("pair", address, request.normalized_email)
        with self._state_lock:
            self._attempts.pop(pair_key, None)
