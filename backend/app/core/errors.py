from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class AppError(Exception):
    def __init__(
        self, status: int, code: str, message: str, headers: dict[str, str] | None = None
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers


def error_response(status: int, code: str, message: str, **kwargs: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
        **kwargs,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def application_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Never echo submitted values: validation errors can contain passwords or URL secrets.
        fields = [
            {"field": ".".join(str(part) for part in e["loc"][1:]), "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Please check the submitted fields.",
                    "fields": fields,
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return error_response(exc.status_code, "HTTP_ERROR", str(exc.detail), headers=exc.headers)
