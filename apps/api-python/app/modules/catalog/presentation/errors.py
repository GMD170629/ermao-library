"""HTTP translation for current catalog application errors."""

from __future__ import annotations

from app.contracts.http_errors import HttpContractError
from app.modules.catalog.domain.errors import (
    AclConflict,
    CatalogLibraryError,
    DuplicateIgnoreRule,
    FinalAdministratorRequired,
    GrantTargetNotFound,
    InvalidGrantLevel,
    InvalidIgnoreRule,
    InvalidLibraryName,
    InvalidLibraryTransition,
    InvalidPageLimit,
    InvalidRootObservation,
    LibraryAuthorizationDenied,
    LibraryConfigConflict,
    LibraryConfigurationFrozen,
    LibraryCreateDenied,
    LibraryForbidden,
    LibraryNotFound,
    LibraryRemoving,
    NoLibraryChanges,
    RootExpansionNotAllowed,
    RootIdentityChanged,
    RootNotAbsolute,
    RootNotDirectory,
    RootOverlapConflict,
    RootProtected,
    RootRegistryBusy,
    RootRequired,
    RootUnavailable,
    RootUnreadable,
    RootUnwritable,
    ScopeEpochExhausted,
    ScopeEpochInvalid,
)

from .schemas import LibraryErrorBody


class CatalogValidationHttpError(HttpContractError[LibraryErrorBody]):
    status_code = 422
    body_model = LibraryErrorBody


class CatalogForbiddenHttpError(HttpContractError[LibraryErrorBody]):
    status_code = 403
    body_model = LibraryErrorBody


class CatalogNotFoundHttpError(HttpContractError[LibraryErrorBody]):
    status_code = 404
    body_model = LibraryErrorBody


class CatalogConflictHttpError(HttpContractError[LibraryErrorBody]):
    status_code = 409
    body_model = LibraryErrorBody


_VALIDATION_ERRORS = (
    InvalidGrantLevel,
    InvalidIgnoreRule,
    DuplicateIgnoreRule,
    InvalidPageLimit,
    InvalidLibraryName,
    InvalidRootObservation,
    NoLibraryChanges,
    RootExpansionNotAllowed,
    RootNotAbsolute,
    RootRequired,
)
_NOT_FOUND_ERRORS = (LibraryNotFound, LibraryForbidden, GrantTargetNotFound)
_FORBIDDEN_ERRORS = (LibraryAuthorizationDenied, LibraryCreateDenied)
_CONFLICT_ERRORS = (
    AclConflict,
    FinalAdministratorRequired,
    InvalidLibraryTransition,
    LibraryConfigConflict,
    LibraryConfigurationFrozen,
    LibraryRemoving,
    RootIdentityChanged,
    RootNotDirectory,
    RootOverlapConflict,
    RootProtected,
    RootRegistryBusy,
    RootUnavailable,
    RootUnreadable,
    RootUnwritable,
    ScopeEpochExhausted,
    ScopeEpochInvalid,
)

_NOT_FOUND_CODES = {"LIBRARY_NOT_FOUND", "GRANT_TARGET_NOT_FOUND"}
_FORBIDDEN_CODES = {"LIBRARY_AUTHORIZATION_DENIED", "LIBRARY_CREATE_DENIED"}
_VALIDATION_CODES = {
    "INVALID_GRANT_LEVEL",
    "INVALID_IGNORE_RULE",
    "DUPLICATE_IGNORE_RULE",
    "INVALID_PAGE_LIMIT",
    "INVALID_LIBRARY_NAME",
    "INVALID_ROOT_OBSERVATION",
    "NO_LIBRARY_CHANGES",
    "ROOT_EXPANSION_NOT_ALLOWED",
    "ROOT_NOT_ABSOLUTE",
    "ROOT_REQUIRED",
}
_CONFLICT_CODES = {
    "FINAL_ADMINISTRATOR_REQUIRED",
    "INVALID_LIBRARY_TRANSITION",
    "CONFIG_REVISION_CONFLICT",
    "LIBRARY_CONFIGURATION_FROZEN",
    "LIBRARY_REMOVING",
    "ACL_CONFLICT",
    "ROOT_PATH_OVERLAP",
    "ROOT_REGISTRY_BUSY",
    "ROOT_IDENTITY_CHANGED",
    "ROOT_UNWRITABLE",
    "ROOT_NOT_DIRECTORY",
    "ROOT_PROTECTED",
    "ROOT_UNAVAILABLE",
    "ROOT_UNREADABLE",
    "SCOPE_EPOCH_EXHAUSTED",
    "INVALID_SCOPE_EPOCH",
}


def http_error_for(error: CatalogLibraryError) -> HttpContractError[LibraryErrorBody]:
    """Map a domain error to a stable status/code without exposing detail."""

    body = LibraryErrorBody(code=error.code, message="Library operation failed")
    if isinstance(error, _NOT_FOUND_ERRORS) or error.code in _NOT_FOUND_CODES:
        return CatalogNotFoundHttpError(body)
    if isinstance(error, _FORBIDDEN_ERRORS) or error.code in _FORBIDDEN_CODES:
        return CatalogForbiddenHttpError(body)
    if isinstance(error, _VALIDATION_ERRORS) or error.code in _VALIDATION_CODES:
        return CatalogValidationHttpError(body)
    if isinstance(error, _CONFLICT_ERRORS) or error.code in _CONFLICT_CODES:
        return CatalogConflictHttpError(body)
    return CatalogConflictHttpError(body)


__all__ = [
    "CatalogConflictHttpError",
    "CatalogForbiddenHttpError",
    "CatalogNotFoundHttpError",
    "CatalogValidationHttpError",
    "http_error_for",
]
