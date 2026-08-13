from fastapi import APIRouter

from app.api.typed_route import TypedContractRoute
from app.modules.reader.presentation.v4 import router as reader_v4_router

router = APIRouter(route_class=TypedContractRoute)
router.include_router(reader_v4_router)
