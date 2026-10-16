from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.db import DbSession
from app.routers import listings

app = FastAPI(title="Housing API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(listings.router)


@app.get("/api/health")
def health(db: DbSession):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "ok"}
