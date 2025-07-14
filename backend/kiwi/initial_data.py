import logging

from sqlalchemy.ext.asyncio import AsyncSession


from kiwi.core.database import AsyncSessionLocal
from kiwi.api.schemas import UserCreate
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

    user = await UserCRUD().get_user_by_email(session, settings.FIRST_SUPERUSER)
    if not user:
        user_in = UserCreate(
            username="admin",
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
        )
        user = await UserCRUD().create_user(session, user_in.model_dump())


async def init() -> None:
    try:
        async with AsyncSessionLocal() as session:
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
