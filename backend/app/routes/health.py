"""Health route for API reachability checks."""

from __future__ import annotations

from fastapi import APIRouter


router = APIRouter(tags=["health"])


@router.get("/health")
async def api_health() -> dict[str, str]:
    return {"ok": "true", "status": "healthy"}

