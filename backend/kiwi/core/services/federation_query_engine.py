import time
from datetime import datetime

import duckdb
import json
import asyncio
from enum import Enum
from fastapi import HTTPException
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Any, AsyncGenerator, Sequence
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from kiwi.schemas import QueryFormatType, QueryResult
from kiwi.models import ProjectDataSource, Dataset, DatasetProjectSource, DataSource
from kiwi.core.services.datasource_utils import decrypt_connection_config, DataSourceType
from kiwi.core.config import logger
from kiwi.api.deps import (
    CurrentUser,
    SessionDep,
)

# --- 配置 ---
DUCKDB_CONFIG = {
    "max_connections": 50,
    "min_connections": 10,
    "timeout": 10,
    "query_timeout": 60,
    "enable_httpfs": True,
    "arrow_batch_size": 65536,  # Arrow批次大小
}

DUCKDB_EXTENSIONS = ['httpfs', 'sqlite', 'postgres', 'parquet', 'mysql', 'excel']


class DuckDBExtensionsType(str, Enum):
    HTTPFS = "httpfs"
    S3 = "S3"
    SQLITE = "sqlite"
    POSTGRES = "postgres"
    POSTGRESQL = "postgresql"
    PARQUET = "parquet"
    MYSQL = "mysql"
    EXCEL = "excel"


