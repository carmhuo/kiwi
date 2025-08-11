import json
import uuid
import time
from typing import Dict, Any, Callable, Awaitable

from fastapi import Request
from fastapi.responses import (
    JSONResponse,  # 用于构建JSON响应
    Response,     # 基础响应类
    StreamingResponse  # 如果需要处理流式响应
)

from kiwi.core.config import logger as app_logger
from kiwi.core.monitoring import timing_metrics, AGENT_ERRORS, AGENT_SQL_GEN_LATENCY


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


async def monitor_requests(request: Request, call_next):
    path = request.url.path
    method = request.method

    # 跳过指标端点自身监控
    if path == "/metrics":
        return await call_next(request)

    # 监控Agent请求
    if "/agents/" in path:
        labels = {"path": path, "method": method}
        async with timing_metrics(AGENT_SQL_GEN_LATENCY, labels):
            response = await call_next(request)

            # 记录错误
            if response.status_code >= 400:
                AGENT_ERRORS.inc({
                    "path": path,
                    "method": method,
                    "status": response.status_code
                })

            return response

    return await call_next(request)


async def response_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """纯函数式响应标准化中间件"""

    # 跳过特定路径
    skip_paths = {"/openapi.json", "/docs", "/redoc", "/metrics"}
    if request.url.path in skip_paths:
        return await call_next(request)

    response = await call_next(request)

    if isinstance(response, StreamingResponse):
        # 可以选择在这里对流式响应添加额外header等操作
        response.headers["X-Processed-By"] = "middleware"
        return response

    # 检查是否需要处理
    content_type = response.headers.get("content-type", "")
    if not (response.status_code == 200 and content_type.startswith("application/json")):
        return response

    try:
        body = b"".join([chunk async for chunk in response.body_iterator])
        raw_data = json.loads(body)

        # 已经是标准格式则直接返回
        if isinstance(raw_data, dict) and all(k in raw_data for k in ("code", "data", "msg")):
            return JSONResponse(
                content=raw_data,
                status_code=response.status_code,
                headers={k: v for k, v in response.headers.items()
                         if k.lower() not in ("content-length", "content-type")}
            )

        # 转换为标准格式
        return JSONResponse(
            content={"code": 0, "data": raw_data, "msg": None},
            status_code=response.status_code,
            headers={k: v for k, v in response.headers.items()
                     if k.lower() not in ("content-length", "content-type")}
        )

    except json.JSONDecodeError:
        return response
    except Exception as e:
        app_logger.error("响应处理错误", extra={
            "request_id": request.state.request_id,
            "error": str(e),
            "path": request.url.path
        })
        return JSONResponse(
            status_code=500,
            content={"code": 500, "msg": "服务器响应处理错误", "data": None}
        )
