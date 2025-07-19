from fastapi import APIRouter

from kiwi.api.routes import login, private, users, utils, projects, data_sources, datasets
from kiwi.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(projects.router)
api_router.include_router(data_sources.router)
api_router.include_router(datasets.router)
api_router.include_router(utils.router)

if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
