from fastapi import APIRouter

from app.api.typed_route import TypedContractRoute
from app.modules.reader.presentation.v4_tombstone import router as reader_v4_router
from app.modules.reader.presentation.v5 import router as reader_v5_router

router = APIRouter(route_class=TypedContractRoute)
router.include_router(reader_v5_router)
router.include_router(reader_v4_router)
