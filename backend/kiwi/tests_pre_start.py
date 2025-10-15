import logging

from sqlalchemy import select
from tenacity import after_log, before_log, retry, stop_after_attempt, wait_fixed

from kiwi.core.database import get_db_session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

max_tries = 60 * 5  # 5 minutes
wait_seconds = 1


@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.WARN),
)
async def init() -> None:
    try:
        db_session_gen = get_db_session()
        session = await db_session_gen.__anext__()  # 获取生成器的第一个值
        try:
            await session.execute(select(1))
        finally:
            try:
                await db_session_gen.__anext__()  # 触发生成器结束
            except StopAsyncIteration:
                pass  # 这是期望的行为
    except Exception as e:
        logger.error(e)
        raise e


async def main() -> None:
    logger.info("Initializing service")
    await init()
    logger.info("Service finished initializing")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
