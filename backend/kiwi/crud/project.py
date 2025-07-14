from kiwi_backend.database import BaseCRUD
from kiwi_backend.models import Project, ProjectMember
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession


class ProjectCRUD(BaseCRUD):
    def __init__(self):
        super().__init__(Project)

    async def create_with_owner(
            self,
            db: AsyncSession,
            project_data: dict,
            owner_id: int
    ):
        """创建项目并添加所有者"""
        project = await self.create(db, project_data)

        # 添加项目所有者
        await self.add_member(
            db,
            project_id=project.id,
            user_id=owner_id,
            role_code=1  # 项目管理员角色ID
        )
        return project

    async def add_member(
            self,
            db: AsyncSession,
            project_id: int,
            user_id: int,
            role_code: int
    ):
        """添加项目成员"""
        # 检查是否已是成员
        stmt = select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            return  # 已是成员则跳过

        # 创建成员关联
        member = ProjectMember(
            project_id=project_id,
            user_id=user_id,
            role_code=role_code
        )
        db.add(member)
        await db.flush()

    async def remove_member(
            self,
            db: AsyncSession,
            project_id: int,
            user_id: int
    ):
        """移除项目成员"""
        stmt = delete(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id
        )
        await db.execute(stmt)
        return True

    async def get_project_members(
            self,
            db: AsyncSession,
            project_id: int
    ):
        """获取项目成员列表"""
        stmt = select(ProjectMember).where(
            ProjectMember.project_id == project_id
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_user_projects(
            self,
            db: AsyncSession,
            user_id: int
    ):
        """获取用户参与的项目"""
        stmt = select(Project).join(ProjectMember).where(
            ProjectMember.user_id == user_id
        )
        result = await db.execute(stmt)
        return result.scalars().all()