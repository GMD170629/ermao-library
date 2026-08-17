"""Named Library write use cases with explicit transaction ownership."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn

from app.modules.catalog.application.dto import IgnoreRulesResult, LibraryGrantView
from app.modules.catalog.application.ports import (
    AuditEvent,
    Clock,
    IdGenerator,
    LibraryQueryRepository,
    LibraryRootPreflight,
    LibraryUnitOfWork,
    LibraryUowFactory,
    OutboxEvent,
    RootRegistry,
    ScopeEpochGenerator,
    SystemCreateLibraryPolicy,
)
from app.modules.catalog.domain.access import (
    GrantLevel,
    LibraryGrant,
)
from app.modules.catalog.domain.errors import (
    FinalAdministratorRequired,
    GrantTargetNotFound,
    LibraryConfigConflict,
    LibraryConfigurationFrozen,
    LibraryForbidden,
    LibraryNotFound,
    LibraryRemoving,
    NoLibraryChanges,
    RootIdentityChanged,
    RootUnwritable,
    ScopeEpochExhausted,
)
from app.modules.catalog.domain.ignore_rules import IgnoreRule, replace_rules
from app.modules.catalog.domain.library import Library, LibraryControlState, WritePolicy
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.domain.root_paths import (
    RegisteredRoot,
    ensure_root_is_disjoint,
)


def _rollback_and_raise(uow: LibraryUnitOfWork, error: BaseException) -> NoReturn:
    uow.rollback()
    raise error


def _event_payload(
    **values: str | int | bool,
) -> tuple[tuple[str, str | int | bool], ...]:
    return tuple(sorted(values.items()))


def _next_epoch(generator: ScopeEpochGenerator) -> int:
    epoch = generator.next_scope_epoch()
    if isinstance(epoch, bool) or not 1 <= epoch <= (1 << 63) - 1:
        raise ScopeEpochExhausted()
    return epoch


def _ensure_not_removing(uow: LibraryUnitOfWork, library: Library) -> None:
    if library.control_state is LibraryControlState.REMOVING:
        _rollback_and_raise(uow, LibraryRemoving())


@dataclass(frozen=True, slots=True)
class CreateLibraryCommand:
    actor_id: str
    name: str
    requested_root: str
    organization_mode: OrganizationMode
    path_comparison: PathComparison
    write_policy: WritePolicy


class CreateLibrary:
    def __init__(
        self,
        *,
        unit_of_work_factory: LibraryUowFactory,
        create_policy: SystemCreateLibraryPolicy,
        root_preflight: LibraryRootPreflight,
        root_registry: RootRegistry,
        id_generator: IdGenerator,
        scope_epoch_generator: ScopeEpochGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = unit_of_work_factory
        self._create_policy = create_policy
        self._root_preflight = root_preflight
        self._root_registry = root_registry
        self._ids = id_generator
        self._epochs = scope_epoch_generator
        self._clock = clock

    def execute(self, command: CreateLibraryCommand) -> Library:
        self._create_policy.authorize(command.actor_id)
        first_observation = self._root_preflight.preflight(
            command.requested_root,
            path_comparison=command.path_comparison,
        )
        ensure_root_is_disjoint(
            first_observation.claim,
            tuple(item.claim for item in self._root_registry.reserved_roots()),
        )
        if (
            command.write_policy is WritePolicy.READ_WRITE
            and not first_observation.writable
        ):
            raise RootUnwritable()
        library_id = self._ids.new_id()
        owner_token = self._ids.new_id()
        with self._root_registry.acquire(owner_token=owner_token):
            observation = self._root_preflight.revalidate(
                command.requested_root,
                first_observation,
                path_comparison=command.path_comparison,
            )
            if (
                observation.filesystem_identity != first_observation.filesystem_identity
                or observation.registered_root != first_observation.registered_root
            ):
                raise RootIdentityChanged()
            ensure_root_is_disjoint(
                observation.claim,
                tuple(item.claim for item in self._root_registry.reserved_roots()),
            )
            if (
                command.write_policy is WritePolicy.READ_WRITE
                and not observation.writable
            ):
                raise RootUnwritable()
            now = self._clock.now()
            library = Library.create(
                library_id=library_id,
                name=command.name,
                root=observation.registered_root,
                organization_mode=command.organization_mode,
                path_comparison=command.path_comparison,
                write_policy=command.write_policy,
                now=now,
            )
            with self._uow_factory() as uow:
                uow.users.ensure_can_create_library(command.actor_id)
                uow.libraries.insert(library)
                creator_grant = LibraryGrant(
                    user_id=command.actor_id,
                    library_id=library.id,
                    level=GrantLevel.ADMIN,
                    scope_epoch=_next_epoch(self._epochs),
                )
                if not uow.grants.save_preserving_last_admin(creator_grant):
                    raise FinalAdministratorRequired()
                uow.users.increment_authz_version(command.actor_id)
                uow.audit.append(
                    AuditEvent(
                        event_type="LIBRARY_CREATED",
                        actor_id=command.actor_id,
                        library_id=library.id,
                        payload=_event_payload(
                            organizationMode=library.organization_mode.value
                        ),
                    )
                )
                uow.outbox.append(
                    OutboxEvent(
                        event_type="LIBRARY_CREATED",
                        aggregate_id=library.id,
                        actor_id=command.actor_id,
                    )
                )
                uow.commit()
            return library


@dataclass(frozen=True, slots=True)
class UpdateLibraryCommand:
    actor_id: str
    library_id: str
    expected_config_revision: int
    name: str | None = None
    organization_mode: OrganizationMode | None = None
    path_comparison: PathComparison | None = None
    write_policy: WritePolicy | None = None


class UpdateLibrary:
    def __init__(
        self,
        *,
        unit_of_work_factory: LibraryUowFactory,
        query_port: LibraryQueryRepository,
        root_preflight: LibraryRootPreflight,
        root_registry: RootRegistry,
        id_generator: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = unit_of_work_factory
        self._queries = query_port
        self._root_preflight = root_preflight
        self._root_registry = root_registry
        self._ids = id_generator
        self._clock = clock

    def execute(self, command: UpdateLibraryCommand) -> Library:
        snapshot = self._queries.get_manageable(command.actor_id, command.library_id)
        if snapshot is None or snapshot.grant.level is not GrantLevel.ADMIN:
            raise LibraryNotFound()
        library = snapshot.library
        if library.control_state is LibraryControlState.REMOVING:
            raise LibraryRemoving()
        if library.config_revision != command.expected_config_revision:
            raise LibraryConfigConflict()
        if (
            command.name is None
            and command.organization_mode is None
            and command.path_comparison is None
            and command.write_policy is None
        ):
            raise NoLibraryChanges()
        if library.control_state is not LibraryControlState.DRAFT and (
            command.organization_mode is not None or command.path_comparison is not None
        ):
            raise LibraryConfigurationFrozen()

        if command.path_comparison is not None:
            first_observation = self._root_preflight.preflight(
                library.root.canonical_path,
                path_comparison=command.path_comparison,
            )
            with self._root_registry.acquire(owner_token=self._ids.new_id()):
                observation = self._root_preflight.revalidate(
                    library.root.canonical_path,
                    first_observation,
                    path_comparison=command.path_comparison,
                )
                if (
                    observation.filesystem_identity
                    != first_observation.filesystem_identity
                    or observation.registered_root != first_observation.registered_root
                    or observation.canonical_path != library.root.canonical_path
                ):
                    raise RootIdentityChanged()
                desired_write_policy = command.write_policy or library.write_policy
                if (
                    desired_write_policy is WritePolicy.READ_WRITE
                    and not observation.writable
                ):
                    raise RootUnwritable()
                ensure_root_is_disjoint(
                    observation.claim,
                    tuple(
                        item.claim
                        for item in self._root_registry.reserved_roots()
                        if item.library_id != library.id
                    ),
                )
                return self._execute_database_changes(
                    command,
                    snapshot=library,
                    registered_root=observation.registered_root,
                )

        if (
            library.write_policy is WritePolicy.READ_ONLY
            and command.write_policy is WritePolicy.READ_WRITE
        ):
            observation = self._root_preflight.preflight(
                library.root.canonical_path,
                path_comparison=library.path_comparison,
            )
            if observation.registered_root != library.root:
                raise RootIdentityChanged()
            if not observation.writable:
                raise RootUnwritable()
        return self._execute_database_changes(
            command,
            snapshot=library,
            registered_root=None,
        )

    def _execute_database_changes(
        self,
        command: UpdateLibraryCommand,
        *,
        snapshot: Library,
        registered_root: RegisteredRoot | None,
    ) -> Library:
        with self._uow_factory() as uow:
            current = uow.libraries.get_for_update(command.library_id)
            if current is None:
                _rollback_and_raise(uow, LibraryNotFound())
            grant = uow.grants.get(command.actor_id, command.library_id)
            if grant is None or grant.level is not GrantLevel.ADMIN:
                _rollback_and_raise(uow, LibraryForbidden())
            _ensure_not_removing(uow, current)
            if (
                current.config_revision != command.expected_config_revision
                or current.root != snapshot.root
            ):
                _rollback_and_raise(uow, LibraryConfigConflict())
            desired_write_policy = command.write_policy or current.write_policy
            if (
                current.write_policy is WritePolicy.READ_WRITE
                and desired_write_policy is WritePolicy.READ_ONLY
            ):
                uow.write_policy.ensure_read_only_safe(command.library_id)
            updated = current.update_draft(
                name=command.name,
                organization_mode=command.organization_mode,
                path_comparison=command.path_comparison,
                write_policy=command.write_policy,
                root=registered_root,
                now=self._clock.now(),
            )
            if not uow.libraries.update_if_revision(
                updated,
                expected_config_revision=command.expected_config_revision,
            ):
                raise LibraryConfigConflict()
            uow.audit.append(
                AuditEvent(
                    event_type="LIBRARY_UPDATED",
                    actor_id=command.actor_id,
                    library_id=updated.id,
                )
            )
            uow.outbox.append(
                OutboxEvent(
                    event_type="LIBRARY_UPDATED",
                    aggregate_id=updated.id,
                    actor_id=command.actor_id,
                )
            )
            uow.commit()
            return updated


@dataclass(frozen=True, slots=True)
class LibraryStateCommand:
    actor_id: str
    library_id: str
    expected_config_revision: int


class _TransitionLibrary:
    event_type: str

    def __init__(
        self, *, unit_of_work_factory: LibraryUowFactory, clock: Clock
    ) -> None:
        self._uow_factory = unit_of_work_factory
        self._clock = clock

    def execute(self, command: LibraryStateCommand) -> Library:
        with self._uow_factory() as uow:
            current = uow.libraries.get_for_update(command.library_id)
            if current is None:
                _rollback_and_raise(uow, LibraryNotFound())
            grant = uow.grants.get(command.actor_id, command.library_id)
            if grant is None or grant.level is not GrantLevel.ADMIN:
                _rollback_and_raise(uow, LibraryForbidden())
            if current.config_revision != command.expected_config_revision:
                _rollback_and_raise(uow, LibraryConfigConflict())
            updated = self._transition(current, now=self._clock.now())
            if not uow.libraries.update_if_revision(
                updated,
                expected_config_revision=command.expected_config_revision,
            ):
                raise LibraryConfigConflict()
            uow.audit.append(AuditEvent(self.event_type, command.actor_id, updated.id))
            uow.outbox.append(
                OutboxEvent(self.event_type, updated.id, command.actor_id)
            )
            uow.commit()
            return updated

    def _transition(self, current: Library, *, now: datetime) -> Library:
        raise NotImplementedError


class ActivateLibrary(_TransitionLibrary):
    event_type = "LIBRARY_ACTIVATION_REQUESTED"

    def _transition(self, current: Library, *, now: datetime) -> Library:
        return current.activate(now=now)


class PauseLibrary(_TransitionLibrary):
    event_type = "LIBRARY_PAUSED"

    def _transition(self, current: Library, *, now: datetime) -> Library:
        return current.pause(now=now)


class ResumeLibrary(_TransitionLibrary):
    event_type = "LIBRARY_RESUMED"

    def _transition(self, current: Library, *, now: datetime) -> Library:
        return current.resume(now=now)


@dataclass(frozen=True, slots=True)
class SetLibraryGrantCommand:
    actor_id: str
    library_id: str
    target_user_id: str
    level: GrantLevel


class SetLibraryGrant:
    def __init__(
        self,
        *,
        unit_of_work_factory: LibraryUowFactory,
        scope_epoch_generator: ScopeEpochGenerator,
    ) -> None:
        self._uow_factory = unit_of_work_factory
        self._epochs = scope_epoch_generator

    def execute(self, command: SetLibraryGrantCommand) -> LibraryGrantView:
        with self._uow_factory() as uow:
            actor_grant = uow.grants.get(command.actor_id, command.library_id)
            if actor_grant is None or actor_grant.level is not GrantLevel.ADMIN:
                _rollback_and_raise(uow, LibraryForbidden())
            library = uow.libraries.get_for_update(command.library_id)
            if library is None:
                _rollback_and_raise(uow, LibraryNotFound())
            _ensure_not_removing(uow, library)
            try:
                uow.users.ensure_active_user(command.target_user_id)
            except GrantTargetNotFound as error:
                _rollback_and_raise(uow, error)
            grant = LibraryGrant(
                user_id=command.target_user_id,
                library_id=command.library_id,
                level=command.level,
                scope_epoch=_next_epoch(self._epochs),
            )
            if not uow.grants.save_preserving_last_admin(grant):
                _rollback_and_raise(uow, FinalAdministratorRequired())
            uow.users.increment_authz_version(command.target_user_id)
            uow.audit.append(
                AuditEvent(
                    "LIBRARY_GRANT_CHANGED",
                    command.actor_id,
                    command.library_id,
                    _event_payload(
                        targetUserId=command.target_user_id,
                        level=command.level.value,
                    ),
                )
            )
            uow.outbox.append(
                OutboxEvent(
                    "LIBRARY_GRANT_CHANGED",
                    command.library_id,
                    command.actor_id,
                    _event_payload(targetUserId=command.target_user_id),
                )
            )
            uow.commit()
            return LibraryGrantView(
                user_id=grant.user_id,
                library_id=grant.library_id,
                level=grant.level,
                scope_epoch=grant.scope_epoch,
            )


# The explicit name makes the intent clear to delivery adapters while both
# commands share exactly one ACL mutation implementation.
ChangeLibraryGrant = SetLibraryGrant
ChangeLibraryGrantCommand = SetLibraryGrantCommand


@dataclass(frozen=True, slots=True)
class RevokeLibraryGrantCommand:
    actor_id: str
    library_id: str
    target_user_id: str


class RevokeLibraryGrant:
    def __init__(
        self,
        *,
        unit_of_work_factory: LibraryUowFactory,
        scope_epoch_generator: ScopeEpochGenerator,
    ) -> None:
        self._uow_factory = unit_of_work_factory
        self._epochs = scope_epoch_generator

    def execute(self, command: RevokeLibraryGrantCommand) -> None:
        with self._uow_factory() as uow:
            actor_grant = uow.grants.get(command.actor_id, command.library_id)
            if actor_grant is None or actor_grant.level is not GrantLevel.ADMIN:
                _rollback_and_raise(uow, LibraryForbidden())
            library = uow.libraries.get_for_update(command.library_id)
            if library is None:
                _rollback_and_raise(uow, LibraryNotFound())
            _ensure_not_removing(uow, library)
            target = uow.grants.get(command.target_user_id, command.library_id)
            if target is None:
                _rollback_and_raise(uow, LibraryNotFound())
            revoked_scope_epoch = _next_epoch(self._epochs)
            if not uow.grants.delete_preserving_last_admin(
                command.target_user_id, command.library_id
            ):
                _rollback_and_raise(uow, FinalAdministratorRequired())
            uow.users.increment_authz_version(command.target_user_id)
            uow.audit.append(
                AuditEvent(
                    "LIBRARY_GRANT_REVOKED",
                    command.actor_id,
                    command.library_id,
                    _event_payload(targetUserId=command.target_user_id),
                )
            )
            uow.outbox.append(
                OutboxEvent(
                    "LIBRARY_GRANT_REVOKED",
                    command.library_id,
                    command.actor_id,
                    _event_payload(
                        targetUserId=command.target_user_id,
                        scopeEpoch=revoked_scope_epoch,
                    ),
                )
            )
            uow.commit()


@dataclass(frozen=True, slots=True)
class ReplaceLibraryIgnoreRulesCommand:
    actor_id: str
    library_id: str
    expected_config_revision: int
    rules: tuple[IgnoreRule, ...]


class ReplaceLibraryIgnoreRules:
    def __init__(
        self, *, unit_of_work_factory: LibraryUowFactory, clock: Clock
    ) -> None:
        self._uow_factory = unit_of_work_factory
        self._clock = clock

    def execute(self, command: ReplaceLibraryIgnoreRulesCommand) -> IgnoreRulesResult:
        rules = replace_rules(command.rules)
        with self._uow_factory() as uow:
            library = uow.libraries.get_for_update(command.library_id)
            if library is None:
                _rollback_and_raise(uow, LibraryNotFound())
            grant = uow.grants.get(command.actor_id, command.library_id)
            if grant is None or grant.level is not GrantLevel.ADMIN:
                _rollback_and_raise(uow, LibraryForbidden())
            _ensure_not_removing(uow, library)
            if library.config_revision != command.expected_config_revision:
                _rollback_and_raise(uow, LibraryConfigConflict())
            next_revision = library.config_revision + 1
            uow.ignore_rules.replace(
                command.library_id,
                rules,
                expected_config_revision=library.config_revision,
                next_config_revision=next_revision,
            )
            updated = library.bump_config_revision(now=self._clock.now())
            if not uow.libraries.update_if_revision(
                updated, expected_config_revision=library.config_revision
            ):
                raise LibraryConfigConflict()
            uow.audit.append(
                AuditEvent(
                    "LIBRARY_IGNORE_RULES_REPLACED", command.actor_id, library.id
                )
            )
            uow.outbox.append(
                OutboxEvent(
                    "LIBRARY_IGNORE_RULES_REPLACED", library.id, command.actor_id
                )
            )
            uow.commit()
            return IgnoreRulesResult(library.id, updated.config_revision, rules)
