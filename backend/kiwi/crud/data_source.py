import json
from enum import Enum
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import aliased

from kiwi.core.database import BaseCRUD
from kiwi.core.query_engine import FederatedQueryEngine
from kiwi.models import DataSource, ProjectDataSource, User
from kiwi.core.encryption import encrypt_data, decrypt_data
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.schemas import DataSourceCreate, DataSourceUpdate


class DataSourceType(str, Enum):
    MYSQL = "mysql"
    POSTGRES = "postgres"
    S3 = "s3"
    SQLITE = "sqlite"
    LOCAL_FILE = "local_file"
    DUCK_DB = "duckdb"
    OTHERS = "others"


class DataSourceCRUD(BaseCRUD):
    def __init__(self):
        super().__init__(DataSource)

    async def list_data_sources_by_user(self, session: AsyncSession, user_id: str, skip: int, limit: int):
        """
        Asynchronously retrieves a list of data sources for a specified user.

        This function is designed to fetch a portion of the data sources belonging to a specific user,
        as defined by the skip and limit parameters, using an asynchronous mechanism to improve performance.

        Parameters:
        - session: Represents the current database session, essential for interacting with the database.
        - user_id: The unique identifier of the user, used to locate the user's data sources.
        - skip: The number of records to skip, used for pagination to avoid retrieving too much data at once.
        - limit: The maximum number of records to retrieve, used in conjunction with skip for pagination.

        Returns:
        A list of data sources belonging to the specified user, according to the skip and limit parameters.
        """
        return await self.get_multi(session, skip, limit, owner_id=user_id)

    async def list_data_sources_by_project(self, session: AsyncSession, project_id: str, skip: int, limit: int) -> List[
        DataSource]:
        """
        Asynchronously retrieves a list of data sources for a specified project.

        Parameters:
        - session: The current database session.
        - project_id: The unique identifier of the project.
        - skip: Number of records to skip for pagination.
        - limit: Maximum number of records to retrieve.

        Returns:
        A list of data sources associated with the specified project, including owner and creator names.
        """
        user_creator = aliased(User)

        stmt = (
            select(DataSource, User.username.label("owner_name"), user_creator.username.label("creator_name"))
            .join(ProjectDataSource, DataSource.id == ProjectDataSource.data_source_id)
            .join(User, DataSource.owner_id == User.id)
            .join(user_creator, DataSource.created_by == user_creator.id)
            .where(ProjectDataSource.project_id == project_id)
            .order_by(desc(DataSource.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await session.execute(stmt)

        # 组合结果，将 owner_name 和 creator_name 添加到 DataSource 对象中
        data_sources = []
        for row in result:
            data_source = row.DataSource
            if data_source is None:
                continue
            data_source.owner_name = row.owner_name
            data_source.creator_name = row.creator_name
            data_sources.append(data_source)

        return data_sources

    async def get_data_source(self, session: AsyncSession, data_source_id: str) -> Optional[DataSource]:

        return await self.get(session, data_source_id)

    async def get_data_source_by_name(self, db: AsyncSession, source_name: str) -> User:
        """根据用户名获取用户"""
        return await self.get_by_field(db, "name", source_name)

    async def create_data_source(self, session: AsyncSession, data_source_create: DataSourceCreate,
                                 user_id: str, type: DataSourceType) -> DataSource:

        connect_config = dict(data_source_create.connection_config)

        required_field_map = {
            DataSourceType.MYSQL: 'password',
            DataSourceType.POSTGRES: 'password',
            DataSourceType.S3: 'secret_key',
        }

        encrypted_field_map = {
            DataSourceType.MYSQL: 'encrypted_password',
            DataSourceType.POSTGRES: 'encrypted_password',
            DataSourceType.S3: 'encrypted_secret_key',
        }

        if type in required_field_map:
            field_name = required_field_map[type]
            encrypted_name = encrypted_field_map[type]

            value = connect_config.pop(field_name, None)
            if value is None:
                raise ValueError(f"Missing '{field_name}' field for database type: {type}")

            try:
                encrypted_value = encrypt_data(value)
                connect_config[encrypted_name] = encrypted_value
            except Exception as e:
                raise ValueError(f"Encryption failed for field '{field_name}': {e}")

        elif type != DataSourceType.OTHERS:
            raise ValueError(f"Unsupported data source type: {type}")

        data_source_dict = data_source_create.model_dump()
        data_source_dict.update({
            "connection_config": json.dumps(connect_config, ensure_ascii=False),
            "owner_id": user_id,
            "created_by": user_id
        })
        db_data_source = await self.create(session, data_source_dict)
        return db_data_source

    async def update_data_source(session: AsyncSession, db_data_source: DataSource,
                                 data_source_update: DataSourceUpdate) -> DataSource:
        for key, value in data_source_update.dict(exclude_unset=True).items():
            setattr(db_data_source, key, value)
        session.commit()
        session.refresh(db_data_source)
        return db_data_source

    async def delete_data_source(session: AsyncSession, data_source_id: str) -> None:
        pass

    async def test_connection(
            self,
            db: AsyncSession,
            data_source_id: Optional[str] = None,
            data_source_in: Optional[DataSourceCreate] = None
    ) -> Dict[str, Any]:
        connection_config = None
        source_type = None
        """测试数据源连接"""
        if data_source_id:
            data_source = await self.get_data_source(db, data_source_id)
            if not data_source:
                return {
                    'status': False,
                    'message': f"数据源不存在：{data_source_id}"
                }
            connection_config = json.loads(data_source.connection_config)
            source_type = data_source.type
        if data_source_in:
            connection_config = data_source_in.connection_config
            source_type = data_source_in.type
        if not connection_config or not source_type:
            return {
                'status': False,
                'message': "配置参数异常"
            }
        connection_config['password'] = decrypt_data(connection_config.pop('encrypted_password', None))
        print(connection_config, source_type)
        return FederatedQueryEngine().connection_test(connection_config, source_type)
