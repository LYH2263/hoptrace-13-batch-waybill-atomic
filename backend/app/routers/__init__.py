from fastapi import APIRouter

from app.routers import batch, core

api = APIRouter()
api.include_router(core.router)
api.include_router(batch.router)
