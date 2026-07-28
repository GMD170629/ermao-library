"""Kindle capability composition root."""

from app.modules.kindle.infrastructure.tasks import (
    cancel_queued_kindle_task,
    create_kindle_send_task,
    delete_kindle_send_task,
    find_active_kindle_task,
    get_kindle_send_task,
    get_library_file_details_for_kindle,
    has_table,
    list_kindle_send_tasks,
    retry_kindle_task,
)

__all__ = [
    "cancel_queued_kindle_task",
    "create_kindle_send_task",
    "delete_kindle_send_task",
    "find_active_kindle_task",
    "get_kindle_send_task",
    "get_library_file_details_for_kindle",
    "has_table",
    "list_kindle_send_tasks",
    "retry_kindle_task",
]
