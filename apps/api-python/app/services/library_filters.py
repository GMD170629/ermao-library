"""Compatibility entry points for smart-filter validation and compilation."""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext, authorization_context
from app.models.auth import User
from app.modules.library.application.filter_ast import (
    InvalidFilterExpression,
    parse_filter_expression,
)
from app.modules.library.application.filter_options import (
    FILTER_FIELD_DEFINITIONS,
    LibraryFilterFieldDefinition,
)
from app.modules.library.infrastructure.filter_query import (
    compile_filter_expression,
    resolve_library_roots,
)
from app.modules.reader.public import ReaderV5LibraryPresentationQueryPort


def _field_contract(field: LibraryFilterFieldDefinition) -> dict[str, Any]:
    result: dict[str, Any] = {
        "key": field.key,
        "label": field.label,
        "group": field.group,
        "type": field.field_type,
        "operators": list(field.operators),
    }
    if field.option_source is not None:
        result["optionSource"] = field.option_source
    if field.allow_custom is not None:
        result["allowCustom"] = field.allow_custom
    if field.unit is not None:
        result["unit"] = field.unit
    if field.value_scale is not None:
        result["valueScale"] = field.value_scale
    return result


FILTER_FIELDS = [_field_contract(field) for field in FILTER_FIELD_DEFINITIONS]
FIELD_BY_KEY = {str(field["key"]): field for field in FILTER_FIELDS}


def normalize_filter_rules(value: Any) -> tuple[dict[str, Any], str | None]:
    if value in (None, ""):
        return {"combinator": "ALL", "conditions": []}, None
    if not isinstance(value, dict):
        return {}, "筛选规则格式不正确"
    combinator = str(value.get("combinator") or "ALL").upper()
    if combinator not in {"ALL", "ANY"}:
        return {}, "筛选条件组合方式无效"
    raw_conditions = value.get("conditions") or []
    if not isinstance(raw_conditions, list):
        return {}, "筛选条件格式不正确"
    if len(raw_conditions) > 30:
        return {}, "筛选条件最多支持 30 条"
    conditions: list[dict[str, Any]] = []
    for raw in raw_conditions:
        if not isinstance(raw, dict):
            return {}, "筛选条件格式不正确"
        field_key = str(raw.get("field") or "").strip()
        field = FIELD_BY_KEY.get(field_key)
        if not field:
            return {}, f"不支持的筛选维度：{field_key or '空'}"
        operator = str(raw.get("operator") or "").strip()
        if operator not in field["operators"]:
            return {}, f"{field['label']}不支持这个条件"
        normalized: dict[str, Any] = {"field": field_key, "operator": operator}
        if operator not in {"is_empty", "is_not_empty", "is_true", "is_false"}:
            raw_value = raw.get("value")
            if operator == "between":
                if (
                    not isinstance(raw_value, list)
                    or len(raw_value) != 2
                    or any(str(item).strip() == "" for item in raw_value)
                ):
                    return {}, f"请填写{field['label']}的完整范围"
                normalized["value"] = [
                    str(raw_value[0]).strip(),
                    str(raw_value[1]).strip(),
                ]
            else:
                next_value = str(raw_value if raw_value is not None else "").strip()
                if not next_value:
                    return {}, f"请填写{field['label']}的筛选值"
                normalized["value"] = next_value[:500]
        conditions.append(normalized)
    return {"combinator": combinator, "conditions": conditions}, None


def _authorization_context_for_user(
    db: Session,
    user_id: str | None,
) -> AuthorizationContext:
    user = db.get(User, user_id) if user_id else None
    if user is not None:
        return authorization_context(db, user)
    return AuthorizationContext(
        user_id=user_id or "",
        is_admin=True,
        can_manage_system=True,
        can_view_manual_imports=True,
        library_ids=(),
        authz_version=1,
    )


def compile_filter_predicate(
    db: Session,
    rules: dict[str, Any],
    *,
    user_id: str | None = None,
    shelf_owner_user_id: str | None = None,
    reader_queries: ReaderV5LibraryPresentationQueryPort,
) -> tuple[ColumnElement[bool] | None, str | None]:
    normalized, error = normalize_filter_rules(rules)
    if error:
        return None, error
    try:
        expression = parse_filter_expression(normalized)
    except InvalidFilterExpression as exc:
        return None, str(exc)
    context = _authorization_context_for_user(db, user_id)
    try:
        library_roots = resolve_library_roots(db, expression, context)
        return (
            compile_filter_expression(
                expression,
                context=context,
                user_id=user_id,
                shelf_owner_user_id=shelf_owner_user_id,
                reader_queries=reader_queries,
                library_roots=library_roots,
            ),
            None,
        )
    except ValueError as exc:
        return None, str(exc)


def compile_filter_rules(
    db: Session,
    rules: dict[str, Any],
    *,
    alias: str = "w",
    user_id: str | None = None,
    param_prefix: str = "smart_filter",
    shelf_owner_user_id: str | None = None,
    reader_queries: ReaderV5LibraryPresentationQueryPort,
) -> tuple[ColumnElement[bool] | None, dict[str, Any], str | None]:
    del alias, param_prefix
    predicate, error = compile_filter_predicate(
        db,
        rules,
        user_id=user_id,
        shelf_owner_user_id=shelf_owner_user_id,
        reader_queries=reader_queries,
    )
    return predicate, {}, error
