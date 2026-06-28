from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from authentication.auth_service import login

from database.database import get_db
from database.schemas import LoginRequest, LoginResponse


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


@router.post("/login",response_model=LoginResponse,)
def login_user(
    login_request: LoginRequest,
    db: Session = Depends(get_db),
):
    return login(
        db=db,
        login_request=login_request,
    )