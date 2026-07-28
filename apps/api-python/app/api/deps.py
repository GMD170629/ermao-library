"""Shared FastAPI delivery dependencies."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.authorization import can_manage_system
from app.core.config import Settings
from app.models.auth import User
from app.schemas.responses import fail


def require_user(
    db: Session,
    request: Request,
    settings: Settings,
) -> tuple[User | None, Response | None]:
    user, _token, _refresh = get_current_user(db, request, settings)
    if user is None:
        return None, fail("UNAUTHORIZED", status_code=401)
    return user, None


def require_system_manager(
    db: Session,
    request: Request,
    settings: Settings,
) -> tuple[User | None, Response | None]:
    user, auth_error = require_user(db, request, settings)
    if auth_error is not None:
        return None, auth_error
    if user is None or not can_manage_system(user):
        return None, fail(
            "需要系统管理权限",
            status_code=403,
            code="SYSTEM_MANAGER_REQUIRED",
        )
    return user, None
