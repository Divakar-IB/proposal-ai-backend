from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from middleware.auth_middleware import generic_exception_handler, sqlalchemy_exception_handler
from router.auth_router import router as auth_router

app = FastAPI(
    title="Proposal AI",
    version="1.0.0",
)

app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

app.include_router(auth_router)


@app.get("/")
def root():
    return {"message": "Proposal AI Backend Running"}
