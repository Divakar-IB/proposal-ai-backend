from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.dependency import get_current_user
from database.crud import (
    count_active_documents_in_category,
    deactivate_category,
    get_category_by_id,
    get_category_by_name_including_deleted,
    reactivate_category,
)
from database.database import get_db
from database.models import Category, KnowledgeDocument
from schemas.category import CategoryRequest
from utilities.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/category", tags=["Categories"])


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
            raise HTTPException(status_code=404, detail="Category not found")
        existing_result = await db.execute(
            select(Category).filter(
                Category.name == request.name,
                Category.id != request.id,
                Category.is_active.is_(True),
            )
        )
        existing = existing_result.scalars().first()
        if existing:
            raise HTTPException(status_code=400, detail="Category name already exists")

        category.name = request.name
        category.description = request.description
        message = "Category updated successfully"

    else:
        # Create. Category.name is UNIQUE at the DB level and deletion is a
        # soft delete, so a previously deleted category still occupies its
        # name while being invisible to /category/list. Revive that row
        # instead of rejecting the request — otherwise a name can never be
        # reused once deleted.
        existing = await get_category_by_name_including_deleted(db, request.name)
        if existing is not None and existing.is_active:
            raise HTTPException(status_code=400, detail="Category name already exists")
        if existing is not None:
            await reactivate_category(db, existing, description=request.description)
            return JSONResponse(
                status_code=200,
                content={"message": "Category created successfully"},
            )

        category = Category(name=request.name, description=request.description)
        db.add(category)
        message = "Category created successfully"

    await db.commit()
    return JSONResponse(status_code=200, content={"message": message})


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
        status_code=status.HTTP_200_OK,
        content={
            "data": [
                {"id": res.id, "name": res.name, "description": res.description, "document_count": res.document_count}
                for res in result
            ]
        },
    )


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Soft-deletes a category (`is_active = False`), matching how every other
    resource in this codebase is deleted.

    Refuses with 409 while active knowledge documents still reference it.
    `KnowledgeDocument.category_id` is a non-nullable FK, so those documents
    would keep working but point at a category that no longer appears in
    /category/list — and their Pinecone vectors carry `category_id` in
    metadata. Reassign or delete the documents first; the 409 reports how many
    are in the way.
    """

    category = await get_category_by_id(db, category_id)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    document_count = await count_active_documents_in_category(db, category_id)
    if document_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot delete '{category.name}' — {document_count} document(s) still "
                "use this category. Move them to another category or delete them first."
            ),
        )

    await deactivate_category(db, category)
    logger.info("category deleted | category_id=%s name=%s", category_id, category.name)
