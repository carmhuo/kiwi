import uuid
import time

from fastapi import Request, Response
from kiwi.core.logger import Logger
from kiwi.core.config import logger as app_logger


async def log_middleware(request: Request, call_next) -> Response:
    """日志中间件，记录所有请求和响应信息
    功能：
    1. 为每个请求生成唯一ID
    2. 记录请求开始信息
    3. 记录请求处理时间
    4. 记录响应信息
    5. 记录异常信息
    6. 添加请求ID到响应头
    """

    # 生成唯一请求ID
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    # 记录请求开始
    start_time = time.time()
    await app_logger.ainfo(
        "Request started",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "client": request.client.host if request.client else None
        }
    )
    # 处理请求并捕获异常
    try:
        response = await call_next(request)
    except Exception as e:
        # 记录未处理异常
        await app_logger.aerror(
            "Unhandled exception",
            extra={
                "request_id": request_id,
                "exception_type": type(e).__name__,
                "exception_msg": str(e)
            }
        )
        raise

        # 计算处理时间
    process_time = time.time() - start_time
    request.state.process_time = process_time

    # 记录响应信息
    await app_logger.ainfo(
        "Request completed",
        extra={
            "request_id": request_id,
            "status_code": response.status_code,
            "process_time": f"{process_time:.4f}s"
        }
    )

    # 添加请求ID到响应头
    response.headers["X-Request-ID"] = request_id
    return response


# 在中间件中添加敏感信息过滤
def sanitize_headers(headers: dict) -> dict:
    sensitive_keys = ["authorization", "cookie", "set-cookie"]
    return {k: "***" if k.lower() in sensitive_keys else v for k, v in headers.items()}


# 在日志记录中使用
# await logger.ainfo("Request started", extra={
#     "headers": sanitize_headers(dict(request.headers))
# })
