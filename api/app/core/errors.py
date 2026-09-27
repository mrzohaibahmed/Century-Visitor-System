"""
One error format for every API response:

    {"error": {"code": "not_found", "message": "...", "request_id": "..."}}

Internal details (stack traces, database errors, submitted values) are logged,
never returned.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import current_request_id

log = logging.getLogger(__name__)

_STATUS_CODES = {
    400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found",
    405: "method_not_allowed", 409: "conflict", 413: "payload_too_large", 422: "validation_error",
    429: "rate_limited", 503: "service_unavailable",
}


class AppError(Exception):
    """A handled error whose message is safe to show to the user."""

    def __init__(self, status_code: int, code: str, message: str, details: list | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def error_body(code: str, message: str, details: list | None = None) -> dict:
    error = {"code": code, "message": message, "request_id": current_request_id()}
    if details:
        error["details"] = details
    return {"error": error}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        code = _STATUS_CODES.get(exc.status_code, "error")
        message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").capitalize()
        return JSONResponse(error_body(code, message), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        # Report where and why, never the submitted value (it may be a password or CNIC).
        details = [{"field": ".".join(str(p) for p in err.get("loc", ())),
                    "message": str(err.get("msg", "Invalid")).removeprefix("Value error, ")}
                   for err in exc.errors()]
        return JSONResponse(error_body("validation_error", "The request is not valid.", details), status_code=422)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            error_body("internal_error",
                       "An unexpected error occurred. Please try again or contact the administrator."),
            status_code=500)
