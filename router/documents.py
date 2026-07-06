from fastapi import (
    APIRouter, 
    HTTPException, 
    status, 
    UploadFile,
    File,
    Depends
)
from sqlalchemy.orm import Session
from database.database import get_db

router = APIRouter(
    prefix='/document',
    tags="Documents"
    )
