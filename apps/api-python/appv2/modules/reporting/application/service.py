from __future__ import annotations

import json
import uuid
from collections.abc import Mapping

from appv2.modules.reporting.contracts import (
    DashboardProjection,
    LibraryFilterCondition,
    LibraryFilterRules,
    LibraryFilterSchema,
    LibraryQuery,
    LibraryWorkProjection,
    ManagementProjection,
    ReportingReadPort,
)

_FILTER_OPERATORS = {
    "text": {
        "contains",
        "not_contains",
        "equals",
        "not_equals",
        "starts_with",
        "ends_with",
        "is_empty",
        "is_not_empty",
    },
    "select": {"equals", "not_equals", "is_empty", "is_not_empty"},
    "number": {
        "equals",
        "not_equals",
        "greater_than",
        "greater_or_equal",
        "less_than",
        "less_or_equal",
        "between",
        "is_empty",
        "is_not_empty",
    },
    "date": {
        "equals",
        "not_equals",
        "after",
        "on_or_after",
        "before",
        "on_or_before",
        "between",
        "is_empty",
        "is_not_empty",
    },
    "boolean": {"is_true", "is_false"},
}

_FILTER_FIELD_TYPES = {
    "title": "text",
    "author": "text",
    "description": "text",
    "series": "text",
    "language": "select",
    "format": "select",
    "fileSize": "number",
    "pageCount": "number",
    "duration": "number",
    "versionCount": "number",
    "readingStatus": "select",
    "progress": "number",
    "lastReadAt": "date",
    "hasCover": "boolean",
    "shelf": "select",
    "createdAt": "date",
    "updatedAt": "date",
}


def _filter_rules(raw_filters: str | None) -> LibraryFilterRules:
    if not raw_filters:
        return LibraryFilterRules(combinator="ALL", conditions=())
    try:
        payload = json.loads(raw_filters)
    except json.JSONDecodeError as error:
        raise ValueError("Invalid smart filter JSON") from error
    if not isinstance(payload, Mapping):
        raise ValueError("Smart filters must be an object")
    combinator = str(payload.get("combinator", "ALL")).upper()
    if combinator not in {"ALL", "ANY"}:
        raise ValueError("Invalid smart filter combinator")
    raw_conditions = payload.get("conditions", [])
    if not isinstance(raw_conditions, list) or len(raw_conditions) > 30:
        raise ValueError("Smart filters support at most 30 conditions")
    conditions: list[LibraryFilterCondition] = []
    for raw in raw_conditions:
        if not isinstance(raw, Mapping):
            raise ValueError("Invalid smart filter condition")
        field = str(raw.get("field", ""))
        field_type = _FILTER_FIELD_TYPES.get(field)
        operator = str(raw.get("operator", ""))
        if field_type is None or operator not in _FILTER_OPERATORS[field_type]:
            raise ValueError("Unsupported smart filter condition")
        raw_value = raw.get("value")
        normalized_value: str | tuple[str, str] | None
        if operator in {"is_empty", "is_not_empty", "is_true", "is_false"}:
            normalized_value = None
        elif operator == "between":
            if (
                not isinstance(raw_value, list)
                or len(raw_value) != 2
                or any(not str(item).strip() for item in raw_value)
            ):
                raise ValueError("Smart filter range requires two values")
            normalized_value = (
                str(raw_value[0]).strip(),
                str(raw_value[1]).strip(),
            )
        else:
            normalized_value = str(raw_value or "").strip()
            if not normalized_value:
                raise ValueError("Smart filter value is required")
        conditions.append(
            LibraryFilterCondition(
                field=field,
                operator=operator,
                value=normalized_value,
            )
        )
    return LibraryFilterRules(combinator=combinator, conditions=tuple(conditions))


class ReportingService:
    def __init__(self, read_port: ReportingReadPort) -> None:
        self._read_port = read_port

    def library(
        self,
        account_id: uuid.UUID,
        *,
        page: int,
        page_size: int,
        query: str | None,
        media_type: str | None,
        series_name: str | None,
        reading_status: str | None,
        sort: str,
        sort_direction: str,
        filters: str | None,
    ) -> tuple[list[LibraryWorkProjection], int]:
        normalized_status = (
            reading_status.upper() if reading_status and reading_status != "全部" else None
        )
        if normalized_status not in {None, "UNREAD", "READING", "FINISHED"}:
            raise ValueError("Invalid reading status")
        if sort not in {
            "recent_read",
            "recent_import",
            "title",
            "author",
            "publisher",
            "series",
        }:
            raise ValueError("Invalid library sort")
        if sort_direction not in {"asc", "desc"}:
            raise ValueError("Invalid library sort direction")
        return self._read_port.library(
            account_id,
            LibraryQuery(
                page=max(page, 1),
                page_size=min(max(page_size, 1), 200),
                query=query.strip() if query and query.strip() else None,
                media_type=media_type,
                series_name=series_name,
                reading_status=normalized_status,
                sort=sort,
                sort_direction=sort_direction,
                filters=_filter_rules(filters),
            ),
        )

    def library_filter_schema(self, account_id: uuid.UUID) -> LibraryFilterSchema:
        return self._read_port.library_filter_schema(account_id)

    def dashboard(self, account_id: uuid.UUID) -> DashboardProjection:
        return self._read_port.dashboard(account_id)

    def management(self) -> ManagementProjection:
        return self._read_port.management()
