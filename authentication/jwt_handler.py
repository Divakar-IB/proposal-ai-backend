from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from config import config

SECRET_KEY = config.jwt.secret_key
ALGORITHM = config.jwt.algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = config.jwt.access_token_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS = config.jwt.refresh_token_expire_days
ISSUER = config.jwt.issuer


# ------------------------------------------------------------------
# Private Helper
# ------------------------------------------------------------------
def _create_token(payload: dict, expires_delta: timedelta) -> str:
    data = payload.copy()
    now = datetime.now(timezone.utc)
    data["iat"] = now
    data["exp"] = now + expires_delta
    data["iss"] = ISSUER
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)


# ------------------------------------------------------------------
# Token Creation
# ------------------------------------------------------------------
def create_access_token(user_id: int, email: str, role: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "token_type": "access",
    }
    return _create_token(payload, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(user_id: int) -> str:
    payload = {
        "user_id": user_id,
        "token_type": "refresh",
    }
    return _create_token(payload, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))


def create_password_reset_token(user_id: int, expire_minutes: int) -> str:
    payload = {
        "user_id": user_id,
        "token_type": "password_reset",
    }
    return _create_token(payload, timedelta(minutes=expire_minutes))


# ------------------------------------------------------------------
# Token Verification
# ------------------------------------------------------------------
def verify_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], issuer=ISSUER)
        if payload.get("token_type") != "access":
            raise JWTError("Invalid token type")
        return payload
    except JWTError:
        return None


def verify_refresh_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], issuer=ISSUER)
        if payload.get("token_type") != "refresh":
            raise JWTError("Invalid token type")
        return payload
    except JWTError:
        return None


def verify_password_reset_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], issuer=ISSUER)
        if payload.get("token_type") != "password_reset":
            raise JWTError("Invalid token type")
        return payload
    except JWTError:
        return None
