import traceback

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """
    Global error handler for the whole request lifecycle (routes,
    services, DB calls). Lets HTTPExceptions pass through unchanged
    (they carry intentional status codes) and maps SQLAlchemy errors
    and any other unexpected exception to consistent JSON error
    responses so callers never receive unformatted Python tracebacks.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except HTTPException:
            raise
        except SQLAlchemyError:
            traceback.print_exc()
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"detail": "A database error occurred. Please try again."},
            )
        except Exception:
            traceback.print_exc()
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "An unexpected error occurred."},
            )
