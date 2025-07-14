import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.crud.project import ProjectCRUD
from kiwi.api.schemas import (
    Project,
    ProjectResponse,
    ProjectsResponse,
    ProjectCreate,
    ProjectUpdate,
    Message
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
):
    # 根据用户角色返回可见项目
    projects = await get_projects_by_user(db, user_id=current_user.id, skip=skip, limit=limit)
    return projects


@router.get("/{project_id}", response_model=ProjectResponse)
async def read_project(
        session: SessionDep,
        project_id: int,
        current_user: CurrentUser):
    project = await get_project(db, project_id=project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 检查用户是否有权限访问项目
    if not current_user.has_project_access(project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问此项目"
        )

    return project


@router.post("/", response_model=ProjectResponse)
async def create_project(
        session: SessionDep,
        project: ProjectCreate,
        current_user: CurrentUser
) -> Any:
    # 检查用户是否有权限创建项目
    if not current_user.has_permission("create_project"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足"
        )

    return await ProjectCRUD().create_with_owner(db=db, project=project, owner_id=current_user.id)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
        session: SessionDep,
        project_id: uuid.UUID,
        project_in: ProjectUpdate,
        current_user: CurrentUser
) -> Any:
    """
        Update an project.
    """
    project = session.get(Project, id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    if not current_user.is_superuser and (project.owner_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")
    update_dict = project_in.model_dump(exclude_unset=True)
    project.sqlmodel_update(update_dict)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.delete("/{project_id}")
def delete_item(
        session: SessionDep, current_user: CurrentUser, project_id: uuid.UUID
) -> Message:
    """
    Delete an project.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and (project.owner_id != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")
    session.delete(project)
    session.commit()
    return Message(message="project deleted successfully")
