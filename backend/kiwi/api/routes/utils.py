from fastapi import APIRouter, Depends, Request
from pydantic.networks import EmailStr

from kiwi.api.deps import get_current_active_superuser, SessionDep, CurrentUser
from kiwi.core.monitoring import metrics_endpoint
from kiwi.core.engine.federation_query_engine import get_engine, get_connection_pool
from kiwi.schemas import Message
from kiwi.utils import generate_test_email, send_email

router = APIRouter(prefix="/utils", tags=["utils"])


@router.post(
    "/test-email/",
    dependencies=[Depends(get_current_active_superuser)],
    status_code=201,
    response_model=Message
)
async def test_email(email_to: EmailStr) -> Message:
    """
    Test emails.
    """
    email_data = generate_test_email(email_to=email_to)
    send_email(
        email_to=email_to,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )
    return Message(message="Test email sent")


@router.get("/health-check/")
async def health_check() -> bool:
    return True


@router.get("/duckdb/status")
async def duckdb_system_status():
    return {
        "duckdb_connections": get_connection_pool().get_pool_stats()
    }


@router.get("/test-duckdb")
async def test_duckdb():
    try:
        query_engine = get_engine()
        result = await query_engine.fetch_one("SELECT 1")
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@router.get("/duckdb/memory/{project_id}")
async def duckdb_memory_usage(
        session: SessionDep,
        current_user: CurrentUser,
        project_id: str
):
    try:
        query_engine = get_engine()
        return await query_engine.get_memory_usage(db=session, project_id=project_id)
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# 添加Prometheus指标端点
# 指标端点认证
@router.get("/metrics")
async def metrics(request: Request):
    return await metrics_endpoint(request)
