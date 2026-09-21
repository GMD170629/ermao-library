"""The v2 tool names and required scopes; registration remains implementation-only."""

from types import MappingProxyType

from app.modules.automation.domain.access import EffectiveAccess, Scope

TOOL_SCOPES = MappingProxyType(
    {
        "get_context": frozenset({Scope.LIBRARY_READ}),
        "list_libraries": frozenset({Scope.LIBRARY_READ}),
        "search_books": frozenset({Scope.LIBRARY_READ}),
        "get_books": frozenset({Scope.LIBRARY_READ}),
        "list_facets": frozenset({Scope.LIBRARY_READ}),
        "list_shelves": frozenset({Scope.LIBRARY_READ}),
        "get_shelf": frozenset({Scope.LIBRARY_READ}),
        "create_shelf": frozenset({Scope.SHELVES_WRITE}),
        "add_shelf_books": frozenset({Scope.SHELVES_WRITE}),
        "remove_shelf_books": frozenset({Scope.SHELVES_WRITE}),
        "add_book_tags": frozenset({Scope.TAGS_WRITE}),
        "remove_book_tags": frozenset({Scope.TAGS_WRITE}),
        "list_source_nodes": frozenset({Scope.FILES_READ}),
        "get_metadata_schema": frozenset({Scope.LIBRARY_READ}),
        "read_file_metadata": frozenset({Scope.FILES_READ}),
        "update_metadata": frozenset({Scope.METADATA_WRITE}),
        "refresh_metadata": frozenset({Scope.FILES_READ, Scope.METADATA_WRITE}),
        "plan_file_operations": frozenset({Scope.FILES_READ, Scope.FILES_MOVE}),
        "execute_file_operations": frozenset({Scope.FILES_READ, Scope.FILES_MOVE}),
        "plan_metadata_writeback": frozenset(
            {Scope.FILES_READ, Scope.METADATA_WRITEBACK}
        ),
        "execute_metadata_writeback": frozenset(
            {Scope.FILES_READ, Scope.METADATA_WRITEBACK}
        ),
        # Ownership, current target visibility, and the original write scope are
        # checked by operation use cases, not merely by tool discovery.
        "get_operation": frozenset({Scope.LIBRARY_READ}),
        "cancel_operation": frozenset({Scope.LIBRARY_READ}),
    }
)

QUERY_DEFAULT_LIMIT = 20
QUERY_MAX_LIMIT = 50
METADATA_BATCH_LIMIT = 20
FILE_PLAN_TARGET_LIMIT = 100
FILE_PLAN_EXPANDED_LIMIT = 10_000
FILE_PLAN_BYTES_LIMIT = 100 * 1024**3
PLAN_LIFETIME_SECONDS = 15 * 60


def visible_tools(
    access: EffectiveAccess, implemented: frozenset[str]
) -> tuple[str, ...]:
    """Never advertise an unimplemented tool or cache across grants."""
    return tuple(
        name
        for name, required in TOOL_SCOPES.items()
        if name in implemented and required <= access.permissions.scopes
    )
