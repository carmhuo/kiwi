from collections.abc import Generator, AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from kiwi.core.config import settings
from kiwi.main import app
from kiwi.models import User, Base
from kiwi.tests.utils.user import authentication_token_from_email
from kiwi.tests.utils.utils import get_superuser_token_headers
from kiwi.initial_data import init_db

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def engine():
    """创建测试数据库引擎"""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True
    )

    # 创建所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    """获取异步数据库会话的上下文管理器"""
    AsyncSessionLocal = sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False
    )
    async with AsyncSessionLocal() as session:
        try:
            await init_db(session)
            yield session
            await session.execute(delete(User))
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# @pytest.fixture(scope="session", autouse=True)
# def db() -> Generator[Session, None, None]:
#     with Session(engine) as session:
#         init_db(session)
#         yield session
#         statement = delete(Item)
#         session.execute(statement)
#         statement = delete(User)
#         session.execute(statement)
#         session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
async def normal_user_token_headers(client: TestClient, db: AsyncSession) -> dict[str, str]:
    return await authentication_token_from_email(
        client=client, username=settings.TEST_USERNAME ,email=settings.EMAIL_TEST_USER, db=db
    )
