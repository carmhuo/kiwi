from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from kiwi.schemas import (
    AgentCreate,
    AgentResponse,
    AgentUpdate,
    AgentVersionResponse,
    AgentVersionCreate,
    AgentMetricCreate,
    AgentsResponse, AgentVersionRollback, AgentVersionsResponse
)

from kiwi.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)

from kiwi.crud.agent import AgentCRUD
from kiwi.crud.project import ProjectCRUD

router = APIRouter(prefix="/agents", tags=["agents"])


# 权限检查 - 确保用户有Agent管理权限
async def verify_agent_permission(
        project_id: str,
        current_user: CurrentUser,
        db: SessionDep
):
    # 系统管理员拥有所有权限
    if current_user.is_superuser:
        return True

    # 检查项目成员权限
    project_member = await ProjectCRUD().get_project_member(db, project_id, current_user.id)
    if not project_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问此项目"
        )

    # 检查角色权限 (项目管理员或数据源管理员)
    if project_member.role_code not in [0, 1]:  # 0=系统管理员,1=项目管理员
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权管理Agent"
        )
    return True


@router.post("/", response_model=AgentResponse)
async def create_agent(
        agent: AgentCreate,
        db: SessionDep,
        current_user: CurrentUser,
        _: bool = Depends(verify_agent_permission)
):
    project_id = agent.project_id
    # 检查项目是否存在
    if not project_id and not await ProjectCRUD().get_project_by_id(db, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="项目不存在"
        )
    # 检查agent name是否存在
    if await AgentCRUD().get_agent_by_name(db, agent.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent已存在"
        )
    # 创建Agent
    agent_data = agent.model_dump()
    agent_data["project_id"] = project_id
    return await AgentCRUD().create_agent(db, agent_data, current_user.id)


@router.get("/project/{project_id}", response_model=AgentsResponse)
async def list_agents_by_project(
        db: SessionDep,
        current_user: CurrentUser,
        project_id: str,
        skip: int = 0,
        limit: int = 100,
        _: bool = Depends(verify_agent_permission)
):
    if not await ProjectCRUD().get_project_by_id(db, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="项目不存在"
        )
    count = await AgentCRUD().count(db, project_id=project_id)
    agents = await AgentCRUD().list_agents(db, project_id, skip, limit)

    return AgentsResponse(data=agents, count=count)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
        agent_id: str,
        db: SessionDep,
        current_user: CurrentUser
):
    agent = await AgentCRUD().get_agent(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent不存在"
        )

    # 检查项目权限
    await verify_agent_permission(agent.project_id, current_user, db)
    return agent


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
        agent_id: str,
        agent_update: AgentUpdate,
        db: SessionDep,
        current_user: CurrentUser
):
    agent = await AgentCRUD().get_agent(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent不存在"
        )

    # 检查权限
    await verify_agent_permission(agent.project_id, current_user, db)

    # 更新Agent
    return await AgentCRUD().update_agent(
        db, agent_id, agent_update.model_dump(exclude_unset=True), current_user.id
    )

@router.get("/{agent_id}/versions", response_model=AgentVersionsResponse)
async def list_agent_versions(
        agent_id: str,
        db: SessionDep,
        current_user: CurrentUser,
        skip: int = 0,
        limit: int = 100
):
    count = await AgentCRUD().count_agent_versions(db, agent_id)
    agent_versions = await AgentCRUD().list_agent_versions(db, agent_id, skip, limit)
    return AgentVersionsResponse(data=agent_versions, count=count)

@router.post("/{agent_id}/rollback", response_model=AgentResponse)
async def rollback_agent_version(
        agent_id: str,
        version_data: AgentVersionRollback,
        db: SessionDep,
        current_user: CurrentUser
):
    agent = await AgentCRUD().get_agent(db, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent不存在"
        )

    # 检查权限
    await verify_agent_permission(agent.project_id, current_user, db)

    # 执行版本回滚
    result = await AgentCRUD().rollback_version(
        db, agent_id, version_data.version, current_user.id
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="回滚版本不存在"
        )
    return result


@router.post("/agent_versions/{version_id}/metrics")
async def record_agent_metric(
        version_id: str,
        metric: AgentMetricCreate,
        db: SessionDep
):
    return await AgentCRUD().record_metric(db, version_id, metric.model_dump())
