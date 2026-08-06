from typing import Optional

from pydantic import BaseModel


class CategoryRequest(BaseModel):
    id: Optional[int] = None
    name: str
    description: str
