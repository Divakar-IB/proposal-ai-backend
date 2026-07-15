from fastapi import FastAPI

from middleware.cors import setup_cors
from middleware.error_handler import ErrorHandlerMiddleware


def setup_middleware(app: FastAPI) -> None:
    """
    Registers all app-wide middleware.

    Call once from main.py right after creating the FastAPI app.
    Order matters: Starlette wraps the LAST-added middleware outermost,
    so the error handler is added first (innermost) and CORS is added
    second (outermost) — that way CORS headers still land on the
    JSON responses the error handler returns.
    """
    app.add_middleware(ErrorHandlerMiddleware)
    setup_cors(app)
