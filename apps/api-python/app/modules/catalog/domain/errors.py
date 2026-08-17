"""Stable domain errors for current library configuration."""

from __future__ import annotations


class CatalogLibraryError(ValueError):
    """Base error whose ``code`` is safe for application/API translation."""

    code = "CATALOG_LIBRARY_ERROR"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail
        super().__init__(self.code if detail is None else f"{self.code}:{detail}")


class InvalidLibraryName(CatalogLibraryError):
    code = "INVALID_LIBRARY_NAME"


class InvalidLibraryIdentifier(CatalogLibraryError):
    code = "INVALID_LIBRARY_IDENTIFIER"


class InvalidRootObservation(CatalogLibraryError):
    code = "INVALID_ROOT_OBSERVATION"


class RootRequired(CatalogLibraryError):
    code = "ROOT_REQUIRED"


class RootNotAbsolute(CatalogLibraryError):
    code = "ROOT_NOT_ABSOLUTE"


class RootExpansionNotAllowed(CatalogLibraryError):
    code = "ROOT_EXPANSION_NOT_ALLOWED"


class RootUnavailable(CatalogLibraryError):
    code = "ROOT_UNAVAILABLE"


class RootNotDirectory(CatalogLibraryError):
    code = "ROOT_NOT_DIRECTORY"


class RootUnreadable(CatalogLibraryError):
    code = "ROOT_UNREADABLE"


class RootProtected(CatalogLibraryError):
    code = "ROOT_PROTECTED"


class RootUnwritable(CatalogLibraryError):
    code = "ROOT_UNWRITABLE"


class RootIdentityChanged(CatalogLibraryError):
    code = "ROOT_IDENTITY_CHANGED"


class RootOverlapConflict(CatalogLibraryError):
    code = "ROOT_PATH_OVERLAP"


class RootRegistryBusy(CatalogLibraryError):
    code = "ROOT_REGISTRY_BUSY"


class LibraryNotFound(CatalogLibraryError):
    code = "LIBRARY_NOT_FOUND"


class LibraryForbidden(CatalogLibraryError):
    code = "LIBRARY_NOT_FOUND"


class LibraryAuthorizationDenied(CatalogLibraryError):
    code = "LIBRARY_AUTHORIZATION_DENIED"


class LibraryCreateDenied(CatalogLibraryError):
    code = "LIBRARY_CREATE_DENIED"


class LibraryConfigConflict(CatalogLibraryError):
    code = "CONFIG_REVISION_CONFLICT"


class AclConflict(CatalogLibraryError):
    code = "ACL_CONFLICT"


class InvalidLibraryTransition(CatalogLibraryError):
    code = "INVALID_LIBRARY_TRANSITION"


class LibraryRemoving(CatalogLibraryError):
    code = "LIBRARY_REMOVING"


class LibraryConfigurationFrozen(CatalogLibraryError):
    code = "LIBRARY_CONFIGURATION_FROZEN"


class NoLibraryChanges(CatalogLibraryError):
    code = "NO_LIBRARY_CHANGES"


class InvalidPageLimit(CatalogLibraryError):
    code = "INVALID_PAGE_LIMIT"


class InvalidIgnoreRule(CatalogLibraryError):
    code = "INVALID_IGNORE_RULE"


class DuplicateIgnoreRule(CatalogLibraryError):
    code = "DUPLICATE_IGNORE_RULE"


class GrantTargetNotFound(CatalogLibraryError):
    code = "GRANT_TARGET_NOT_FOUND"


class InvalidGrantLevel(CatalogLibraryError):
    code = "INVALID_GRANT_LEVEL"


class FinalAdministratorRequired(CatalogLibraryError):
    code = "FINAL_ADMINISTRATOR_REQUIRED"


class ScopeEpochInvalid(CatalogLibraryError):
    code = "INVALID_SCOPE_EPOCH"


class ScopeEpochExhausted(CatalogLibraryError):
    code = "SCOPE_EPOCH_EXHAUSTED"


class MissingApplicationDependency(CatalogLibraryError):
    code = "MISSING_APPLICATION_DEPENDENCY"
