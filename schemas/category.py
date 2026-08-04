from pydantic import BaseModel


class CategoryRequest(BaseModel):
    id: int | None = None
    name: str
    description: str
