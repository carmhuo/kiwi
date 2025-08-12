from functools import partial
from typing import Annotated, List

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.core.security.auth_utils import ALGORITHM
from kiwi.core.cache import CacheManager, Cache
from kiwi.core.config import settings
from kiwi.core.database import get_db_session
from kiwi.crud.project import ProjectCRUD
from kiwi.crud.user import UserCRUD
from kiwi.models import User, Role

# 定义数据库会话依赖
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)

TokenDep = Annotated[str, Depends(reusable_oauth2)]


async def get_current_user(session: SessionDep, token: TokenDep) -> User:
    """
    获取当前认证用户对象

    参数:
        session: 数据库会话依赖
        token: OAuth2认证令牌

    返回:
        User: 认证通过的用户对象

    异常:
        HTTPException: 
            - 401: 凭证验证失败
            - 404: 用户不存在
            - 400: 用户被禁用
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except (InvalidTokenError, ValidationError):
        raise credentials_exception

    user = await UserCRUD().get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


# 定义认证用户依赖
CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_active_superuser(current_user: CurrentUser) -> User:
    """
    获取当前具有超级管理员权限的用户对象

    Args:
        current_user: 当前认证用户对象，通过依赖注入自动获取

    Returns:
        User: 具有超级管理员权限的用户对象

    Exp:
        HTTPException: 
            - 403: 用户没有足够的权限（非超级管理员）
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


async def get_user_roles(db: AsyncSession, user_id: str) -> List[int]:
    """
    获取用户的全部角色信息

    :param db: 数据库会话
    :param user_id: 用户唯一标识
    :return: 角色列表 [0,1,2...]
    """
    # 查询用户拥有的所有角色
    roles = await UserCRUD().get_user_roles(db, user_id)
    return [role.code for role in roles]


async def verify_project_member(db: SessionDep,
                                current_user: CurrentUser,
                                project_id: str) -> bool:
    # 系统管理员拥有所有权限
    if current_user.is_superuser:
        return True

    # 检查项目成员
    member = await ProjectCRUD().get_project_member(db, project_id, current_user.id)
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户不是项目成员"
        )

    # 普通用户只能访问对话
    if member.role_code == 99:  # 普通用户
        return True

    # 其他角色有完全访问权限
    return True


# 定义项目成员验证依赖
ProjectMember = Annotated[bool, Depends(verify_project_member)]


# 依赖项：获取缓存实例
async def get_cache() -> Cache:
    return await CacheManager.get_cache()

CacheDep = Annotated[Cache, Depends(get_cache)]
