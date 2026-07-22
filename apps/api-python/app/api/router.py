from fastapi import APIRouter

from app.api.routes import auth, compat, health, kindle, reader_v2

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(reader_v2.router)
api_router.include_router(kindle.router, tags=["kindle"])
api_router.include_router(compat.router, tags=["compat"])
