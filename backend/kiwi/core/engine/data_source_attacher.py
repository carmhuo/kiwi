import asyncio
from enum import Enum
from typing import Dict, Set, Optional, Any, Tuple, List
import duckdb
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kiwi.models import ProjectDataSource, Dataset, DatasetProjectSource, DataSource
from kiwi.core.services.datasource_utils import decrypt_connection_config, DataSourceType
from kiwi.core.config import logger


class DuckDBExtensionsType(str, Enum):
    HTTPFS = "httpfs"
    S3 = "S3"
    SQLITE = "sqlite"
    POSTGRES = "postgres"
    POSTGRESQL = "postgresql"
    PARQUET = "parquet"
    MYSQL = "mysql"
    EXCEL = "excel"


class DataSourceAttacher:
    """专门负责数据源附加操作的类"""
    DATA_SOURCE_TTL = 3600

    @staticmethod
    async def attach_project_sources(
            conn: duckdb.DuckDBPyConnection,
            db: AsyncSession,
            project_id: str
    ) -> Set[str]:
        """附加项目所有激活的数据源"""
        sources_used = set()

        result = await db.execute(
            select(ProjectDataSource)
            .options(selectinload(ProjectDataSource.data_source))
            .where(ProjectDataSource.project_id == project_id)
            .where(ProjectDataSource.is_active == True)
        )
        project_data_sources = result.scalars().all()

        for pds in project_data_sources:
            try:
                await DataSourceAttacher._attach_single_source(
                    conn,
                    pds.data_source,
                    pds.alias
                )
                sources_used.add(pds.alias)
            except Exception as e:
                await logger.awarning(
                    f"Failed to attach project data source {pds.alias}: {str(e)}"
                )

        return sources_used

    @staticmethod
    async def attach_dataset_sources(
            conn: duckdb.DuckDBPyConnection,
            db: AsyncSession,
            project_id: str,
            dataset_id: str
    ) -> Set[str]:
        """附加数据集相关的数据源"""
        sources_used = set()

        dataset = await db.execute(
            select(Dataset)
            .options(
                selectinload(Dataset.data_sources)
                .selectinload(DatasetProjectSource.data_source)
            )
            .where(Dataset.id == dataset_id)
            .where(Dataset.project_id == project_id)
        )
        dataset = dataset.scalars().first()

        if not dataset:
            raise ValueError(f"Dataset {dataset_id} not found in project {project_id}")

        dataset_config = dataset.configuration
        required_aliases = {
            table["source_alias"]
            for table in dataset_config.get("tables", [])
        }

        for ds_rel in dataset.data_sources:
            if ds_rel.data_source.alias in required_aliases:
                try:
                    await DataSourceAttacher._attach_single_source(
                        conn,
                        ds_rel.data_source
                    )
                    sources_used.add(ds_rel.data_source.alias)
                except Exception as e:
                    await logger.awarning(
                        f"Failed to attach dataset data source {ds_rel.data_source.alias}: {str(e)}"
                    )

        return sources_used

    @staticmethod
    async def _attach_single_source(
            conn: duckdb.DuckDBPyConnection,
            data_source: DataSource,
            alias: Optional[str] = None
    ):
        """附加单个数据源"""
        source_type = data_source.type
        config = await decrypt_connection_config(
            DataSourceType(source_type),
            data_source.connection_config
        )

        stmt = DataSourceAttacher._generate_attach_statement(
            DuckDBExtensionsType(source_type),
            config,
            alias or data_source.alias
        )
        await asyncio.wait_for(
            asyncio.to_thread(conn.execute, stmt),
            timeout=30
        )

    @staticmethod
    async def attach_single_source(
            conn: duckdb.DuckDBPyConnection,
            source_type: DuckDBExtensionsType,
            connection_config: Dict[str, Any],
            database_alias: str
    ):
        """异步附加单个数据源到DuckDB连接

        参数:
            conn: DuckDB连接对象，用于执行附加操作
            source_type: 数据源类型字符串，指定要附加的数据源类型
            connection_config: 连接配置字典，包含连接到数据源所需的信息
            database_alias: 数据库别名，用于在DuckDB中标识附加的数据源

        返回值:
            无返回值
        """
        stmt = DataSourceAttacher._generate_attach_statement(
            source_type,
            connection_config,
            database_alias
        )
        await asyncio.wait_for(
            asyncio.to_thread(conn.execute, stmt),
            timeout=30
        )

    @staticmethod
    def _generate_attach_statement(
            source_type: DuckDBExtensionsType,
            config: Dict[str, Any],
            alias: str
    ) -> str:
        """生成数据源ATTACH语句"""
        """生成数据源ATTACH语句"""
        # if not config['password']:
        #     config['password'] = decrypt_data(config.pop('encrypted_password', None))

        if source_type == DuckDBExtensionsType.MYSQL:
            return (
                f"ATTACH 'host={config['host']} port={config['port']} "
                f"database={config['database']} user={config['username']} "
                f"password={config['password']}' AS {alias} (TYPE mysql, READ_ONLY)"
            )
        elif source_type == DuckDBExtensionsType.POSTGRES:
            return (
                f"ATTACH 'dbname={config['database']} host={config['host']} "
                f"port={config['port']} user={config['username']} "
                f"password={config['password']}' AS {alias} (TYPE postgres, SCHEMA '{config['database_schema']}', READ_ONLY)"
            )
        elif source_type == DuckDBExtensionsType.S3:
            # S3需要特殊处理，不是ATTACH而是设置配置
            secret_name = f"secret_{alias}"
            return (f"DROP SECRET IF EXISTS {secret_name}; "
                    f"""CREATE OR REPLACE SECRET {secret_name} (
                                TYPE s3,
                                PROVIDER config,
                                ENDPOINT '{config.get('endpoint', '')}',
                                KEY_ID '{config['access_key']}',
                                SECRET '{config['secret_key']}',
                                REGION '{config.get('region', 'us-east-1')}',
                                URL_STYLE '{config.get('url_style', 'path')}'
                            );""")
        elif source_type == DuckDBExtensionsType.SQLITE:
            path = config.get('path')
            if not path:
                raise ValueError("SQLite connection requires 'path' configuration")
            return f"ATTACH '{config['path']}' AS {alias} (TYPE sqlite, READ_ONLY);"
        else:
            raise NotImplemented

    @staticmethod
    async def attach_dataset_tables(
            conn: duckdb.DuckDBPyConnection,
            db: AsyncSession,
            project_id: str,
            dataset_id: str,
            dataset_config: dict
    ) -> Tuple[Set[str], Set[str]]:
        """
        设置数据集所需的表和视图

        Returns:
            Tuple[loaded_sources, loaded_tables]: 已加载的数据源和表
        """
        loaded_sources = set()
        loaded_tables = set()

        # 1. 提取需要加载的表信息
        tables_to_load = {}
        table_mappings = {}

        for table in dataset_config.get("tables", []):
            source_alias = table["source_alias"]
            source_table = table["table_name"]
            columns = table.get("columns")

            if source_alias not in tables_to_load:
                tables_to_load[source_alias] = {}

            tables_to_load[source_alias][source_table] = columns
            table_mappings[source_table] = table.get("target_name", source_table)

        # 2. 获取数据集关联的数据源
        data_sources_map = {}
        for ds_rel in dataset_config.get("data_sources", []):
            if ds_rel.data_source.alias in tables_to_load:
                data_sources_map[ds_rel.data_source.alias] = ds_rel.data_source

        # 3. 加载数据源和创建视图
        for source_alias, tables in tables_to_load.items():
            if source_alias not in data_sources_map:
                raise ValueError(f"Data source {source_alias} not associated with dataset {dataset_id}")

            data_source = data_sources_map[source_alias]

            # 附加数据源
            try:
                await DataSourceAttacher._attach_single_source(conn, data_source, source_alias)
                loaded_sources.add(source_alias)
            except Exception as e:
                await logger.awarning(
                    f"Failed to attach data source {source_alias}: {str(e)}"
                )
                continue

            # 为每个表创建视图
            for source_table, columns in tables.items():
                target_name = table_mappings.get(source_table, source_table)
                view_stmt = DataSourceAttacher._generate_table_view_statement(
                    source_alias, source_table, target_name, columns
                )
                try:
                    conn.execute(view_stmt)
                    loaded_tables.add(target_name)
                except Exception as e:
                    await logger.awarning(
                        f"Failed to create view {target_name}: {str(e)}"
                    )

        # 4. 添加关系约束（可选）
        for rel in dataset_config.get("relationships", []):
            try:
                conn.execute(
                    f"ALTER VIEW {rel['left_table']} ADD PRIMARY KEY ({rel['left_column']});"
                )
                conn.execute(
                    f"ALTER VIEW {rel['right_table']} ADD PRIMARY KEY ({rel['right_column']});"
                )
            except Exception as e:
                await logger.awarning(f"Failed to add relationship constraint: {str(e)}")

        return loaded_sources, loaded_tables

    @staticmethod
    def _generate_table_view_statement(
            self,
            source_alias: str,
            source_table: str,
            target_name: str,
            columns: List[str]
    ) -> str:
        """生成表视图创建语句"""
        columns_str = ", ".join(columns) if columns else "*"
        return (
            f"CREATE OR REPLACE VIEW {target_name} AS "
            f"SELECT {columns_str} FROM {source_alias}.{source_table}"
        )
