import time
from contextlib import asynccontextmanager
from aioprometheus import Counter, Gauge, Histogram, Registry
from fastapi import Request, Response
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

from kiwi.core.config import settings

# 创建全局监控注册表
MONITOR_REGISTRY = Registry()

# 定义核心指标
AGENT_SQL_GEN_LATENCY = Histogram(
    "agent_sql_gen_latency_seconds",
    "SQL generation latency distribution",
    registry=MONITOR_REGISTRY
)

AGENT_QUERY_SUCCESS_RATE = Gauge(
    "agent_query_success_rate",
    "Agent query success rate",
    registry=MONITOR_REGISTRY
)

AGENT_ACTIVE_REQUESTS = Gauge(
    "agent_active_requests",
    "Number of active requests",
    registry=MONITOR_REGISTRY
)

AGENT_ERRORS = Counter(
    "agent_errors_total",
    "Total agent errors",
    registry=MONITOR_REGISTRY
)

DATABASE_QUERY_DURATION = Histogram(
    "database_query_duration_seconds",
    "Database query duration",
    registry=MONITOR_REGISTRY
)

CHART_GEN_LATENCY = Histogram(
    "chart_gen_latency_seconds",
    "Chart generation latency distribution",
    registry=MONITOR_REGISTRY
)


# 分布式追踪配置
def configure_tracing(service_name: str):
    resource = Resource(attributes={"service.name": service_name})
    tracer_provider = TracerProvider(resource=resource)

    # 生产环境使用OTLP导出到Jaeger/Tempo
    otlp_exporter = OTLPSpanExporter(endpoint="http://jaeger:4317", insecure=True)
    tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    # 开发环境使用控制台输出
    if settings.ENVIRONMENT == "local":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter
        tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(tracer_provider)


# 性能剖析中间件
@asynccontextmanager
async def timing_metrics(metric: Histogram, labels: dict = None):
    start_time = time.perf_counter()
    AGENT_ACTIVE_REQUESTS.inc(labels or {})
    try:
        yield
    finally:
        duration = time.perf_counter() - start_time
        metric.observe(duration, labels or {})
        AGENT_ACTIVE_REQUESTS.dec(labels or {})


# 错误监控装饰器
def track_errors(metric: Counter):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                metric.inc({"error_type": type(e).__name__})
                raise

        return wrapper

    return decorator


# 数据库查询监控
@asynccontextmanager
async def track_db_query(query_name: str):
    start_time = time.perf_counter()
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(f"db:{query_name}") as span:
        span.set_attribute("db.query", query_name)
        try:
            yield
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            raise
        finally:
            duration = time.perf_counter() - start_time
            DATABASE_QUERY_DURATION.observe(duration, {"query": query_name})


# 指标端点生成器
async def metrics_endpoint(request: Request) -> str:
    content, http_headers = await render(MONITOR_REGISTRY, request.headers.get("accept"))
    return Response(content, media_type=http_headers["Content-Type"])