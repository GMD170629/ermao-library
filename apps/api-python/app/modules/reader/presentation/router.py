from fastapi import APIRouter

from app.api.typed_route import TypedContractRoute
from app.modules.reader.presentation.http import router as reader_v1_router
from app.modules.reader.presentation.retired import router as reader_v2_router
from app.modules.reader.presentation.v3 import router as reader_v3_router

router = APIRouter(route_class=TypedContractRoute)
router.include_router(reader_v1_router)
router.include_router(reader_v2_router)
router.include_router(reader_v3_router)
