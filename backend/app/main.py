"""FastAPI app entrypoint for MYKL churn webapp backend."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.routes import api_router


APP_ROOT = Path(__file__).resolve().parents[1]
WEBAPP_ROOT = APP_ROOT.parent
FRONTEND_ROOT = WEBAPP_ROOT / "frontend"
FRONTEND_ASSETS = FRONTEND_ROOT / "assets"


app = FastAPI(title="MYKL Churn Webapp Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

if FRONTEND_ASSETS.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_ASSETS)), name="assets")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def index():
    index_path = FRONTEND_ROOT / "index.html"
    if not index_path.exists():
        return JSONResponse(status_code=404, content={"ok": False, "message": "Frontend index not found."})
    return FileResponse(str(index_path))


@app.get("/styles.css")
async def styles():
    path = FRONTEND_ROOT / "styles.css"
    if not path.exists():
        return JSONResponse(status_code=404, content={"ok": False, "message": "styles.css not found."})
    return FileResponse(str(path), media_type="text/css")


@app.get("/app.js")
async def script():
    path = FRONTEND_ROOT / "app.js"
    if not path.exists():
        return JSONResponse(status_code=404, content={"ok": False, "message": "app.js not found."})
    return FileResponse(str(path), media_type="application/javascript")


@app.get("/MYKL_logo.jpg")
async def logo():
    path = FRONTEND_ROOT / "MYKL_logo.jpg"
    if not path.exists():
        return JSONResponse(status_code=404, content={"ok": False, "message": "MYKL_logo.jpg not found."})
    return FileResponse(str(path), media_type="image/jpeg")


@app.get("/background_Image.jpg")
async def background_image():
    path = FRONTEND_ROOT / "background_Image.jpg"
    if not path.exists():
        return JSONResponse(status_code=404, content={"ok": False, "message": "background_Image.jpg not found."})
    return FileResponse(str(path), media_type="image/jpeg")
