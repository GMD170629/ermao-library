from fastapi import APIRouter

from app.api.routes import auth, health, kindle, reader_v2, users
from app.modules.metadata.presentation.http import router as metadata_router
from app.modules.imports.presentation.http import router as imports_router
from app.modules.library.presentation.http import router as library_router
from app.modules.download.presentation.http import router as download_router
from app.modules.shelf.presentation.http import router as shelf_router
from app.modules.organize.presentation.http import router as organize_router
from app.modules.media.presentation.http import router as media_router
from app.modules.reader.presentation.http import router as reader_v1_router
from app.modules.system.presentation.http import router as system_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/admin", tags=["users"])
api_router.include_router(users.preferences_router, prefix="/auth", tags=["preferences"])
api_router.include_router(reader_v2.router)
api_router.include_router(reader_v1_router)
api_router.include_router(system_router)
api_router.include_router(metadata_router)
api_router.include_router(imports_router)
api_router.include_router(media_router)
api_router.include_router(library_router)
api_router.include_router(download_router)
api_router.include_router(shelf_router)
api_router.include_router(organize_router)
api_router.include_router(kindle.router, tags=["kindle"])
