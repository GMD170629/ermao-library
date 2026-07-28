from fastapi import APIRouter

from app.api.typed_route import TypedContractRoute
from app.modules.system.presentation.health import router as health_router
from app.modules.system.presentation.http import router as system_router

router = APIRouter(route_class=TypedContractRoute)
router.include_router(health_router)
router.include_router(system_router)
