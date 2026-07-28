from fastapi import (
    APIRouter,
    HTTPException,
    status,
    Depends
)
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from authentication.dependency import get_current_user
from database.database import get_db
from database.models import Category, KnowledgeDocument
from schemas.category import CategoryRequest
from constants import KNOWLEDGE_CATEGORIES

router = APIRouter(
    prefix='/category',
    tags=["Categories"]
    )


@router.post("")
async def create_or_update_category(
    request: CategoryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if request.id:
        # Update
        result = await db.execute(select(Category).filter(Category.id == request.id))
        category = result.scalars().first()
        if not category:
            raise HTTPException(
                status_code=404,
                detail="Category not found"
            )
        existing_result = await db.execute(
            select(Category).filter(
                Category.name == request.name,
                Category.id != request.id
            )
        )
        existing = existing_result.scalars().first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Category name already exists"
            )

        category.name = request.name
        category.description = request.description
        message = "Category updated successfully"

    else:
        # Create
        existing_result = await db.execute(select(Category).filter(Category.name == request.name))
        existing = existing_result.scalars().first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Category name already exists"
            )
        category = Category(
            name=request.name,
            description=request.description
        )
        db.add(category)
        message = "Category created successfully"

    await db.commit()
    return JSONResponse(
        status_code=200,
        content={"message": message}
    )


@router.get("/list")
async def get_categories(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    query_result = await db.execute(
        select(
            Category.id,
            Category.name,
            Category.description,
            func.count(KnowledgeDocument.id).label("document_count"),
        )
        .outerjoin(
            KnowledgeDocument,
            (KnowledgeDocument.category_id == Category.id) & KnowledgeDocument.is_active.is_(True),
        )
        .filter(Category.is_active.is_(True))
        .group_by(Category.id)
    )
    result = query_result.all()

    return JSONResponse(
        status_code=status.HTTP_200_OK,content={
            "data":[
                {
                "id":res.id,
                "name":res.name,
                "description": res.description,
                "document_count": res.document_count
                }
                for res in result
            ]
        }
    )