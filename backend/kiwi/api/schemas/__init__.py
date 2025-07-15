import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, ConfigDict, Field
from typing import Optional, List


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None


# Contents of JWT token
class TokenPayload(BaseModel):
    sub: str | None = None


class NewPassword(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=40)


class RoleBase(BaseModel):
    code: int
    name: str
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr = Field(..., max_length=100)
    is_active: bool = True
    is_superuser: bool = False

    model_config = ConfigDict(from_attributes=True)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=40)


class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=40)
    email: EmailStr = Field(max_length=100)


# Properties to receive via API on update, all are optionals
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=100)  # type: ignore
    password: Optional[str] = Field(None, min_length=8, max_length=40)


class UserUpdateMe(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=50)
    email: EmailStr = Field(max_length=100)


class UpdatePassword(BaseModel):
    current_password: str = Field(min_length=8, max_length=40)
    new_password: str = Field(min_length=8, max_length=40)


class UserResponse(UserBase):
    id: uuid.UUID


class UsersResponse(BaseModel):
    data: list[UserResponse]
    count: int


class ProjectMemberBase(BaseModel):
    project_id: uuid.UUID
    user_id: uuid.UUID
    role_code: int

    model_config = ConfigDict(from_attributes=True)


class UserResponseWithRelations(UserResponse):
    roles: List[RoleBase] = []
    projects: List[ProjectMemberBase] = []

    model_config = ConfigDict(from_attributes=True)


class UserRoleAssignment(BaseModel):
    role_code_list: List[int] = Field(..., description="要分配给用户的角色ID列表")


class ProjectMemberAssignment(BaseModel):
    user_id: uuid.UUID
    role_code: int


# 基础项目信息
class ProjectBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


# 创建项目所需的字段
class ProjectCreate(ProjectBase):
    model_config = ConfigDict(from_attributes=True)


# 更新项目所需的字段
class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ProjectResponse(ProjectBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectsResponse(BaseModel):
    data: List[ProjectResponse]
    count: int
    skip: int
    limit: int

class ProjectDetail(BaseModel):
    project: ProjectResponse
    members: List[ProjectMemberBase] = []
    data_sources: List[str] = []
    datasets: List[str] = []


class ProjectMemberResponse(ProjectMemberBase):
    pass


class ProjectWithMembersResponse(ProjectResponse):
    members: List[ProjectMemberResponse] = []


# Generic message
class Message(BaseModel):
    message: str
