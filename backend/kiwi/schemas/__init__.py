import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, ConfigDict, Field
from typing import Optional, List, Dict, Any


class Message(BaseModel):
    message: str


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


# 数据源模型

class DataSourceBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., min_length=1, max_length=20)
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DataSourceBaseResponse(DataSourceBase):
    id: str = uuid.UUID
    owner_name: str = Field(..., min_length=3, max_length=50, alias="owner_id")
    creator_name: str = Field(..., min_length=3, max_length=50, alias="created_by")
    created_at: datetime = Field(..., alias="created_at")
    updated_at: datetime = Field(..., alias="created_at")

    model_config = ConfigDict(from_attributes=True)


class DataSourceResponse(DataSourceBaseResponse):
    connection_config: str


class DataSourcesResponse(BaseModel):
    data: List[DataSourceResponse]
    count: int


class DataSourceUpdate(BaseModel):
    description: Optional[str] = None
    connection_config: Dict[str, Any]


class DataSourceCreate(DataSourceBase):
    connection_config: Dict[str, Any]


class DataBaseConnectionWithoutPassword(BaseModel):
    host: str
    port: int
    database: str
    database_schema: str
    username: str

    model_config = ConfigDict(from_attributes=True)


class DataBaseConnection(DataBaseConnectionWithoutPassword):
    password: str


class DataBaseResponse(DataSourceBaseResponse):
    connection_config: DataBaseConnectionWithoutPassword


class DataBaseCreate(DataSourceBase):
    connection_config: DataBaseConnection


class DataBaseUpdate(BaseModel):
    description: Optional[str] = None
    connection_config: DataBaseConnection


class S3ConnectionWithoutSecretKey(BaseModel):
    endpoint: Optional[str] = Field(None, min_length=1, max_length=100)
    region: str = Field(..., min_length=1, max_length=100)
    bucket: str = Field(..., min_length=1, max_length=100)
    access_key: str = Field(..., min_length=1, max_length=100)


class S3Connection(S3ConnectionWithoutSecretKey):
    secret_key: str = Field(..., min_length=1, max_length=100)


class S3Create(DataSourceBase):
    connection_config: S3Connection


class S3Update(S3Connection):
    description: Optional[str] = None
    connection_config: DataBaseConnection


class S3Response(DataSourceBaseResponse):
    connection_config: S3ConnectionWithoutSecretKey

# 数据集
# class TableMapping(BaseModel):
#     source_alias: str
#     source_table: str
#     target_name: str
#
# class Relationship(BaseModel):
#     left_table: str
#     left_column: str
#     right_table: str
#     right_column: str
#     type: str
#
# class DatasetConfig(BaseModel):
#     name: str
#     tables: List[Dict[str, Any]]  # 表信息列表
#     table_mappings: List[TableMapping]  # 表映射关系
#     relationships: List[Relationship]  # 表关系定义
#
# class DatasetResponse(BaseModel):
#     success: bool
#     data: Optional[Dict[str, Any]] = None
#     error: Optional[str] = None
