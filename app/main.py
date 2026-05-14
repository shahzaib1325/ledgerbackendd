import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.logging import configure_logging
from app.core.middleware import LoggingMiddleware, RequestIDMiddleware

configure_logging()
logger = structlog.get_logger(__name__)

# Standard envelope builder — keeps all handlers consistent.
def _error_body(code: str, message: str, field: str | None = None) -> dict:
    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message, "field": field},
        "meta": None,
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title="SmartLedger API",
        version="1.0.0",
        description="Business accounting & ERP backend for SmartLedger.",
        docs_url=settings.docs_url,
        redoc_url=settings.redoc_url,
        openapi_url="/openapi.json" if not settings.is_production else None,
    )

    _register_middleware(app)
    _register_exception_handlers(app)
    _register_routers(app)
    _register_health(app)

    return app


def _register_middleware(app: FastAPI) -> None:
    # Order matters — outermost middleware runs first on ingress, last on egress.
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )


def _register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(AppException)
    async def app_exception_handler(
        _request: Request, exc: AppException
    ) -> JSONResponse:
        """Maps all domain exceptions to the standard error envelope."""
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.field),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """
        Pydantic request validation failures (422).

        Reports the first failing field using the standard error envelope.
        Field path is formatted as a dot-separated string (e.g. 'items[0].quantity').
        """
        errors = exc.errors()
        first = errors[0] if errors else {}

        # Build a readable field path from the loc tuple.
        # loc may start with 'body', 'query', etc. — skip the leading context token.
        loc = first.get("loc", ())
        parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
        field = ".".join(parts) if parts else None

        message = first.get("msg", "Invalid request.").replace("Value error, ", "")

        return JSONResponse(
            status_code=422,
            content=_error_body("VALIDATION_ERROR", message, field),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """
        Catches any raw HTTPException raised by FastAPI internals
        (e.g. 404 on unknown route, 405 method not allowed).
        Wraps them in the standard envelope so no FastAPI default leaks through.
        """
        code_map = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "PERMISSION_DENIED",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            429: "RATE_LIMIT_EXCEEDED",
        }
        code = code_map.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "An error occurred."

        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(code, message),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """
        Catch-all for any unhandled exception.
        Logs the full traceback; returns a generic 500 without leaking internals.
        """
        logger.exception(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content=_error_body(
                "INTERNAL_ERROR", "An unexpected error occurred."
            ),
        )


def _register_routers(app: FastAPI) -> None:
    app.include_router(api_v1_router, prefix="/api/v1")


def _register_health(app: FastAPI) -> None:
    @app.get("/health", tags=["Observability"], include_in_schema=False)
    async def health() -> dict:
        return {"status": "ok", "environment": settings.ENVIRONMENT}


app = create_app()
