"""API route registry."""

from fastapi import APIRouter

from .dashboard import router as dashboard_router
from .download import router as download_router
from .health import router as health_router
from .process import router as process_router
from .upload import router as upload_router


api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(upload_router)
api_router.include_router(process_router)
api_router.include_router(dashboard_router)
api_router.include_router(download_router)
