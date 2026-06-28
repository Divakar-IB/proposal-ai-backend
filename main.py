from fastapi import FastAPI

from router.auth_router import router as auth_router


app = FastAPI(
    title="Proposal AI",
    version="1.0.0",
)


app.include_router(auth_router)


@app.get("/")
def root():

    return {
        "message": "Proposal AI Backend Running"
    }