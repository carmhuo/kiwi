from typing import Any, Optional, List

from fastapi import APIRouter, Depends, HTTPException, status

from kiwi.crud.project import ProjectCRUD
from kiwi.schemas import (
    ProjectResponse,
    ProjectsResponse,
    ProjectCreate,
    ProjectUpdate,
    Message, ProjectDetail
)
from kiwi.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/", response_model=ProjectsResponse)
async def read_projects(
        session: SessionDep,
        current_user: CurrentUser,
        skip: int = 0,
        limit: int = 100
) -> Any:
    """获取所有项目信息"""
    crud = ProjectCRUD()
    count = await crud.count(session)
    projects = await crud.get_multi(session, skip, limit)
    return ProjectsResponse(data=projects, count=count, skip=skip, limit=limit)


@router.get("/", response_model=ProjectsResponse)
async def read_projects_me(
        session: SessionDep,
        current_user: CurrentUser,
        skip: int = 0,
        limit: int = 100
) -> Any:
    """获取用户已加入项目信息"""
    crud = ProjectCRUD()

    count = await crud.count(session, user_id=current_user.id)
    projects = await crud.get_user_projects(session, user_id=current_user.id)

    return ProjectsResponse(data=projects, count=count, skip=skip, limit=limit)


@router.get("/{project_id}", response_model=ProjectDetail)
async def read_project_detail(
        session: SessionDep,
        project_id: str,
        current_user: CurrentUser):
    # 检查用户是否有权限访问项目
    has_access = await ProjectCRUD().has_user_project_access(session, project_id=project_id, user_id=current_user.id)
    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user is not a member of the project"
        )

    project = await ProjectCRUD().get_project_details(session, project_id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    return ProjectDetail(
        project=project,
        members=project.members,
        data_sources=project.data_sources,
        datasets=project.datasets
    )


@router.post("/",
             dependencies=[Depends(get_current_active_superuser)],
             response_model=ProjectResponse)
async def create_project(
        session: SessionDep,
        project: ProjectCreate,
        current_user: CurrentUser
) -> Any:
    exists_project = await ProjectCRUD().get_by_project_name(session, project.name)
    if exists_project:
        raise HTTPException(status_code=404, detail="Project already created")
    return await ProjectCRUD().create_with_owner(session, project.model_dump(), owner_id=current_user.id)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
        session: SessionDep,
        project_id: str,
        project_in: ProjectUpdate,
        current_user: CurrentUser
) -> Any:
    """
        Update a project.
    """
    project = await ProjectCRUD().get(session, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not current_user.is_superuser and (project.owner_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")
    update_dict = project_in.model_dump(exclude_unset=True)
    await ProjectCRUD().update(session, project, update_dict)
    return project


@router.post("/{project_id}/members", response_model=Message)
async def add_project_member_with_role(
        session: SessionDep,
        project_id: str,
        user_id: str,
        role_code: int,
        current_user: CurrentUser
) -> Message:
    """
    添加用户到项目并指定角色
    """
    # 检查项目是否存在
    project = await ProjectCRUD().get(session, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not current_user.is_superuser:
        # 检查当前用户是否有权限添加成员
        project_member = await ProjectCRUD().get_user_project_role(
            session, project_id=project_id, user_id=current_user.id
        )
        if (not project_member) or (project_member.role_code > 1):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough privileges to add members to this project"
            )

    # 添加成员并指定角色
    await ProjectCRUD().add_member(
        session,
        project_id=project_id,
        user_id=user_id,
        role_code=role_code
    )

    return Message(message="User added to the project with specified role successfully")


@router.post("/{project_id}/bind-data-sources")
async def bind_data_sources(
        session: SessionDep,
        current_user: CurrentUser,
        project_id: str,
        data_source_ids: List[str],
        aliases: Optional[List[str]] = None

) -> Message:
    """
    绑定一个或多个数据源到项目，并为每个数据源指定别名（若未提供则使用默认别名）。

    参数:
        db (AsyncSession): 数据库会话
        project_id (str): 项目ID
        data_source_ids (List[str]): 数据源ID列表
        aliases (Optional[List[str]]): 数据源别名列表（可选）

    返回:
        List[ProjectDataSource]: 创建的 ProjectDataSource 对象列表
    """
    if aliases is None:
        # 若未提供别名，则使用 data_source_id 作为默认值
        aliases = data_source_ids

    if len(data_source_ids) != len(aliases):
        raise ValueError("数据源ID和别名的数量必须一致")

    await ProjectCRUD().bind_data_sources(
        session,
        project_id=project_id,
        data_source_ids=data_source_ids,
        aliases=aliases
    )

    return Message(message="Data source bind successfully")


@router.delete("/{project_id}")
async def delete_project(
        session: SessionDep, current_user: CurrentUser, project_id: str
) -> Message:
    """
    Delete a project. 注意，删除项目需要删除关联的用户，数据集
    """
    project = await ProjectCRUD().get(session, id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not current_user.is_superuser and (project.owner_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")
    await ProjectCRUD().delete(session, project_id)
    # TODO 删除项目需要删除关联的用户，数据集
    return Message(message="Project deleted successfully")
