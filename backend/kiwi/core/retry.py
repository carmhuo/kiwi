import asyncio
import time
from functools import wraps
from typing import Callable, Any

from kiwi.core.config import logger


def async_retry(
        max_retries: int = 3,
        initial_delay: float = 0.1,
        backoff_factor: float = 2.0,
        exceptions: tuple = (Exception,)
):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            delay = initial_delay
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries:
                        raise

                    wait_time = delay * (backoff_factor ** (attempt - 1))
                    logger.warning(f"Attempt {attempt} failed, retrying in {wait_time:.1f}s: {e}")
                    await asyncio.sleep(wait_time)

        return wrapper

    return decorator
