from typing import Optional, List

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from kiwi.schemas import (
    MessageCreate,
    MessageResponse,
    ConversationResponse,
    FeedbackCreate, ConversationsResponse, Message, ConversationDetailResponse
)
from kiwi.api.deps import (
    CurrentUser,
    SessionDep,
    ProjectMember,
)
from kiwi.core.services.conversation_service import ConversationService
from kiwi.core.config import logger

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/messages", response_model=MessageResponse)
async def create_message(
        message: MessageCreate,
        project_id: str,
        db: SessionDep,
        current_user: CurrentUser,
        is_member: ProjectMember
):
    """
    发送消息到对话
    - 如果conversation_id为空，创建新对话
    - 调用Agent生成SQL并执行
    - 返回系统响应
    """
    service = ConversationService(db, current_user.id)
    try:
        return await service.process_message(message, project_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"处理消息失败: {str(e)}"
        )


@router.post("/completion/astream")
async def chat(
        message: MessageCreate,
        project_id: str,
        db: SessionDep,
        current_user: CurrentUser,
        is_member: ProjectMember
):
    """
        Endpoint to stream the agent's responses using Server-Sent Events.
        Expects JSON: {"messages": [{"role": "user", "content": "Your query"}]}
        """
    try:
        service = ConversationService(db, current_user.id)
        return StreamingResponse(
            service.event_stream_generator(message, project_id),
            media_type="text/event-stream"
        )

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        import traceback
        await logger.aerror(f"Error in /api/astream: {e}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/completion/ainvoke")
async def completion(
        messages: MessageCreate,
        project_id: str,
        db: SessionDep,
        current_user: CurrentUser,
        is_member: ProjectMember
):
    """
        一次性获取完整结果
        Expects JSON: {"messages": [{"role": "user", "content": "Your query"}]}
        """
    try:
        service = ConversationService(db, current_user.id)
        return await service.invoke_agent_endpoint(messages, project_id)

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        import traceback
        await logger.aerror(f"Error in /completion/ainvoke: {e}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/completion/human-in-the-loop")
async def human_in_the_loop(
        messages: List[MessageCreate],
        project_id: str,
        db: SessionDep,
        current_user: CurrentUser,
        is_member: ProjectMember
):
    pass


@router.get("/", response_model=ConversationsResponse)
async def list_conversations(
        db: SessionDep,
        current_user: CurrentUser,
        project_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
):
    """
    获取用户对话列表
    - 可按项目筛选
    - 分页支持
    """
    service = ConversationService(db, current_user.id)
    try:

        conversations, count = await service.get_user_conversations(project_id, skip, limit)
        return ConversationsResponse(data=conversations, count=count)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取对话列表失败: {str(e)}"
        )


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation_detail(
        conversation_id: str,
        db: SessionDep,
        current_user: CurrentUser
):
    """
       获取对话详情，包括所有消息
       """
    service = ConversationService(db, current_user.id)
    try:
        conversation = await service.get_conversation_detail(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="对话不存在")
        return conversation
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取对话详情失败: {str(e)}"
        )


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def record_feedback(
        feedback: FeedbackCreate,
        db: SessionDep,
        current_user: CurrentUser
):
    """
       提交用户反馈
       - 反馈类型: 0=错误,1=正确,2=部分正确,3=建议改进
    """
    service = ConversationService(db, current_user.id)
    try:
        await service.record_feedback(feedback.model_dump())
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"记录反馈失败: {str(e)}"
        )


@router.get("/health")
async def health_check():
    raise NotImplemented
    # return {
    #     "status": "ok",
    #     "services": {
    #         "database": await check_db_health(),
    #         "cache": await check_cache_health(),
    #         "llm": await check_llm_health()
    #     }
    # }


@router.post("/download_csv")
async def download_csv(user: CurrentUser, id: str):
    """Download CSV
    ---
    parameters:
      - name: user
        in: query
      - name: id
        in: query|body
        type: string
        required: true
    responses:
      200:
        description: download CSV
    """
    # df = get_from_cache()
    # csv = df.to_csv()
    #
    # return Response(
    #     csv,
    #     mimetype="text/csv",
    #     headers={"Content-disposition": f"attachment; filename={id}.csv"},
    # )
    raise NotImplementedError


@router.post("/generate_plotly_figure")
async def generate_plotly_figure(user: CurrentUser, id: str, df, question, sql):
    raise NotImplementedError
