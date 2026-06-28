from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from config import config

jwt_config = config["JWT"]

SECRET_KEY = jwt_config["SECRET_KEY"]
ALGORITHM = jwt_config["ALGORITHM"]

ACCESS_TOKEN_EXPIRE_MINUTES = jwt_config["ACCESS_TOKEN_EXPIRE_MINUTES"]
REFRESH_TOKEN_EXPIRE_MINUTES = jwt_config["REFRESH_TOKEN_EXPIRE_MINUTES"]
ISSUER = jwt_config["ISSUER"]
# -----------------------------
# Private Helper
# -----------------------------
def _create_token(payload: dict,expires_delta: timedelta,) -> str:
    data = payload.copy()
    now = datetime.now(timezone.utc)
    data["iat"] = now
    data["exp"] = now + expires_delta
    data["iss"] = ISSUER
    token = jwt.encode(
        data,
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    return token

def create_access_token(user_id: int,email: str,session_uuid: str,) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "session_uuid": session_uuid,
        "token_type": "access",
    }
    return _create_token(
        payload=payload,
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )

def create_refresh_token(user_id: int,session_uuid: str,) -> str:
    payload = {
        "user_id": user_id,
        "session_uuid": session_uuid,
        "token_type": "refresh",
    }
    return _create_token(
        payload=payload,
        expires_delta=timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES),
    )

def verify_access_token(token: str,) -> dict:
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
        )
        if payload.get("token_type") != "access":
            raise JWTError("Invalid token type")
        return payload
    except JWTError:
        return None
    
def verify_refresh_token(token: str,) -> dict:
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
        )
        if payload.get("token_type") != "refresh":
            raise JWTError("Invalid token type")
        return payload
    except JWTError:
        return None