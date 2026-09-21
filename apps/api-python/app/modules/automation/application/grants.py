"""Grant lifecycle and fresh authorization shared by HTTP and file workers."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.modules.automation.application.audit import AutomationAuditPort
from app.modules.automation.domain.access import (
    AutomationAccessError,
    AutomationActor,
    EffectiveAccess,
    GrantPermissions,
    Scope,
    effective_access,
    validate_permissions,
)


@dataclass(frozen=True, slots=True)
class AutomationGrant:
    id: str
    user_id: str
    name: str
    permissions: GrantPermissions
    created_at_ms: int
    expires_at_ms: int
    revoked_at_ms: int | None = None
    last_used_at_ms: int | None = None


@dataclass(frozen=True, slots=True)
class IssuedCredential:
    grant_id: str
    token: str = field(repr=False)
    digest: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class CreatedGrant:
    grant: AutomationGrant
    token: str = field(repr=False)


class GrantStore(Protocol):
    def add(self, grant: AutomationGrant, digest: str) -> None: ...

    def by_digest(self, digest: str) -> AutomationGrant | None: ...

    def by_id(self, grant_id: str) -> AutomationGrant | None: ...

    def list_owned(self, user_id: str) -> tuple[AutomationGrant, ...]: ...

    def revoke(self, grant_id: str, user_id: str, now_ms: int) -> bool: ...


class AutomationIdentityPort(Protocol):
    def current_actor(self, user_id: str) -> AutomationActor | None: ...


class CredentialPort(Protocol):
    def issue(self) -> IssuedCredential: ...

    def digest(self, token: str) -> str | None: ...


class GrantUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class ManageGrants:
    def __init__(
        self,
        store: GrantStore,
        identities: AutomationIdentityPort,
        credentials: CredentialPort,
        unit_of_work: GrantUnitOfWork,
        clock_ms: Callable[[], int],
        audit: AutomationAuditPort,
    ) -> None:
        self._store = store
        self._identities = identities
        self._credentials = credentials
        self._uow = unit_of_work
        self._clock_ms = clock_ms
        self._audit = audit

    def _actor(self, user_id: str) -> AutomationActor:
        actor = self._identities.current_actor(user_id)
        if actor is None or not actor.active:
            raise AutomationAccessError("UNAUTHORIZED")
        return actor

    def create(
        self,
        *,
        user_id: str,
        name: str,
        permissions: GrantPermissions,
        lifetime_days: int = 90,
    ) -> CreatedGrant:
        actor = self._actor(user_id)
        validate_permissions(permissions, actor)
        name = name.strip()
        if not name or len(name) > 100 or any(ord(char) < 32 for char in name):
            raise AutomationAccessError("INVALID_GRANT_NAME")
        if isinstance(lifetime_days, bool) or lifetime_days not in {30, 90, 365}:
            raise AutomationAccessError("INVALID_GRANT_LIFETIME")
        now_ms = self._clock_ms()
        credential = self._credentials.issue()
        grant = AutomationGrant(
            id=credential.grant_id,
            user_id=user_id,
            name=name,
            permissions=permissions,
            created_at_ms=now_ms,
            expires_at_ms=now_ms + lifetime_days * 86_400_000,
        )
        event = self._audit.prepare("grant.created", user_id, grant.id)
        try:
            self._store.add(grant, credential.digest)
            self._audit.write(event)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return CreatedGrant(grant, credential.token)

    def list_owned(self, user_id: str) -> tuple[AutomationGrant, ...]:
        self._actor(user_id)
        return self._store.list_owned(user_id)

    def revoke(self, *, user_id: str, grant_id: str) -> None:
        self._actor(user_id)
        now_ms = self._clock_ms()
        event = self._audit.prepare("grant.revoked", user_id, grant_id)
        try:
            if not self._store.revoke(grant_id, user_id, now_ms):
                raise AutomationAccessError("GRANT_NOT_FOUND")
            self._audit.write(event)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise


class AuthorizeAutomation:
    def __init__(
        self,
        store: GrantStore,
        identities: AutomationIdentityPort,
        credentials: CredentialPort,
        clock_ms: Callable[[], int],
    ) -> None:
        self._store = store
        self._identities = identities
        self._credentials = credentials
        self._clock_ms = clock_ms

    def bearer(
        self,
        authorization: str | None,
        *,
        service_enabled: bool,
        enabled_scopes: frozenset[Scope],
    ) -> EffectiveAccess:
        if not service_enabled:
            raise AutomationAccessError("AUTOMATION_DISABLED")
        parts = (authorization or "").split()
        if len(parts) != 2 or parts[0].casefold() != "bearer":
            raise AutomationAccessError("UNAUTHORIZED")
        digest = self._credentials.digest(parts[1])
        grant = self._store.by_digest(digest) if digest is not None else None
        return self._authorize(grant, enabled_scopes)

    def operation(
        self,
        *,
        grant_id: str,
        user_id: str,
        service_enabled: bool,
        enabled_scopes: frozenset[Scope],
    ) -> EffectiveAccess:
        """Recheck a durable operation at each new target and publication boundary."""
        if not service_enabled:
            raise AutomationAccessError("AUTOMATION_DISABLED")
        grant = self._store.by_id(grant_id)
        if grant is None or grant.user_id != user_id:
            raise AutomationAccessError("UNAUTHORIZED")
        return self._authorize(grant, enabled_scopes)

    def _authorize(
        self, grant: AutomationGrant | None, enabled_scopes: frozenset[Scope]
    ) -> EffectiveAccess:
        if (
            grant is None
            or grant.revoked_at_ms is not None
            or grant.expires_at_ms <= self._clock_ms()
        ):
            raise AutomationAccessError("UNAUTHORIZED")
        actor = self._identities.current_actor(grant.user_id)
        if actor is None:
            raise AutomationAccessError("UNAUTHORIZED")
        return effective_access(
            grant_id=grant.id,
            user_id=grant.user_id,
            permissions=grant.permissions,
            actor=actor,
            enabled_scopes=enabled_scopes,
        )
