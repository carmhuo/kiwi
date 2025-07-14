from typing import List

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.core.database import BaseCRUD
from kiwi.core.security import verify_password, get_password_hash
from kiwi.models import User, UserRole, Role, ProjectMember


class UserCRUD(BaseCRUD):
    def __init__(self):
        super().__init__(User)

    async def get_user_by_id(self, db: AsyncSession, user_id: str) -> User:
        """根据用户ID获取用户"""
        return await self.get_by_field(db, "id", user_id)

    async def get_by_username(self, db: AsyncSession, username: str) -> User:
        """根据用户名获取用户"""
        return await self.get_by_field(db, "username", username)

    async def get_user_by_email(self, db: AsyncSession, email: str) -> User:
        """根据邮箱获取用户"""
        return await self.get_by_field(db, "email", email)

    async def create_user(
            self,
            db: AsyncSession,
            user_data: dict
    ):
        """创建用户"""
        # 创建用户
        user_data["hashed_password"] = get_password_hash(user_data.pop("password"))  # 加密并改名
        user = await self.create(db, user_data)
        return user

    async def create_with_role(
            self,
            db: AsyncSession,
            user_data: dict,
            role_code: int
    ):
        """创建用户并分配角色"""
        # 创建用户
        user = await self.create(db, user_data)

        # 分配角色
        await self.assign_role(db, user.id, role_code)
        return user

    async def assign_role(
            self,
            db: AsyncSession,
            user_id: str,
            role_code: int
    ):
        """为用户分配角色"""
        # 检查角色是否存在
        role = await db.get(Role, role_code)
        if not role:
            raise ValueError(f"角色ID {role_code} 不存在")

        # 检查是否已分配
        stmt = select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_code == role_code
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            return  # 已分配则跳过

        # 创建关联
        user_role = UserRole(user_id=user_id, role_code=role_code)
        db.add(user_role)
        await db.flush()

    async def get_user_roles(self, db: AsyncSession, user_id: str):
        """获取用户的角色列表"""
        stmt = select(Role).join(UserRole).where(UserRole.user_id == user_id)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def authenticate_user(
            self,
            db: AsyncSession,
            username: str,
            password: str
    ):
        """用户认证"""
        user = await self.get_by_username(db, username)
        if not user or not verify_password(password, user.hashed_password):
            return None
        return user

    async def delete_user(self, db: AsyncSession, user_id: str):
        """删除用户及其相关联的角色和项目成员信息"""
        # 删除用户的角色关联
        stmt_delete_user_roles = delete(UserRole).where(UserRole.user_id == user_id)
        await db.execute(stmt_delete_user_roles)

        # 删除用户在项目中的成员信息
        stmt_delete_project_members = delete(ProjectMember).where(ProjectMember.user_id == user_id)
        await db.execute(stmt_delete_project_members)

        # 删除用户本身
        await self.delete(db, user_id)
        stmt_delete_user = User.__table__.delete().where(User.id == user_id)
        await db.execute(stmt_delete_user)
        # TODO 对话表conversation（是否保留？）
        await db.flush()
