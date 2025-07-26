import re
import uuid
from enum import Enum
from datetime import datetime

from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator, ValidationError
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


class UserResponseDetail(UserBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    role_codes: List[int] = []


class ProjectMemberBase(BaseModel):
    project_id: str
    user_id: str
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


class ProjectMemberResponse(ProjectMemberBase):
    pass


class ProjectWithMembersResponse(ProjectResponse):
    members: List[ProjectMemberResponse] = []


class ProjectDatasourceResponse(BaseModel):
    project_id: str
    data_source_id: str
    alias: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


# 数据源模型

class DataSourceBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., min_length=1, max_length=20)
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DataSourceBaseResponse(DataSourceBase):
    id: uuid.UUID
    owner_name: str = Field(..., min_length=3, max_length=50, alias="owner_id")
    creator_name: str = Field(..., min_length=3, max_length=50, alias="created_by")
    created_at: datetime = Field(..., alias="created_at")
    updated_at: datetime = Field(..., alias="created_at")

    model_config = ConfigDict(from_attributes=True)


class DataSourceResponse(DataSourceBaseResponse):
    connection_config: Dict[str, Any]


class DataSourcesResponse(BaseModel):
    data: List[DataSourceResponse]
    count: int


class DataSourceUpdate(BaseModel):
    description: Optional[str] = None
    connection_config: Dict[str, Any]


class DataSourceCreate(DataSourceBase):
    connection_config: Dict[str, Any]


class DataSourceConnection(DataSourceBase):
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
class DatasetBase(BaseModel):
    id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    project_id: str

    model_config = ConfigDict(from_attributes=True)


class DatasetCreate(DatasetBase):
    data_source_aliases: List[str] = Field(..., min_items=1)
    configuration: Dict[str, Any] = Field(..., description="including tables/relationships")


class DatasetResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    data_source_aliases: List[str]
    configuration: str
    created_by: str
    creator_name: str = Field(..., min_length=3, max_length=50)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DatasetsResponse(BaseModel):
    data: List[DatasetResponse]
    count: int


class ProjectDetail(BaseModel):
    project: ProjectResponse
    members: List[ProjectMemberBase] = []
    data_sources: List[ProjectDatasourceResponse] = []
    datasets: List[DatasetBase] = []


# Agent
class AgentBase(BaseModel):
    name: str = Field(..., max_length=100, example="销售分析Agent")
    type: str = Field(..., example="TEXT2SQL")
    config: Dict[str, Any] = Field(..., example={"model": "gpt-4", "temperature": 0.7})


class AgentCreate(AgentBase):
    project_id: str = Field(..., example="proj_123")


class AgentUpdate(AgentBase):
    is_active: Optional[bool] = None


class AgentResponse(AgentBase):
    id: str
    project_id: str
    created_by: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentsResponse(BaseModel):
    data: List[AgentResponse]
    count: int


class AgentVersionBase(BaseModel):
    version: str = Field(..., examples=["v1.2.0"])

    @field_validator('version')
    @classmethod
    def validate_version(cls, v: str):
        if not re.match(r"^v\d+\.\d+\.\d+$", v):
            raise ValueError("版本号格式应为vX.Y.Z")
        return v


class AgentVersionCreate(AgentVersionBase):
    config: Dict[str, Any]


class AgentVersionRollback(AgentVersionBase):
    agent_id: Optional[str] = None


class AgentVersionResponse(AgentVersionCreate):
    id: str
    agent_id: str
    created_at: datetime
    is_current: bool

    model_config = ConfigDict(from_attributes=True)


class AgentVersionsResponse(BaseModel):
    data: List[AgentVersionResponse]
    count: int


class AgentMetricCreate(BaseModel):
    sql_gen_latency: float
    query_success_rate: float = Field(..., ge=0, le=1)


class AgentMetricResponse(AgentMetricCreate):
    id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# 对话

class MessageCreate(BaseModel):
    content: str = Field(..., description="用户消息内容")
    role: Optional[str] = Field(default="user", description="角色，可选值：user,assistant")
    conversation_id: Optional[str] = Field(None, description="对话ID，新建对话时为空")


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    sql_query: Optional[str] = None
    report_data: Optional[Dict[str, Any]] = None
    created_at: datetime


class ConversationCreate(BaseModel):
    project_id: str
    title: str = Field(..., max_length=200, example="销售分析")


class ConversationResponse(BaseModel):
    id: str
    project_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationsResponse(BaseModel):
    data: List[ConversationResponse]
    count: int


class ConversationDetailResponse(ConversationResponse):
    messages: List[MessageResponse] = []


class FeedbackCreate(BaseModel):
    message_id: str
    feedback_type: int = Field(..., ge=0, le=3, description="0=错误,1=正确,2=部分正确,3=建议改进")
    feedback_text: Optional[str] = None


# 联邦sql查询
class QueryFormatType(str, Enum):
    ARROW = "arrow"
    JSON = "json"


class QueryRequest(BaseModel):
    project_id: str
    sql: str
    dataset_id: Optional[str] = None
    format: QueryFormatType = QueryFormatType.JSON  # 返回格式: arrow或json

    @field_validator('sql')
    def validate_sql(cls, v):
        if not v or not isinstance(v, str):
            raise ValueError('sql must be a non-empty string')
        # 基本的SQL关键字检查，防止危险操作
        from kiwi.core.security.sql_validator import SQLValidator
        SQLValidator.validate(v)
        return v


class QueryResult(BaseModel):
    columns: List[str]
    rows: List[Dict[str, Any]]
    execution_time: float
    connection_time: float
    sources_used: List[str]  # 使用的数据源列表


class ArrowResult(BaseModel):
    a_schema: dict
    batches: list
    num_rows: int
    execution_time: float
