from typing import Any, Callable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select


async def paginate(
    db: AsyncSession,
    query: Select,
    *,
    page: int = 1,
    limit: int = 10,
    serializer: Optional[Callable[[Any], Any]] = None,
) -> dict:
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    total_pages = (total + limit - 1) // limit if limit > 0 else 0

    rows = (await db.execute(query.offset((page - 1) * limit).limit(limit))).scalars().all()
    data = [serializer(row) for row in rows] if serializer else list(rows)

    return {
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "total": total,
        "data": data,
    }