# --- 联邦查询服务 ---
class FederationQueryEngine:
    _connection_queue: asyncio.Queue[duckdb.DuckDBPyConnection] = None
    _monitor_task: asyncio.Task = None
    _initialized: bool = False  # 初始化状态标识

    @classmethod
    async def initialize(cls):
        """初始化连接池"""
        start_time = time.time()
        await logger.ainfo("Starting DuckDB connection pool initialization...")
        try:
            if cls._initialized:
                await logger.awarning("Connection pool already initialized")
                return

            cls._connection_queue = asyncio.Queue(maxsize=DUCKDB_CONFIG["max_connections"])

            for _ in range(DUCKDB_CONFIG["min_connections"]):
                conn = cls._create_duckdb_connection()
                await cls._connection_queue.put(conn)

            cls._monitor_task = asyncio.create_task(cls._monitor_connection_pool())

            cls._initialized = True
            total_time = time.time() - start_time
            await logger.ainfo(f"DuckDB connection pool initialized successfully [Total: {total_time:.3f}s]")
        except Exception as e:
            await logger.aerror(f"Initialization failed: {str(e)}")
            raise

    @classmethod
    async def shutdown(cls):
        """关闭连接池"""
        if not cls._initialized:
            return
        if cls._monitor_task:
            try:
                cls._monitor_task.cancel()
                await cls._monitor_task
            except asyncio.CancelledError:
                pass
            finally:
                _monitor_task = None

            while not cls._connection_queue.empty():
                try:
                    conn = await cls._connection_queue.get()
                    conn.close()
                except Exception:
                    pass
                finally:
                    _connection_queue = None

        cls._initialized = False

        await logger.ainfo("Connection pool shutdown completed")

    @classmethod
    def is_initialized(cls) -> bool:
        """检查连接池是否已初始化"""
        return cls._initialized

    @staticmethod
    def _create_duckdb_connection() -> duckdb.DuckDBPyConnection:
        """创建DuckDB连接并加载扩展支持"""
        conn = duckdb.connect(':memory:')
        if DUCKDB_CONFIG.get("enable_httpfs", False):
            conn.execute("INSTALL httpfs; LOAD httpfs;")
        conn.execute("INSTALL sqlite; LOAD sqlite;")
        return conn

    @classmethod
    async def _monitor_connection_pool(cls):
        """监控连接池状态"""
        while True:
            await asyncio.sleep(30)
            current_size = cls._connection_queue.qsize()

            # 动态调整连接池
            if current_size < DUCKDB_CONFIG["min_connections"]:
                needed = min(
                    DUCKDB_CONFIG["min_connections"] - current_size,
                    DUCKDB_CONFIG["max_connections"] - current_size
                )
                for _ in range(needed):
                    await cls._connection_queue.put(cls._create_duckdb_connection())

    @classmethod
    @asynccontextmanager
    async def get_duckdb_connection(cls) -> AsyncGenerator[duckdb.DuckDBPyConnection, None]:
        """获取DuckDB连接"""
        if not cls._initialized:
            raise HTTPException(
                status_code=503,
                detail="Connection pool not initialized"
            )
        try:
            conn = await asyncio.wait_for(
                cls._connection_queue.get(),
                timeout=DUCKDB_CONFIG["timeout"]
            )
            if conn is None:
                raise HTTPException(
                    status_code=503,
                    detail="Invalid database connection"
                )
            yield conn
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=503,
                detail="Database connection timeout"
            )
        finally:
            if conn:
                try:
                    # 清除未提交的连接，避免污染
                    # if conn.execute("SELECT * FROM duckdb_transactions();").fetchone()
                    conn.execute("ROLLBACK")
                    await cls._connection_queue.put(conn)
                except:
                    conn.close()

    @staticmethod
    def generate_attach_statement(ext_type: DuckDBExtensionsType, config: Dict[str, Any], alias: str) -> str:
        """生成数据源ATTACH语句"""
        # if not config['password']:
        #     config['password'] = decrypt_data(config.pop('encrypted_password', None))

        if ext_type == DuckDBExtensionsType.MYSQL:
            return (
                f"ATTACH 'host={config['host']} port={config['port']} "
                f"database={config['database']} user={config['username']} "
                f"password={config['password']}' AS {alias} (TYPE mysql, READ_ONLY)"
            )
        elif ext_type == DuckDBExtensionsType.POSTGRES:
            return (
                f"ATTACH 'dbname={config['database']} host={config['host']} "
                f"port={config['port']} user={config['username']} "
                f"password={config['password']}' AS {alias} (TYPE postgres, SCHEMA '{config['database_schema']}', READ_ONLY)"
            )
        elif ext_type == DuckDBExtensionsType.S3:
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
        elif ext_type == DuckDBExtensionsType.SQLITE:
            path = config.get('path')
            if not path:
                raise ValueError("SQLite connection requires 'path' configuration")
            return f"ATTACH '{config['path']}' AS {alias} (TYPE sqlite, READ_ONLY);"
        else:
            raise NotImplemented

    @staticmethod
    def generate_table_view_statement(
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

    @classmethod
    async def execute_query(
            cls,
            db: SessionDep,
            project_id: str,
            sql: str,
            result_format: QueryFormatType = QueryFormatType.JSON,
            preview: bool = False
    ) -> QueryResult:
        """
        执行联邦查询，从项目关联的数据源中获取数据并执行 SQL 查询。

        :param db: 数据库会话对象，用于访问项目数据源配置。
        :param project_id: 项目 ID，用于筛选该项目下激活的数据源。
        :param sql: 要执行的 SQL 查询语句。
        :param result_format: 查询结果的格式类型，默认为 JSON 格式（当前未使用）。
        :param preview: 是否为预览模式（当前未使用）。
        :return: 查询结果对象，包含列名、行数据、执行时间等信息。
        """
        # 获取项目数据源
        result = await db.execute(
            select(ProjectDataSource)
            .options(selectinload(ProjectDataSource.data_source))
            .where(ProjectDataSource.project_id == project_id)
            .where(ProjectDataSource.is_active == True)
        )
        project_data_sources = result.scalars().all()

        sources_used = set()
        async with cls.get_duckdb_connection() as conn:
            start_time = asyncio.get_event_loop().time()

            # 附加数据源
            for pds in project_data_sources:
                try:
                    data_source: DataSource = pds.data_source
                    source_type = data_source.type
                    config = await decrypt_connection_config(DataSourceType(source_type), data_source.connection_config)
                    stmt = cls.generate_attach_statement(DuckDBExtensionsType(source_type), config, pds.alias)
                    conn.execute(stmt)
                    sources_used.add(pds.alias)
                except Exception as e:
                    await logger.awarning(f"Failed to attach data source {pds.alias}: {str(e)}")

            connection_time = asyncio.get_event_loop().time() - start_time

            # 执行查询（带超时）
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(conn.execute, sql),
                    timeout=DUCKDB_CONFIG["query_timeout"]
                )
            except asyncio.TimeoutError:
                logger.warning(f"Query timeout: {sql[:100]}...")
                raise HTTPException(
                    status_code=504,
                    detail="Query execution timeout"
                )

            # 处理结果
            columns = [desc[0] for desc in result.description] if result.description else []
            rows = [dict(zip(columns, row)) for row in result.fetchall()] if columns else []

            return QueryResult(
                columns=columns,
                rows=rows,
                execution_time=asyncio.get_event_loop().time() - start_time - connection_time,
                connection_time=connection_time,
                sources_used=list(sources_used)
            )

    @classmethod
    async def execute_query_with_dataset(
            cls,
            db: SessionDep,
            project_id: str,
            sql: str,
            dataset_id: str,
            result_format: QueryFormatType = QueryFormatType.JSON,
            preview: bool = False
    ) -> QueryResult:
        """
        执行联邦查询，只加载数据集使用的数据源和表。

        参数:
            db (AsyncSession): 数据库会话对象，用于执行数据库查询。
            project_id (str): 项目 ID，用于限定数据集所属项目。
            sql (str): 要执行的 SQL 查询语句。
            dataset_id (str): 数据集 ID，用于确定需要加载的数据源和表。
            result_format (QueryFormatType): 查询结果的格式，默认为 JSON 格式。
            preview (bool): 是否为预览模式。若为 True，则自动添加 LIMIT 100 子句。

        返回:
            QueryResult: 查询结果对象，包含列信息、行数据、执行时间等元信息。
        """
        start_time = datetime.now()

        # 获取数据集及其关联的数据源
        dataset: Dataset = await db.execute(
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

        # 解析数据集配置
        try:
            dataset_config = json.loads(dataset.configuration)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid dataset configuration for dataset {dataset_id}")

        # 提取需要加载的表信息
        tables_to_load = {}
        table_mappings = {}
        for table in dataset_config.get("tables", []):
            source_alias = table["source_alias"]
            source_table = table["table_name"]
            columns = table.get("columns")

            if source_alias not in tables_to_load:
                tables_to_load[source_alias] = {}

            tables_to_load[source_alias][source_table] = columns

        # 创建表映射关系
        for mapping in dataset_config.get("table_mappings", []):
            source_table = mapping["source_table"]
            target_name = mapping["target_name"]
            table_mappings[source_table] = target_name

        # 获取数据集关联的数据源
        data_sources_map = {}
        for ds_rel in dataset.data_sources:
            if ds_rel.data_source.alias in tables_to_load:
                data_sources_map[ds_rel.data_source.alias] = ds_rel.data_source

        async with cls.get_duckdb_connection() as conn:
            loaded_sources = []
            loaded_tables = []

            # 只加载数据集使用的数据源
            for source_alias, tables in tables_to_load.items():
                if source_alias not in data_sources_map:
                    raise ValueError(f"Data source {source_alias} not associated with dataset {dataset_id}")

                pds = data_sources_map[source_alias]

                # 附加数据源
                attach_stmt = cls.generate_attach_statement(pds.connection_config, pds.alias)
                conn.execute(attach_stmt)
                loaded_sources.append(source_alias)

                # 为每个表创建视图
                for source_table, columns in tables.items():
                    target_name = table_mappings.get(source_table, source_table)
                    view_stmt = cls.generate_table_view_statement(
                        source_alias, source_table, target_name, columns
                    )
                    conn.execute(view_stmt)
                    loaded_tables.append(target_name)

            # 添加关系约束（帮助查询优化器）
            for rel in dataset_config.get("relationships", []):
                try:
                    conn.execute(f"ALTER VIEW {rel['left_table']} ADD PRIMARY KEY ({rel['left_column']});")
                    conn.execute(f"ALTER VIEW {rel['right_table']} ADD PRIMARY KEY ({rel['right_column']});")
                except Exception as e:
                    # 关系约束失败不影响查询
                    logger.warning(f"添加关系约束失败， {str(e)}")

            # 如果是预览模式，添加LIMIT子句
            final_sql = sql
            if preview:
                if "LIMIT" not in sql.upper():
                    final_sql = f"{sql.rstrip(';')} LIMIT 100;"

            # 执行查询
            try:
                result = conn.execute(final_sql)
            except duckdb.Error as e:
                raise ValueError(f"DuckDB query error: {str(e)}")

            # 处理结果
            columns = [desc[0] for desc in result.description] if result.description else []
            rows = []

            # 分批次获取结果，避免内存溢出
            batch_size = 1000
            while True:
                batch = result.fetchmany(batch_size)
                if not batch:
                    break
                rows.extend([dict(zip(columns, row)) for row in batch])

            execution_time = (datetime.now() - start_time).total_seconds()

            return QueryResult(
                columns=columns,
                rows=rows,
                execution_time=execution_time,
                loaded_sources=loaded_sources,
                loaded_tables=loaded_tables,
                generated_sql=final_sql if preview else None
            )

    @staticmethod
    def generate_view_statements(dataset_config: dict, loaded_tables: List[str]) -> List[str]:
        """生成数据集视图语句，基于实际加载的表"""
        statements = []

        # 创建表映射关系
        table_mappings = {}
        for mapping in dataset_config.get("table_mappings", []):
            source_table = mapping["source_table"]
            target_name = mapping["target_name"]
            table_mappings[source_table] = target_name

        # 创建视图
        for table in dataset_config.get("tables", []):
            source_alias = table["source_alias"]
            table_name = table["table_name"]
            target_name = table_mappings.get(table_name, table_name)

            # 检查表是否已加载
            temp_table_name = f"{source_alias}_{table_name}"
            if temp_table_name not in loaded_tables:
                continue

            columns = ", ".join(table.get("columns", ["*"]))
            statements.append(
                f"CREATE OR REPLACE VIEW {target_name} AS "
                f"SELECT {columns} FROM {temp_table_name}"
            )

        # 添加关系约束（可选）
        for rel in dataset_config.get("relationships", []):
            statements.append(
                f"ALTER VIEW {rel['left_table']} ADD PRIMARY KEY ({rel['left_column']});"
            )
            statements.append(
                f"ALTER VIEW {rel['right_table']} ADD PRIMARY KEY ({rel['right_column']});"
            )

        return statements

    @classmethod
    async def connection_activity_test(cls, connection_config: Dict[str, Any], source_type: str) -> Dict[str, Any]:
        """
            测试与DuckDB扩展的连接。

            参数:
            - connection_config: 连接配置信息。
            - source_type: 数据源类型。

            返回:
                {
                'status': bool,
                'message': str,
                'error_type': Optional[str]  # 错误类型字段
                }
            """
        try:
            ext_type = DuckDBExtensionsType(source_type)
        except  Exception as e:
            await logger.aerror(f"不支持的DuckDB扩展类型: {e}")
            return {
                'status': False,
                'message': "不支持的DuckDB扩展类型",
                'error_type': 'INVALID_TYPE'
            }

        database_alias = f"__{source_type}_db_test__"

        try:
            async with cls.get_duckdb_connection() as conn:
                try:
                    statements = cls.generate_attach_statement(ext_type, connection_config, database_alias)
                    conn.execute(statements)
                    result = conn.execute(
                        f"SELECT * FROM duckdb_databases() WHERE database_name = ?",
                        [database_alias]
                    ).fetchone()
                    # Clean up
                    conn.execute(f"DETACH {database_alias}")
                    return {
                        'status': bool(result),
                        'message': f"{source_type} connection test successful" if result else "Failed to attach database",
                        'error_type': None
                    }
                except duckdb.BinderException as e:
                    return {
                        'status': False,
                        'message': f"Database attachment failed: {str(e)}",
                        'error_type': 'BIND_ERROR'
                    }
                except duckdb.ConnectionException as e:
                    return {
                        'status': False,
                        'message': f"Connection failed: {str(e)}",
                        'error_type': 'CONNECTION_ERROR'
                    }
                except duckdb.Error as e:
                    await logger.aerror(f"Connection test failed:: {str(e)}",
                                        extra={'type': source_type, 'connection_config': connection_config})
                    return {
                        'status': False,
                        'message': f"DuckDB error: {str(e)}",
                        'error_type': 'DUCKDB_ERROR'
                    }
        except asyncio.TimeoutError:
            return {
                'status': False,
                'message': "Connection pool timeout",
                'error_type': 'POOL_TIMEOUT'
            }
        except Exception as e:
            await logger.aerror(
                f"Connection test failed for {source_type}",
                extra={'config': connection_config}
            )
            return {
                'status': False,
                'message': str(e),
                'error_type': 'UNKNOWN_ERROR'
            }
