from fastapi import APIRouter

from app.api.typed_route import TypedContractRoute
from app.modules.auth.presentation.router import router as auth_router
from app.modules.download.presentation.http import router as download_router
from app.modules.imports.presentation.http import router as imports_router
from app.modules.kindle.presentation.http import router as kindle_router
from app.modules.library.presentation.http import router as library_router
from app.modules.media.presentation.http import router as media_router
from app.modules.metadata.presentation.http import router as metadata_router
from app.modules.mobile.presentation.http import router as mobile_router
from app.modules.organize.presentation.http import router as organize_router
from app.modules.reader.presentation.router import router as reader_router
from app.modules.shelf.presentation.http import router as shelf_router
from app.modules.system.presentation.router import router as system_router

api_router = APIRouter(route_class=TypedContractRoute)
api_router.include_router(auth_router)
api_router.include_router(reader_router)
api_router.include_router(system_router)
api_router.include_router(metadata_router)
api_router.include_router(mobile_router)
api_router.include_router(imports_router)
api_router.include_router(media_router)
api_router.include_router(library_router)
api_router.include_router(download_router)
api_router.include_router(shelf_router)
api_router.include_router(organize_router)
api_router.include_router(kindle_router, tags=["kindle"])
