from fastapi import APIRouter

from app.api.typed_route import TypedContractRoute
from app.modules.auth.presentation.http import router as session_router
from app.modules.auth.presentation.users import (
    preferences_router,
    router as users_router,
)

router = APIRouter(route_class=TypedContractRoute)
router.include_router(session_router, prefix="/auth", tags=["auth"])
router.include_router(users_router, prefix="/admin", tags=["users"])
router.include_router(preferences_router, prefix="/auth", tags=["preferences"])
