from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.error_handlers import typed_http_error_handler
from app.contracts.http_errors import HttpContractError
from app.modules.catalog.application.dto import (
    IgnoreRulesResult,
    LibraryAdminDetails,
    LibraryGrantPage,
    LibraryGrantView,
    LibraryPage,
    LibrarySummary,
)
from app.modules.catalog.domain.access import GrantLevel
from app.modules.catalog.domain.errors import (
    AclConflict,
    CatalogLibraryError,
    InvalidPageLimit,
    LibraryConfigConflict,
    LibraryCreateDenied,
    LibraryForbidden,
    LibraryNotFound,
    RootExpansionNotAllowed,
    RootNotAbsolute,
    RootNotDirectory,
    RootOverlapConflict,
    RootProtected,
    RootRequired,
    RootUnavailable,
    RootUnreadable,
)
from app.modules.catalog.domain.ignore_rules import IgnoreRule, IgnoreRuleKind
from app.modules.catalog.domain.library import (
    Library,
    LibraryControlState,
    LibraryHealth,
    WritePolicy,
)
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.domain.root_paths import RootObservation
from app.modules.catalog.presentation.errors import http_error_for
from app.modules.catalog.presentation.http import (
    LibraryRouterDependencies,
    create_library_router,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _summary() -> LibrarySummary:
    return LibrarySummary(
        id="library-1",
        name="Books",
        organization_mode=OrganizationMode.VOLUMES,
        control_state=LibraryControlState.ACTIVE,
        observed_health=LibraryHealth.HEALTHY,
        config_revision=2,
        grant_level=GrantLevel.READ,
        topology_version=1,
        path_comparison=PathComparison.SENSITIVE,
        write_policy=WritePolicy.READ_ONLY,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _admin() -> LibraryAdminDetails:
    summary = _summary()
    return LibraryAdminDetails(
        id=summary.id,
        name=summary.name,
        organization_mode=summary.organization_mode,
        control_state=summary.control_state,
        observed_health=summary.observed_health,
        config_revision=summary.config_revision,
        grant_level=summary.grant_level,
        topology_version=summary.topology_version,
        path_comparison=summary.path_comparison,
        write_policy=summary.write_policy,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        root_path="/srv/books",
        root_path_key="/srv/books",
    )


@dataclass(frozen=True, slots=True)
class _Actor:
    def __call__(self) -> str:
        return "user-1"


@dataclass(frozen=True, slots=True)
class _ListLibraries:
    def execute(self, query: object) -> LibraryPage:
        return LibraryPage(items=(_summary(),), next_cursor=None)


@dataclass(frozen=True, slots=True)
class _GetLibrary:
    def execute(self, *, actor_id: str, library_id: str) -> LibrarySummary:
        if library_id != "library-1":
            raise LibraryNotFound()
        return _summary()


@dataclass(frozen=True, slots=True)
class _GetAdminLibrary:
    def execute(self, *, actor_id: str, library_id: str) -> LibraryAdminDetails:
        if library_id != "library-1":
            raise LibraryNotFound()
        return _admin()


@dataclass(frozen=True, slots=True)
class _GetIgnoreRules:
    def execute(self, *, actor_id: str, library_id: str) -> IgnoreRulesResult:
        return IgnoreRulesResult(library_id, 2, ())


def _domain_library() -> Library:
    return Library.create(
        library_id="library-1",
        name="Books",
        root=RootObservation(
            canonical_path="/srv/books",
            root_path_key="/srv/books",
            components=("srv", "books"),
            filesystem_identity="device:1:2",
            writable=False,
        ),
        organization_mode=OrganizationMode.VOLUMES,
        path_comparison=PathComparison.SENSITIVE,
        write_policy=WritePolicy.READ_ONLY,
        now=_NOW,
    )


@dataclass(frozen=True, slots=True)
class _Create:
    def execute(self, command: object) -> Library:
        return _domain_library()


@dataclass(frozen=True, slots=True)
class _ForbiddenCreate:
    def execute(self, command: object) -> Library:
        raise LibraryCreateDenied()


@dataclass(frozen=True, slots=True)
class _Update:
    def execute(self, command: object) -> Library:
        return _domain_library()


@dataclass(frozen=True, slots=True)
class _ConflictUpdate:
    def execute(self, command: object) -> Library:
        raise LibraryConfigConflict()


@dataclass(frozen=True, slots=True)
class _State:
    def execute(self, command: object) -> Library:
        return _domain_library()


@dataclass(frozen=True, slots=True)
class _SetGrant:
    def execute(self, command: object) -> LibraryGrantView:
        return LibraryGrantView("user-2", "library-1", GrantLevel.READ, 1)


@dataclass(frozen=True, slots=True)
class _Revoke:
    def execute(self, command: object) -> None:
        return None


@dataclass(frozen=True, slots=True)
class _ListGrants:
    def execute(self, query: object) -> LibraryGrantPage:
        return LibraryGrantPage(
            items=(LibraryGrantView("user-2", "library-1", GrantLevel.READ, 1),),
            next_cursor="next-grant",
        )


@dataclass(frozen=True, slots=True)
class _ReplaceRules:
    def execute(self, command: object) -> IgnoreRulesResult:
        rule = IgnoreRule.create(kind=IgnoreRuleKind.NAME, pattern="draft")
        return IgnoreRulesResult("library-1", 3, (rule,))


def _client() -> TestClient:
    dependencies = LibraryRouterDependencies(
        actor_id=_Actor(),
        create_library=object(),
        update_library=object(),
        activate_library=object(),
        pause_library=object(),
        resume_library=object(),
        set_grant=object(),
        revoke_grant=object(),
        replace_ignore_rules=object(),
        list_libraries=_ListLibraries(),
        get_library=_GetLibrary(),
        get_admin_library=_GetAdminLibrary(),
        list_grants=object(),
        get_ignore_rules=_GetIgnoreRules(),
    )
    app = FastAPI(
        title="Shuku Starship current Library API",
        version="current-v2",
    )
    app.add_exception_handler(HttpContractError, typed_http_error_handler)
    app.include_router(create_library_router(dependencies))
    return TestClient(app)


def _mutation_client(
    update: object | None = None,
    create: object | None = None,
) -> TestClient:
    dependencies = LibraryRouterDependencies(
        actor_id=_Actor(),
        create_library=create or _Create(),
        update_library=update or _Update(),
        activate_library=_State(),
        pause_library=_State(),
        resume_library=_State(),
        set_grant=_SetGrant(),
        revoke_grant=_Revoke(),
        replace_ignore_rules=_ReplaceRules(),
        list_libraries=_ListLibraries(),
        get_library=_GetLibrary(),
        get_admin_library=_GetAdminLibrary(),
        list_grants=_ListGrants(),
        get_ignore_rules=_GetIgnoreRules(),
    )
    app = FastAPI(
        title="Shuku Starship current Library API",
        version="current-v2",
    )
    app.add_exception_handler(HttpContractError, typed_http_error_handler)
    app.include_router(create_library_router(dependencies))
    return TestClient(app)


def test_current_library_routes_have_no_legacy_or_mutating_file_routes() -> None:
    client = _client()
    paths = {route.path for route in client.app.routes}
    methods_by_path: dict[str, set[str]] = {}
    for route in client.app.routes:
        if hasattr(route, "methods"):
            methods_by_path.setdefault(route.path, set()).update(route.methods)

    assert "/api/libraries" in paths
    assert methods_by_path["/api/libraries"] == {"GET", "POST"}
    assert "/api/libraries/{library_id}" in paths
    assert "/api/libraries/{library_id}/management" in paths
    assert methods_by_path["/api/libraries/{library_id}/management"] == {"GET"}
    assert methods_by_path["/api/libraries/{library_id}"] == {"GET", "PATCH"}
    for action in ("activate", "pause", "resume"):
        assert methods_by_path[f"/api/libraries/{{library_id}}/{action}"] == {"POST"}
    assert methods_by_path["/api/libraries/{library_id}/grants"] == {"GET"}
    assert methods_by_path["/api/libraries/{library_id}/grants/{target_user_id}"] == {
        "PUT",
        "DELETE",
    }
    assert "/api/libraries/{library_id}/ignore-rules" in paths
    assert methods_by_path["/api/libraries/{library_id}/ignore-rules"] == {
        "GET",
        "PUT",
    }
    assert not any("monitor" in path for path in paths)
    assert not any(action in path for path in paths for action in ("relocate", "scan"))


def test_current_library_router_remains_dormant_in_production_app() -> None:
    from app.main import app as production_app

    production_paths = {route.path for route in production_app.routes}

    assert not any(path.startswith("/api/libraries") for path in production_paths)


def test_safe_and_admin_library_projections_are_separate() -> None:
    client = _client()

    safe = client.get("/api/libraries/library-1")
    admin = client.get("/api/libraries/library-1/management")

    assert safe.status_code == 200
    assert safe.json()["data"]["library"]["name"] == "Books"
    assert "rootPath" not in safe.json()["data"]["library"]
    assert admin.status_code == 200
    assert admin.json()["data"]["library"]["rootPath"] == "/srv/books"


def test_current_list_and_missing_library_use_safe_contracts() -> None:
    client = _client()

    listed = client.get("/api/libraries")
    missing = client.get("/api/libraries/missing")

    assert listed.status_code == 200
    assert "rootPath" not in listed.json()["data"]["libraries"][0]
    assert missing.status_code == 404
    assert missing.json() == {
        "ok": False,
        "error": {"code": "LIBRARY_NOT_FOUND", "message": "Library operation failed"},
    }


def test_current_mutation_and_acl_endpoints_keep_declared_statuses() -> None:
    client = _mutation_client()
    create_payload = {
        "name": "Books",
        "rootPath": "/srv/books",
        "organizationMode": "VOLUMES",
        "pathComparison": "SENSITIVE",
    }

    assert client.post("/api/libraries", json=create_payload).status_code == 201
    assert (
        client.patch(
            "/api/libraries/library-1",
            json={"expectedConfigRevision": 1, "name": "Books 2"},
        ).status_code
        == 200
    )
    for action in ("activate", "pause", "resume"):
        assert (
            client.post(
                f"/api/libraries/library-1/{action}",
                json={"expectedConfigRevision": 1},
            ).status_code
            == 202
        )

    grants = client.get("/api/libraries/library-1/grants?limit=10")
    assert grants.status_code == 200
    assert grants.json()["data"]["nextCursor"] == "next-grant"
    assert (
        client.put(
            "/api/libraries/library-1/grants/user-2", json={"level": "READ"}
        ).status_code
        == 200
    )
    assert client.delete("/api/libraries/library-1/grants/user-2").status_code == 200

    assert client.get("/api/libraries/library-1/ignore-rules").status_code == 200
    assert (
        client.put(
            "/api/libraries/library-1/ignore-rules",
            json={
                "expectedConfigRevision": 1,
                "rules": [{"kind": "NAME", "pattern": "draft", "enabled": True}],
            },
        ).status_code
        == 200
    )


def test_current_create_validation_returns_422() -> None:
    response = _mutation_client().post("/api/libraries", json={})

    assert response.status_code == 422


def test_current_config_revision_conflict_returns_409() -> None:
    response = _mutation_client(_ConflictUpdate()).patch(
        "/api/libraries/library-1",
        json={"expectedConfigRevision": 1, "name": "Books 2"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFIG_REVISION_CONFLICT"


def test_current_verified_create_denial_is_403_but_missing_management_is_404() -> None:
    client = _mutation_client(create=_ForbiddenCreate())
    create_response = client.post(
        "/api/libraries",
        json={
            "name": "Books",
            "rootPath": "/srv/books",
            "organizationMode": "VOLUMES",
            "pathComparison": "SENSITIVE",
        },
    )
    missing_management = client.get("/api/libraries/missing/management")

    assert create_response.status_code == 403
    assert create_response.json()["error"]["code"] == "LIBRARY_CREATE_DENIED"
    assert missing_management.status_code == 404


def test_not_found_translation_does_not_expose_domain_detail() -> None:
    translated = http_error_for(LibraryNotFound("/srv/private/books"))

    assert translated.status_code == 404
    assert "/srv/private" not in str(translated.body)


def test_anti_enumeration_forbidden_error_uses_not_found_contract() -> None:
    translated = http_error_for(LibraryForbidden("actor lacks grant"))

    assert translated.status_code == 404
    assert translated.body.code == "LIBRARY_NOT_FOUND"


@pytest.mark.parametrize(
    ("error_type", "status_code"),
    [
        (RootRequired, 422),
        (RootNotAbsolute, 422),
        (RootExpansionNotAllowed, 422),
        (RootUnavailable, 409),
        (RootNotDirectory, 409),
        (RootUnreadable, 409),
        (RootProtected, 409),
        (InvalidPageLimit, 422),
    ],
)
def test_root_error_mapping_is_stable_and_does_not_expose_path(
    error_type: type[CatalogLibraryError], status_code: int
) -> None:
    translated = http_error_for(error_type("/private/root"))

    assert translated.status_code == status_code
    assert "/private/root" not in str(translated.body)


@pytest.mark.parametrize("error_type", [RootOverlapConflict, AclConflict])
def test_current_conflict_codes_map_to_409_without_leaking_detail(
    error_type: type[CatalogLibraryError],
) -> None:
    translated = http_error_for(error_type("/private/root"))

    assert translated.status_code == 409
    assert translated.body.code == error_type.code
    assert "/private/root" not in str(translated.body)


def test_independent_current_v2_openapi_artifact_lists_only_current_surface() -> None:
    artifact_path = (
        Path(__file__).parents[4] / "docs" / "openapi-audit" / "current-v2.json"
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    paths = artifact["paths"]
    runtime_paths = set(_client().app.openapi()["paths"])

    assert artifact["info"]["version"] == "current-v2"
    assert runtime_paths == set(paths)
    assert "/api/libraries/{library_id}/config" not in paths
    assert "/api/libraries/{library_id}/management" in paths
    assert "/api/libraries/{library_id}/grants/{target_user_id}" in paths
    assert not any("monitor" in path for path in paths)
    assert not any(action in path for path in paths for action in ("relocate", "scan"))
    assert artifact["x-current-contract"]["ordinaryProjectionExcludes"] == [
        "rootPath",
        "rootPathKey",
    ]
    assert artifact["x-current-contract"]["conflictCodes"] == [
        "ACL_CONFLICT",
        "ROOT_PATH_OVERLAP",
        "ROOT_UNAVAILABLE",
    ]
    schemas = artifact["components"]["schemas"]
    assert "rootPath" not in schemas["LibrarySummary"]["properties"]
    assert "rootPath" in schemas["LibraryAdminView"]["properties"]
    assert "nextCursor" in schemas["LibraryGrantsPayload"]["properties"]
