import logging

from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.core.database import get_db_session
from kiwi.schemas import UserCreate
from kiwi.crud.user import UserCRUD
from kiwi.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def init_db(session: AsyncSession) -> None:
    # Tables should be created with Alembic migrations
    # But if you don't want to use migrations, create
    # the tables un-commenting the next lines

    # This works because the models are already imported and registered from kiwi.models
    # Base.metadata.create_all(engine)

    user = await UserCRUD().get_by_username(session, settings.FIRST_SUPERUSER)
    if not user:
        user_in = UserCreate(
            username=settings.FIRST_SUPERUSER,
            email=settings.FIRST_SUPERUSER_EMAIL,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
        )
        await UserCRUD().create_user(session, user_in.model_dump())


async def init() -> None:
    try:
        db_session_gen = get_db_session()
        session = await db_session_gen.__anext__()  # 获取生成器的第一个值
        await init_db(session)
    except Exception as e:
        logger.error(e)
        raise e


async def main() -> None:
    logger.info("Creating initial data")
    await init()
    logger.info("Initial data created")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
