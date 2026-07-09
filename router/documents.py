from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from authentication.dependency import get_current_user
from database.crud import (
    create_knowledge_document,
    delete_knowledge_document,
    get_knowledge_document_by_id,
    get_knowledge_documents,
    update_knowledge_document,
)
from database.database import get_db
from database.models import Category, KnowledgeDocument
from schemas.document import DocumentResponse, DocumentUpdateRequest
from utilities.s3_service import S3PathBuilder, S3Service

s3_service = S3Service()

router = APIRouter(
    prefix="/document",
    tags=["Documents"],
)


def _to_response(document: KnowledgeDocument) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        title=document.title,
        file_name=document.file_name,
        extension=document.extension,
        category_id=document.category_id,
        category_name=document.category.name,
        user_id=document.user_id,
        version=document.version,
        status=document.status,
        created_at=document.created_at,
    )


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def upload_document(
    title: str = Form(...),
    category_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    category = db.query(Category).filter(Category.id == category_id, Category.is_active.is_(True)).first()
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    extension = Path(file.filename or "").suffix.lstrip(".").lower()
    user_id = current_user["user_id"]

    document = KnowledgeDocument(
        title=title,
        file_name=file.filename,
        file_path="",
        extension=extension,
        category_id=category_id,
        user_id=user_id,
    )
    document = create_knowledge_document(db, document)

    s3_key = S3PathBuilder.knowledge_document(
        user_id=user_id,
        category_id=category_id,
        document_id=document.id,
        filename=file.filename,
    )
    s3_service.upload_file(file, s3_key)

    document = update_knowledge_document(db, document, file_path=s3_key)
    return _to_response(document)


@router.get("/list", response_model=list[DocumentResponse])
def list_documents(
    category_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    documents = get_knowledge_documents(db, category_id=category_id)
    return [_to_response(document) for document in documents]


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
):
    document = get_knowledge_document_by_id(db, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return _to_response(document)


@router.get("/{document_id}/download")
def download_document(
    document_id: int,
    db: Session = Depends(get_db),
):
    document = get_knowledge_document_by_id(db, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    url = s3_service.generate_presigned_url(document.file_path)
    return RedirectResponse(url=url)


@router.put("/{document_id}", response_model=DocumentResponse)
def update_document(
    document_id: int,
    request: DocumentUpdateRequest,
    db: Session = Depends(get_db),
):
    document = get_knowledge_document_by_id(db, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if request.category_id is not None:
        category = db.query(Category).filter(
            Category.id == request.category_id, Category.is_active.is_(True)
        ).first()
        if category is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    updates = {k: v for k, v in request.model_dump(exclude_unset=True).items() if v is not None}
    document = update_knowledge_document(db, document, **updates)
    return _to_response(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
):
    document = get_knowledge_document_by_id(db, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    delete_knowledge_document(db, document)
    s3_service.delete_file(document.file_path)
