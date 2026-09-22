"""The v2 tool names and required scopes; registration remains implementation-only."""

from types import MappingProxyType

from app.modules.automation.domain.access import EffectiveAccess, Scope

TOOL_SCOPES = MappingProxyType(
    {
        "begin_upload": frozenset({Scope.SYSTEM_READ}),
        "upload_chunk": frozenset({Scope.SYSTEM_READ}),
        "complete_upload": frozenset({Scope.SYSTEM_READ}),
        "list_import_queue": frozenset({Scope.SYSTEM_READ}),
        "get_system_queue_status": frozenset({Scope.SYSTEM_READ}),
        "list_system_logs": frozenset({Scope.SYSTEM_READ}),
        "get_system_configuration": frozenset({Scope.SYSTEM_READ}),
        "update_site_settings": frozenset({Scope.SYSTEM_MANAGE}),
        "update_email_settings": frozenset({Scope.SYSTEM_MANAGE}),
        "update_opds_settings": frozenset({Scope.SYSTEM_MANAGE}),
        "update_library_settings": frozenset({Scope.SYSTEM_MANAGE}),
        "update_organize_settings": frozenset({Scope.SYSTEM_MANAGE}),
        "get_context": frozenset({Scope.SYSTEM_READ}),
        "list_libraries": frozenset({Scope.SYSTEM_READ}),
        "search_books": frozenset({Scope.SYSTEM_READ}),
        "get_books": frozenset({Scope.SYSTEM_READ}),
        "list_facets": frozenset({Scope.SYSTEM_READ}),
        "list_shelves": frozenset({Scope.SYSTEM_READ}),
        "get_shelf": frozenset({Scope.SYSTEM_READ}),
        "update_shelf": frozenset({Scope.SHELVES_WRITE}),
        "delete_shelf": frozenset({Scope.SHELVES_WRITE}),
        "create_shelf": frozenset({Scope.SHELVES_WRITE}),
        "add_shelf_books": frozenset({Scope.SHELVES_WRITE}),
        "remove_shelf_books": frozenset({Scope.SHELVES_WRITE}),
        "add_book_tags": frozenset({Scope.BOOKS_WRITE}),
        "remove_book_tags": frozenset({Scope.BOOKS_WRITE}),
        "list_source_nodes": frozenset({Scope.SYSTEM_READ}),
        "get_metadata_schema": frozenset({Scope.SYSTEM_READ}),
        "read_file_metadata": frozenset({Scope.SYSTEM_READ}),
        "update_metadata": frozenset({Scope.BOOKS_WRITE}),
        "refresh_metadata": frozenset({Scope.SYSTEM_READ, Scope.BOOKS_WRITE}),
        "plan_file_deletions": frozenset({Scope.FILES_MODIFY}),
        "execute_file_deletions": frozenset({Scope.FILES_MODIFY}),
        "plan_file_operations": frozenset({Scope.SYSTEM_READ, Scope.FILES_MODIFY}),
        "execute_file_operations": frozenset({Scope.FILES_MODIFY}),
        "plan_metadata_writeback": frozenset({Scope.SYSTEM_READ, Scope.FILES_MODIFY}),
        "execute_metadata_writeback": frozenset({Scope.FILES_MODIFY}),
        # Ownership, current target visibility, and the original write scope are
        # checked by operation use cases, not merely by tool discovery.
        "get_operation": frozenset({Scope.SYSTEM_READ}),
        "cancel_operation": frozenset({Scope.SYSTEM_READ}),
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
        if name in implemented
        and required <= access.permissions.scopes
        and (
            access.can_manage_system
            or name
            not in {
                "list_import_queue",
                "get_system_queue_status",
                "list_system_logs",
                "get_system_configuration",
                "update_site_settings",
                "update_email_settings",
                "update_library_settings",
                "update_opds_settings",
                "update_organize_settings",
            }
        )
        and (
            name not in {"begin_upload", "upload_chunk", "complete_upload"}
            or bool(
                access.permissions.scopes
                & {Scope.FILES_UPLOAD, Scope.BOOKS_WRITE, Scope.FILES_MODIFY}
            )
        )
    )
