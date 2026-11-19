import json
import logging
import time
import uuid
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import auth, monitors
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import error_response, install_error_handlers
from app.core.security import RateLimiter

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("uptimex.api")


def document_client_header(
    _client: Annotated[
        str,
        Header(
            alias="X-UptimeX-Client",
            description="Use web for writes. CSRF marker only, not an authentication credential.",
        ),
    ] = "web",
) -> None:
    """Expose the middleware-enforced marker in the interactive API reference."""


def create_app() -> FastAPI:
    app = FastAPI(
        title="UptimeX API",
        version="0.1.0",
        description="Phase 1 foundation. Monitor configuration only; checks are not running yet.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        dependencies=[Depends(document_client_header)],
    )
    app.state.rate_limiter = RateLimiter()
    install_error_handlers(app)

    @app.middleware("http")
    async def request_guard(request: Request, call_next):
        request_id = str(uuid.uuid4())
        started = time.monotonic()
        response = None
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith(
            "/api/"
        ):
            # Custom headers force a CORS preflight; this same-origin API grants no CORS access.
            # Also enforce Origin when the browser supplies it. No GET route mutates state.
            origin = request.headers.get("origin")
            try:
                origin_url = urlsplit(origin) if origin is not None else None
                bad_origin = origin_url is not None and (
                    origin_url.scheme not in {"http", "https"}
                    or origin_url.netloc.lower() != request.headers.get("host", "").lower()
                )
            except ValueError:
                bad_origin = True
            if (
                request.headers.get("x-uptimex-client") != "web"
                or request.headers.get("sec-fetch-site") == "cross-site"
                or bad_origin
            ):
                response = error_response(
                    403, "CSRF_REJECTED", "Use the same-origin UptimeX client."
                )
        if response is None:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception("Unhandled API error; request_id=%s", request_id)
                response = error_response(
                    500, "INTERNAL_ERROR", "Something went wrong. Please try again."
                )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000, 1),
                }
            )
        )
        return response

    @app.get("/api/v1/health", tags=["Platform"])
    def health(db: Session = Depends(get_db)) -> JSONResponse:
        try:
            db.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return JSONResponse(
                status_code=503, content={"status": "unavailable", "database": "error"}
            )
        return JSONResponse(
            content={
                "status": "ok",
                "database": "connected",
                "version": "0.1.0",
                "checks_enabled": False,
            }
        )

    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(monitors.router, prefix="/api/v1")
    frontend_dist = get_settings().frontend_dist
    if frontend_dist is not None:
        directory = frontend_dist.resolve()
        if not (directory / "index.html").is_file():
            raise RuntimeError(
                "FRONTEND_DIST must contain a built dashboard; run npm run build first"
            )
        # One origin/entry point for protected previews; /api routes still take precedence.
        app.mount("/", StaticFiles(directory=directory, html=True), name="dashboard")
    return app


app = create_app()
