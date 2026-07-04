from functools import wraps

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from authentication.dependency import get_current_user
from database.db_enum import UserRole


# ------------------------------------------------------------------
# Exception Handling
# ------------------------------------------------------------------
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
            import traceback
            traceback.print_exc()
            raise
        except SQLAlchemyError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="A database error occurred. Please try again.",
            )
        except Exception:
            import traceback
            traceback.print_exc()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred.",
            )
    return wrapper


async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "A database error occurred. Please try again."},
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred."},
    )


# ------------------------------------------------------------------
# Role Validation
# ------------------------------------------------------------------
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
