"""Dormant current Library HTTP router.

The composition root is responsible for deciding when this router is mounted.
This module only adapts validated HTTP input to current application commands.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Annotated, NoReturn, cast

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.typed_route import TypedContractRoute
from app.contracts.http_errors import ErrorResponses, HttpContractError
from app.modules.catalog.application.dto import (
    IgnoreRulesResult,
    LibraryAdminDetails,
    LibraryGrantPage,
    LibraryGrantView,
    LibraryPage,
    admin_details_from_library,
)
from app.modules.catalog.application.dto import (
    LibrarySummary as LibrarySummaryDTO,
)
from app.modules.catalog.application.library_commands import (
    ActivateLibrary,
    CreateLibrary,
    CreateLibraryCommand,
    LibraryStateCommand,
    PauseLibrary,
    ReplaceLibraryIgnoreRules,
    ReplaceLibraryIgnoreRulesCommand,
    ResumeLibrary,
    RevokeLibraryGrant,
    RevokeLibraryGrantCommand,
    SetLibraryGrant,
    SetLibraryGrantCommand,
    UpdateLibrary,
    UpdateLibraryCommand,
)
from app.modules.catalog.application.library_queries import (
    GetAdminLibrary,
    GetLibrary,
    GetLibraryIgnoreRules,
    ListLibraries,
    ListLibraryGrants,
)
from app.modules.catalog.application.ports import (
    LibraryGrantPageQuery,
    LibraryPageQuery,
)
from app.modules.catalog.domain.access import GrantLevel
from app.modules.catalog.domain.errors import CatalogLibraryError
from app.modules.catalog.domain.ignore_rules import IgnoreRule as DomainIgnoreRule
from app.modules.catalog.domain.ignore_rules import IgnoreRuleKind
from app.modules.catalog.domain.library import WritePolicy
from app.modules.catalog.domain.model import OrganizationMode, PathComparison

from .errors import (
    CatalogConflictHttpError,
    CatalogForbiddenHttpError,
    CatalogNotFoundHttpError,
    CatalogValidationHttpError,
    http_error_for,
)
from .mappers import ignore_rule, library_admin, library_grant, library_summary
from .schemas import (
    CreateLibraryRequest,
    DeletedLibraryGrantPayload,
    DeletedLibraryGrantResponse,
    IgnoreRulesPayload,
    IgnoreRulesResponse,
    LibrariesPayload,
    LibrariesResponse,
    LibraryActionPayload,
    LibraryActionResponse,
    LibraryAdminPayload,
    LibraryAdminResponse,
    LibraryGrantPayload,
    LibraryGrantResponse,
    LibraryGrantsPayload,
    LibraryGrantsResponse,
    LibraryPayload,
    LibraryResponse,
    LibraryStateRequest,
    ReplaceIgnoreRulesRequest,
    UpdateLibraryConfigRequest,
    UpsertLibraryGrantRequest,
)
from .schemas import (
    IgnoreRule as IgnoreRuleContract,
)

ActorDependency = Callable[[], str]


@dataclass(frozen=True, slots=True)
class LibraryRouterDependencies:
    actor_id: ActorDependency
    create_library: CreateLibrary
    update_library: UpdateLibrary
    activate_library: ActivateLibrary
    pause_library: PauseLibrary
    resume_library: ResumeLibrary
    set_grant: SetLibraryGrant
    revoke_grant: RevokeLibraryGrant
    replace_ignore_rules: ReplaceLibraryIgnoreRules
    list_libraries: ListLibraries
    get_library: GetLibrary
    get_admin_library: GetAdminLibrary
    list_grants: ListLibraryGrants
    get_ignore_rules: GetLibraryIgnoreRules


_ERROR_RESPONSES = ErrorResponses(
    cast(type[HttpContractError[BaseModel]], CatalogValidationHttpError),
    cast(type[HttpContractError[BaseModel]], CatalogForbiddenHttpError),
    cast(type[HttpContractError[BaseModel]], CatalogNotFoundHttpError),
    cast(type[HttpContractError[BaseModel]], CatalogConflictHttpError),
)


def _raise_catalog_error(error: CatalogLibraryError) -> NoReturn:
    translated = http_error_for(error)
    raise translated from error


def _organization_mode(value: str) -> OrganizationMode:
    return OrganizationMode(value)


def _path_comparison(value: str) -> PathComparison:
    return PathComparison(value)


def _write_policy(value: str) -> WritePolicy:
    return WritePolicy(value)


def _grant_level(value: str) -> GrantLevel:
    return GrantLevel(value)


def _domain_ignore_rule(
    value: IgnoreRuleContract,
) -> DomainIgnoreRule:
    created = DomainIgnoreRule.create(
        kind=IgnoreRuleKind(value.kind),
        pattern=value.pattern,
    )
    return replace(created, enabled=value.enabled)


def create_library_router(dependencies: LibraryRouterDependencies) -> APIRouter:
    """Build an unmounted current router with all application dependencies injected."""

    router = APIRouter(
        prefix="/api/libraries",
        tags=["current-libraries"],
        route_class=TypedContractRoute,
    )
    actor = dependencies.actor_id

    @router.post("", status_code=201)
    def create_library(
        payload: CreateLibraryRequest,
        actor_id: str = Depends(actor),
    ) -> Annotated[LibraryAdminResponse, _ERROR_RESPONSES]:
        try:
            library = dependencies.create_library.execute(
                CreateLibraryCommand(
                    actor_id=actor_id,
                    name=payload.name,
                    requested_root=payload.root_path,
                    organization_mode=_organization_mode(payload.organization_mode),
                    path_comparison=_path_comparison(payload.path_comparison),
                    write_policy=_write_policy(payload.write_policy),
                )
            )
            details = admin_details_from_library(library, GrantLevel.ADMIN)
            return LibraryAdminResponse(
                data=LibraryAdminPayload(library=library_admin(details))
            )
        except CatalogLibraryError as error:
            _raise_catalog_error(error)

    @router.get("")
    def list_libraries(
        cursor: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        actor_id: str = Depends(actor),
    ) -> Annotated[LibrariesResponse, _ERROR_RESPONSES]:
        try:
            page: LibraryPage = dependencies.list_libraries.execute(
                LibraryPageQuery(actor_id=actor_id, cursor=cursor, limit=limit)
            )
            return LibrariesResponse(
                data=LibrariesPayload(
                    libraries=[library_summary(item) for item in page.items],
                    nextCursor=page.next_cursor,
                )
            )
        except CatalogLibraryError as error:
            _raise_catalog_error(error)

    @router.get("/{library_id}")
    def get_library(
        library_id: str,
        actor_id: str = Depends(actor),
    ) -> Annotated[LibraryResponse, _ERROR_RESPONSES]:
        try:
            summary: LibrarySummaryDTO = dependencies.get_library.execute(
                actor_id=actor_id, library_id=library_id
            )
            return LibraryResponse(
                data=LibraryPayload(library=library_summary(summary))
            )
        except CatalogLibraryError as error:
            _raise_catalog_error(error)

    @router.get("/{library_id}/management")
    def get_admin_library(
        library_id: str,
        actor_id: str = Depends(actor),
    ) -> Annotated[LibraryAdminResponse, _ERROR_RESPONSES]:
        try:
            details: LibraryAdminDetails = dependencies.get_admin_library.execute(
                actor_id=actor_id, library_id=library_id
            )
            return LibraryAdminResponse(
                data=LibraryAdminPayload(library=library_admin(details))
            )
        except CatalogLibraryError as error:
            _raise_catalog_error(error)

    @router.patch("/{library_id}")
    def update_library_config(
        library_id: str,
        payload: UpdateLibraryConfigRequest,
        actor_id: str = Depends(actor),
    ) -> Annotated[LibraryAdminResponse, _ERROR_RESPONSES]:
        try:
            updated = dependencies.update_library.execute(
                UpdateLibraryCommand(
                    actor_id=actor_id,
                    library_id=library_id,
                    expected_config_revision=payload.expected_config_revision,
                    name=payload.name,
                    organization_mode=(
                        _organization_mode(payload.organization_mode)
                        if payload.organization_mode is not None
                        else None
                    ),
                    path_comparison=(
                        _path_comparison(payload.path_comparison)
                        if payload.path_comparison is not None
                        else None
                    ),
                    write_policy=(
                        _write_policy(payload.write_policy)
                        if payload.write_policy is not None
                        else None
                    ),
                )
            )
            details = admin_details_from_library(updated, GrantLevel.ADMIN)
            return LibraryAdminResponse(
                data=LibraryAdminPayload(library=library_admin(details))
            )
        except CatalogLibraryError as error:
            _raise_catalog_error(error)

    def _transition(
        use_case: ActivateLibrary | PauseLibrary | ResumeLibrary,
        library_id: str,
        payload: LibraryStateRequest,
        actor_id: str,
    ) -> LibraryActionResponse:
        try:
            updated = use_case.execute(
                LibraryStateCommand(
                    actor_id=actor_id,
                    library_id=library_id,
                    expected_config_revision=payload.expected_config_revision,
                )
            )
            details = admin_details_from_library(updated, GrantLevel.ADMIN)
            return LibraryActionResponse(
                data=LibraryActionPayload(library=library_admin(details))
            )
        except CatalogLibraryError as error:
            _raise_catalog_error(error)

    @router.post("/{library_id}/activate", status_code=202)
    def activate_library(
        library_id: str,
        payload: LibraryStateRequest,
        actor_id: str = Depends(actor),
    ) -> Annotated[LibraryActionResponse, _ERROR_RESPONSES]:
        return _transition(
            dependencies.activate_library,
            library_id,
            payload,
            actor_id,
        )

    @router.post("/{library_id}/pause", status_code=202)
    def pause_library(
        library_id: str,
        payload: LibraryStateRequest,
        actor_id: str = Depends(actor),
    ) -> Annotated[LibraryActionResponse, _ERROR_RESPONSES]:
        return _transition(
            dependencies.pause_library,
            library_id,
            payload,
            actor_id,
        )

    @router.post("/{library_id}/resume", status_code=202)
    def resume_library(
        library_id: str,
        payload: LibraryStateRequest,
        actor_id: str = Depends(actor),
    ) -> Annotated[LibraryActionResponse, _ERROR_RESPONSES]:
        return _transition(
            dependencies.resume_library,
            library_id,
            payload,
            actor_id,
        )

    @router.get("/{library_id}/grants")
    def list_grants(
        library_id: str,
        cursor: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        actor_id: str = Depends(actor),
    ) -> Annotated[LibraryGrantsResponse, _ERROR_RESPONSES]:
        try:
            page: LibraryGrantPage = dependencies.list_grants.execute(
                LibraryGrantPageQuery(
                    actor_id=actor_id,
                    library_id=library_id,
                    cursor=cursor,
                    limit=limit,
                )
            )
            return LibraryGrantsResponse(
                data=LibraryGrantsPayload(
                    grants=[library_grant(item) for item in page.items],
                    nextCursor=page.next_cursor,
                )
            )
        except CatalogLibraryError as error:
            _raise_catalog_error(error)

    @router.put("/{library_id}/grants/{target_user_id}")
    def set_grant(
        library_id: str,
        target_user_id: str,
        payload: UpsertLibraryGrantRequest,
        actor_id: str = Depends(actor),
    ) -> Annotated[LibraryGrantResponse, _ERROR_RESPONSES]:
        try:
            grant: LibraryGrantView = dependencies.set_grant.execute(
                SetLibraryGrantCommand(
                    actor_id=actor_id,
                    library_id=library_id,
                    target_user_id=target_user_id,
                    level=_grant_level(payload.level),
                )
            )
            return LibraryGrantResponse(
                data=LibraryGrantPayload(grant=library_grant(grant))
            )
        except CatalogLibraryError as error:
            _raise_catalog_error(error)

    @router.delete("/{library_id}/grants/{target_user_id}")
    def revoke_grant(
        library_id: str,
        target_user_id: str,
        actor_id: str = Depends(actor),
    ) -> Annotated[DeletedLibraryGrantResponse, _ERROR_RESPONSES]:
        try:
            dependencies.revoke_grant.execute(
                RevokeLibraryGrantCommand(
                    actor_id=actor_id,
                    library_id=library_id,
                    target_user_id=target_user_id,
                )
            )
            return DeletedLibraryGrantResponse(
                data=DeletedLibraryGrantPayload(
                    deleted=True,
                    userId=target_user_id,
                    libraryId=library_id,
                )
            )
        except CatalogLibraryError as error:
            _raise_catalog_error(error)

    @router.get("/{library_id}/ignore-rules")
    def get_ignore_rules(
        library_id: str,
        actor_id: str = Depends(actor),
    ) -> Annotated[IgnoreRulesResponse, _ERROR_RESPONSES]:
        try:
            result: IgnoreRulesResult = dependencies.get_ignore_rules.execute(
                actor_id=actor_id, library_id=library_id
            )
            return IgnoreRulesResponse(
                data=IgnoreRulesPayload(
                    rules=[ignore_rule(item) for item in result.rules],
                    configRevision=result.config_revision,
                )
            )
        except CatalogLibraryError as error:
            _raise_catalog_error(error)

    @router.put("/{library_id}/ignore-rules")
    def replace_ignore_rules(
        library_id: str,
        payload: ReplaceIgnoreRulesRequest,
        actor_id: str = Depends(actor),
    ) -> Annotated[IgnoreRulesResponse, _ERROR_RESPONSES]:
        try:
            result: IgnoreRulesResult = dependencies.replace_ignore_rules.execute(
                ReplaceLibraryIgnoreRulesCommand(
                    actor_id=actor_id,
                    library_id=library_id,
                    expected_config_revision=payload.expected_config_revision,
                    rules=tuple(_domain_ignore_rule(item) for item in payload.rules),
                )
            )
            return IgnoreRulesResponse(
                data=IgnoreRulesPayload(
                    rules=[ignore_rule(item) for item in result.rules],
                    configRevision=result.config_revision,
                )
            )
        except CatalogLibraryError as error:
            _raise_catalog_error(error)

    return router


__all__ = ["LibraryRouterDependencies", "create_library_router"]
