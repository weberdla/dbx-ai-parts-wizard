"""AI Parts Wizard - FastAPI entry point.

Serves the JSON API under /api and the built React SPA for everything else.
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server.db import db
from server.routes import router

FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the pool; don't crash startup if the DB is briefly unreachable.
    try:
        await db.get_pool()
    except Exception as exc:  # pragma: no cover
        print(f"[startup] Lakebase pool warm-up failed (will retry lazily): {exc}")
    yield
    await db.close()


app = FastAPI(title="AI Parts Wizard", lifespan=lifespan)
app.include_router(router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


if FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

    # index.html must never be cached: it names the content-hashed JS/CSS
    # bundles, so a stale copy pins the browser to an old build. The hashed
    # assets under /assets are immutable and safe to cache long-term.
    _NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"error": "not found"}, status_code=404)
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html", headers=_NO_CACHE)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
