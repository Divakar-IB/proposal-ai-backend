import traceback
from functools import wraps

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from authentication.dependency import get_current_user
from config import config
from database.db_enum import UserRole



def handle_exceptions(func):
    """
    Decorator applied to service functions.

    Passes HTTPExceptions through unchanged (they carry intentional
    status codes).  Catches SQLAlchemy errors and any other unexpected
    exception and maps them to consistent JSON error responses so
    callers never receive unformatted Python tracebacks.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except HTTPException:
            raise
        except SQLAlchemyError:
            traceback.print_exc()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="A database error occurred. Please try again.",
            )
        except Exception:
            traceback.print_exc()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred.",
            )
    return wrapper


async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    traceback.print_exc()
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "A database error occurred. Please try again."},
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    traceback.print_exc()
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred."},
    )


# ------------------------------------------------------------------
# App-wide middleware / exception handler registration
# ------------------------------------------------------------------
def setup_middleware(app: FastAPI) -> None:
    """
    Registers all app-wide middleware and exception handlers.

    Call once from main.py right after creating the FastAPI app.
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)


# Role Validation
def require_role(*roles: UserRole):
    """
    Returns a FastAPI dependency that enforces role-based access.

    Usage:
        current_user: dict = Depends(require_role(UserRole.ADMIN))
        current_user: dict = Depends(require_role(UserRole.ADMIN, UserRole.USER))
    """
    allowed = {r.value for r in roles}

    def dependency(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("role") not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return current_user

    return dependency
