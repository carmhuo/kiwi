from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, TIMESTAMP, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.ext.declarative import declarative_base
import uuid

Base = declarative_base()


class User(Base):
    __tablename__ = "user"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
                index=True, unique=True, nullable=False)
    username = Column(String(50), unique=True, nullable=False)
    hashed_password = Column(String(128), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    user_roles = relationship("UserRole", back_populates="user")
    project_members = relationship("ProjectMember", back_populates="user")


class Role(Base):
    __tablename__ = "role"

    code = Column(Integer, primary_key=True, unique=True, nullable=False)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)


class UserRole(Base):
    __tablename__ = "user_role"

    user_id = Column(String(36), ForeignKey("user.id"), primary_key=True)
    role_code = Column(Integer, ForeignKey("role.code"), primary_key=True)

    user = relationship("User", back_populates="user_roles")
    role = relationship("Role")


class Project(Base):
    __tablename__ = "project"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
                index=True, unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    owner_id = Column(String(36), ForeignKey("user.id"))
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    owner = relationship("User")
    members = relationship("ProjectMember", back_populates="project")
    data_sources = relationship("DataSource", back_populates="project")
    datasets = relationship("Dataset", back_populates="project")
    agents = relationship("Agent", back_populates="project")
    conversations = relationship("Conversation", back_populates="project")


class ProjectMember(Base):
    __tablename__ = "project_member"

    project_id = Column(String(36), ForeignKey("project.id"), primary_key=True)
    user_id = Column(String(36), ForeignKey("user.id"), primary_key=True)
    role_code = Column(Integer, ForeignKey("role.code"))

    project = relationship("Project", back_populates="members")
    user = relationship("User", back_populates="project_members")
    role = relationship("Role")


class DataSource(Base):
    __tablename__ = "data_source"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
                index=True, unique=True, nullable=False)
    project_id = Column(String(36), ForeignKey("project.id"))
    name = Column(String(100), nullable=False)
    type = Column(String(20), nullable=False)
    connection_config = Column(Text, nullable=False)
    created_by = Column(String(36), ForeignKey("user.id"))
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    project = relationship("Project", back_populates="data_sources")
    creator = relationship("User")
    datasets = relationship("DatasetDataSource", back_populates="data_source")


class Dataset(Base):
    __tablename__ = "dataset"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
                index=True, unique=True, nullable=False)
    project_id = Column(String(36), ForeignKey("project.id"))
    name = Column(String(100), nullable=False)
    configuration = Column(Text, nullable=False)
    created_by = Column(String(36), ForeignKey("user.id"))
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    project = relationship("Project", back_populates="datasets")
    creator = relationship("User")
    data_sources = relationship("DatasetDataSource", back_populates="dataset")


class DatasetDataSource(Base):
    __tablename__ = "dataset_data_source"

    dataset_id = Column(String(36), ForeignKey("dataset.id"), primary_key=True)
    data_source_id = Column(String(36), ForeignKey("data_source.id"), primary_key=True)
    alias = Column(String(100), nullable=False)

    dataset = relationship("Dataset", back_populates="data_sources")
    data_source = relationship("DataSource", back_populates="datasets")


class Agent(Base):
    __tablename__ = "agent"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
                index=True, unique=True, nullable=False)
    project_id = Column(String(36), ForeignKey("project.id"))
    name = Column(String(100), nullable=False)
    type = Column(String(20), nullable=False)
    config = Column(Text, nullable=False)
    created_by = Column(String(36), ForeignKey("user.id"))
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    project = relationship("Project", back_populates="agents")
    creator = relationship("User")
    versions = relationship("AgentVersion", back_populates="agent")


class AgentVersion(Base):
    __tablename__ = "agent_version"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
                index=True, unique=True, nullable=False)
    agent_id = Column(String(36), ForeignKey("agent.id"))
    version = Column(String(20), nullable=False)
    config = Column(Text, nullable=False)
    checksum = Column(String(64), nullable=False)
    created_by = Column(String(36), ForeignKey("user.id"))
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    is_current = Column(Boolean, default=False)

    agent = relationship("Agent", back_populates="versions")
    creator = relationship("User")
    metrics = relationship("AgentMetric", back_populates="version")


class AgentMetric(Base):
    __tablename__ = "agent_metric"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
                index=True, unique=True, nullable=False)
    agent_version_id = Column(String(36), ForeignKey("agent_version.id"))
    sql_gen_latency = Column(Float, nullable=False)
    query_success_rate = Column(Float, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    version = relationship("AgentVersion", back_populates="metrics")


class Conversation(Base):
    __tablename__ = "conversation"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
                index=True, unique=True, nullable=False)
    project_id = Column(String(36), ForeignKey("project.id"))
    user_id = Column(String(36), ForeignKey("user.id"))
    title = Column(String(200), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    project = relationship("Project", back_populates="conversations")
    user = relationship("User")
    messages = relationship("Message", back_populates="conversation")


class Message(Base):
    __tablename__ = "message"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
                index=True, unique=True, nullable=False)
    conversation_id = Column(String(36), ForeignKey("conversation.id"))
    content = Column(Text, nullable=False)
    role = Column(String(10), nullable=False)  # user/assistant
    sql_query = Column(Text)
    report_data = Column(Text)  # JSON格式
    feedback_type = Column(Integer)  # 1=正确, 0=错误, 2=部分正确, 3=建议改进
    feedback_text = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)

    conversation = relationship("Conversation", back_populates="messages")
