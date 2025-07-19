from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from kiwi.api.main import api_router
from kiwi.core.config import settings, logger
from kiwi.core.middleware import log_middleware
from kiwi.core.database import init_db, close_db


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    await logger.ainfo(
        "Application starting",
        extra={
            "app_name": settings.APP_NAME,
            "environment": settings.ENVIRONMENT,
            "version": settings.VERSION,
            "log_level": settings.LOG_LEVEL
        }
    )
    await init_db()
    await logger.ainfo("Database connection test successful")

    yield

    await logger.ainfo("Application shutting down")
    await close_db()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)

# Set all CORS enabled origins
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,  # type: ignore
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# 添加日志中间件
app.middleware("http")(log_middleware)

# 添加路由
app.include_router(api_router, prefix=settings.API_V1_STR)
