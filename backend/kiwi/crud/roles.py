from enum import Enum
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from kiwi.models import User, Role, UserRole
from kiwi.core.database import BaseCRUD

class UserRoleType(int, Enum):
    SYSTEM_ADMIN = 0
    PROJECT_ADMIN  = 1
    DATASOURCE_ADMIN = 2
    DATA_ANALYST = 3
    BIZ_USER = 99

class UserRoles(BaseCRUD):
    def __init__(self):
        super().__init__(UserRole)

    async def get_user_roles(self, db: AsyncSession, user_id: str):
        """
        获取用户的全部角色信息

        :param db: 数据库会话
        :param user_id: 用户唯一标识
        :return: 角色列表 [0,1, ...]
        """
        # 查询用户拥有的所有角色
        roles = self.get(db, user_id)

        return [role.role_code for role in roles]

    async def has_data_source_admin(self, db: AsyncSession, user_id: str):
        role_codes = self.get_user_roles(db, user_id)
        return 2 in role_codes

    @staticmethod
    async def has_data_source_creation(self, db: AsyncSession, user_id: str):
        """
        判断用户是否有创建数据源的权限

        :param db: 数据库会话
        :param user_id: 用户唯一标识
        :return: 是否拥有数据源管理员权限
        """
        stmt = select(UserRole.role_code).where(UserRole.user_id == user_id)
        result = await session.execute(stmt)
        role_codes = [row[0] for row in result.all()]
        return role_codes

    @staticmethod
    async def has_data_source_read(db: AsyncSession, user_id: str) -> bool:
        """
        判断用户是否有创建数据源的权限

        :param db: 数据库会话
        :param user_id: 用户唯一标识
        :return: 是否拥有数据源管理员权限
        """
        try:
            stmt = select(UserRole.role_code).where(
                UserRole.user_id == user_id,
                UserRole.role_code.in_((UserRoleType.SYSTEM_ADMIN, UserRoleType.DATASOURCE_ADMIN))
            )
            result = await db.execute(stmt)
            role_codes = [row[0] for row in result.all()]
            return len(role_codes) > 0
        except Exception as e:
            # 可根据项目实际情况替换为 logging.error 或其他日志方式
            print(f"数据库查询异常: {e}")
            return False

