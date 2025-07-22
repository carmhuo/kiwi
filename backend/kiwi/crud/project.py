from typing import Sequence, List

from kiwi.core.database import BaseCRUD
from kiwi.models import Project, ProjectMember, UserRole, ProjectDataSource
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession


class ProjectCRUD(BaseCRUD):
    def __init__(self):
        super().__init__(Project)

    async def create_with_owner(
            self,
            db: AsyncSession,
            project_data: dict,
            owner_id: str
    ):
        """创建项目并添加所有者"""
        project_data["owner_id"] = owner_id
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
            project_id: str,
            user_id: str,
            role_code: int
    ) -> ProjectMember:
        """添加项目成员"""
        # 检查是否已是成员
        stmt = select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            return result.scalar_one_or_none()

        # 创建成员关联
        member = ProjectMember(
            project_id=project_id,
            user_id=user_id,
            role_code=role_code
        )
        db.add(member)
        await db.flush()
        return member

    async def remove_member(
            self,
            db: AsyncSession,
            project_id: str,
            user_id: str
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
            project_id: str
    ) -> Sequence[ProjectMember]:
        """获取项目成员列表"""
        stmt = select(ProjectMember).where(
            ProjectMember.project_id == project_id
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_user_projects(
            self,
            db: AsyncSession,
            user_id: str
    ):
        """获取用户参与的项目"""
        stmt = select(Project).join(ProjectMember).where(
            ProjectMember.user_id == user_id
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def has_user_project_access(db: AsyncSession, project_id: str, user_id: str):
        """判断用户是否是该项目成员"""
        return bool(ProjectCRUD.get_user_project_role(db, project_id, user_id))

    @staticmethod
    async def get_user_project_role(db: AsyncSession, project_id, user_id) -> ProjectMember:
        """检查用户是否具备项目管理操作，仅系统管理员和项目管理员可以创建和删除项目"""
        stmt = select(ProjectMember).where(ProjectMember.project_id == project_id,
                                           ProjectMember.user_id == user_id)
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_by_project_name(self, db: AsyncSession, project_name: str) -> Project:
        """根据项目名称检索项目"""
        return await self.get_by_field(db, "name", project_name)

    async def get_project_details(self, db: AsyncSession, project_id: str):
        """获取项目详细信息，包括成员、数据源、数据集等"""
        project = await self.get(db, id=project_id)

        members = await self.get_project_members(db, project_id=project_id)
        data_sources = await self.get_project_data_sources(db, project_id=project_id)
        datasets = await self.get_project_datasets(db, project_id=project_id)

        return {
            "project": project,
            "members": members,
            "data_sources": data_sources,
            "datasets": datasets
        }

    async def get_project_data_sources(self, db: AsyncSession, project_id: str):
        """获取项目下的所有数据源"""
        from kiwi.crud.data_source import DataSourceCRUD
        ds_crud = DataSourceCRUD()
        return await ds_crud.get_multi(db, project_id=project_id)

    async def get_project_datasets(self, db: AsyncSession, project_id: str):
        """获取项目下的所有数据集"""
        from kiwi.crud.dataset import DatasetCRUD
        ds_crud = DatasetCRUD()
        return await ds_crud.get_multi(db, project_id=project_id)

    async def bind_data_sources(
            self,
            db: AsyncSession,
            project_id: str,
            data_source_ids: List[str],
            aliases: List[str]
    ):
        """
        绑定一个或多个数据源到项目，并为每个数据源指定别名。

        参数:
            db (AsyncSession): 数据库会话
            project_id (str): 项目ID
            data_source_ids (List[str]): 数据源ID列表
            aliases (List[str]): 数据源别名列表

        返回:
            List[ProjectDataSource]: 创建的 ProjectDataSource 对象列表
        """
        if len(data_source_ids) != len(aliases):
            raise ValueError("数据源ID和别名的数量必须一致")

        project = await self.get(db, id=project_id)
        if not project:
            raise ValueError("项目不存在")

        created_relations = []

        for data_source_id, alias in zip(data_source_ids, aliases):
            # 检查是否已经绑定
            stmt = select(ProjectDataSource).where(
                ProjectDataSource.project_id == project_id,
                ProjectDataSource.data_source_id == data_source_id
            )
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                continue  # 跳过已存在的绑定

            # 创建新的绑定关系
            relation = ProjectDataSource(
                project_id=project_id,
                data_source_id=data_source_id,
                alias=alias
            )
            db.add(relation)
            created_relations.append(relation)

        await db.flush()
        return created_relations
