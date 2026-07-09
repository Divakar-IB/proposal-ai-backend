from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext

from authentication.jwt_handler import verify_access_token
from database.db_enum import UserRole



pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


def hash_password(password: str):
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)
security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security),):
    token = credentials.credentials
    payload = verify_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        )
    return 

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
