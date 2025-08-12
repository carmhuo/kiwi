import re
import time

import duckdb
import json
import asyncio
from enum import Enum

from fastapi import HTTPException
from typing import Dict, List, Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.core.engine.connection_pool import DuckDBConnectionPool
from kiwi.core.engine.data_source_attacher import DataSourceAttacher
from kiwi.core.engine.query_executor import DuckDBQueryExecutor
from kiwi.schemas import QueryResult
from kiwi.core.config import logger

DUCKDB_EXTENSIONS = ['httpfs', 'sqlite', 'postgres', 'parquet', 'mysql', 'excel']

DUCKDB_SYSTEM_DATABASES = ["memory", "system", "temp"]


class DuckDBExtensionsType(str, Enum):
    HTTPFS = "httpfs"
    S3 = "S3"
    SQLITE = "sqlite"
    POSTGRES = "postgres"
    POSTGRESQL = "postgresql"
    PARQUET = "parquet"
    MYSQL = "mysql"
    EXCEL = "excel"


def _format_index(index) -> str:
    return (
        f"Name: {index['name']}, Unique: {index['is_unique']},"
        f" Columns: {str(index['expressions'])}"
    )


def sanitize_schema(schema: str) -> str:
    """Sanitize a schema name to only contain letters, digits, and underscores."""
    if not re.match(r"^[a-zA-Z0-9_]+$", schema):
        raise ValueError(
            f"Schema name '{schema}' contains invalid characters. "
            "Schema names must contain only letters, digits, and underscores."
        )
    return schema


# --- 联邦查询服务 ---

class FederationQueryEngine:
    _max_string_length: int = 300

    DIALECT: str = "DuckDB"

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.connection_pool = DuckDBConnectionPool()
        self.query_executor = DuckDBQueryExecutor(self.connection_pool, self.config)
        self._initialized: bool = False

    async def initialize(self):
        """初始化连接池"""
        start_time = time.time()
        await logger.ainfo("Starting DuckDB connection pool initialization...")
        await self.connection_pool.initialize(self.config)
        self._initialized = True
        total_time = time.time() - start_time
        await logger.ainfo(f"DuckDB connection pool initialized successfully [Total: {total_time:.3f}s]")

    async def shutdown(self):
        """关闭连接池"""
        """关闭服务"""
        if not self._initialized:
            return

        await self.connection_pool.shutdown()
        self._initialized = False
        await logger.ainfo("Connection pool shutdown completed")

    def is_initialized(self) -> bool:
        """检查连接池是否已初始化"""
        return self._initialized

    async def fetch_one(self, sql: str, parameters=None, timeout=30):
        """执行异步查询"""
        if not self._initialized:
            raise HTTPException(
                status_code=503,
                detail="Service not initialized"
            )
        try:
            async with self.connection_pool.get_connection(reuse=False) as conn:
                query_result = await self.query_executor.arun(conn, sql, parameters, timeout)
                return query_result.fetchone()
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Database query failed"
            ) from e

    async def execute_query(
            self,
            db: AsyncSession,
            project_id: str,
            sql: str,
            **kwargs
    ) -> QueryResult:
        """执行查询"""
        if not self._initialized:
            raise HTTPException(
                status_code=503,
                detail="Service not initialized"
            )

        return await self.query_executor.execute_query(db, project_id, sql, **kwargs)

    @DeprecationWarning
    async def execute_query_with_dataset(
            self,
            db: AsyncSession,
            project_id: str,
            sql: str,
            dataset_id: str,
            **kwargs
    ) -> QueryResult:
        """执行数据集查询"""
        return await self.query_executor.execute_query(db, project_id, sql, dataset_id=dataset_id, **kwargs)

    async def connection_activity_test(self, connection_config: Dict[str, Any], source_type: str) -> Dict[str, Any]:
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
            async with self.connection_pool.get_connection(reuse=False) as conn:

                await DataSourceAttacher.attach_single_source(conn, ext_type, connection_config, database_alias)
                try:
                    query = await self.query_executor.arun(
                        conn,
                        f"SELECT * FROM duckdb_databases() WHERE database_name = ?",
                        [database_alias]
                    )
                    result = query.fetchone()
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

    async def list_tables(
            self,
            db: AsyncSession,
            project_id: Optional[str] = None,
            dataset_id: Optional[str] = None,
    ):
        """列出项目或数据集可用的表

            Args:
                db: 数据库会话
                project_id: 项目ID
                dataset_id: 数据集ID

            Returns:
                表信息列表，每个表包含database_name和table_name
        """
        return await self.query_executor.list_tables(db, project_id, dataset_id)

    async def get_table_info(
            self,
            db: AsyncSession,
            project_id: Optional[str] = None,
            dataset_id: Optional[str] = None,
            full_table_names: Optional[List[str]] = None,
            get_col_comments: bool = False,
            indexes_in_table_info: bool = False,
            sample_rows_in_table_info: int = 3
    ):
        """Get information about specified tables.

                Follows best practices as specified in: Rajkumar et al, 2022
                (https://arxiv.org/abs/2204.00498)

                If `sample_rows_in_table_info`, the specified number of sample rows will be
                appended to each table description. This can increase performance as
                demonstrated in the paper.
        """
        try:
            async with self.connection_pool.get_connection(
                    project_id=project_id,
                    dataset_id=dataset_id,
                    reuse=True
            ) as conn:

                await self.query_executor.attach_data_sources(
                    conn, db, project_id, dataset_id
                )

                # 构建SQL查询，如果table_names存在则添加过滤条件
                base_query = """
                       SELECT database_name, schema_name, table_name, column_name, comment, is_nullable, data_type 
                       FROM duckdb_columns()
                       WHERE database_name != 'system'
                       {filter_condition}
                       ORDER BY database_name, schema_name, table_name
                   """
                filters = ""
                params = []
                if full_table_names:
                    # 构造表名过滤条件
                    filter_conditions = []
                    for full_table_name in full_table_names:
                        if '.' not in full_table_name:
                            raise ValueError(f"Invalid table name format: {full_table_name}")
                        db_name, table_name = full_table_name.split('.', 1)
                        filter_conditions.append(f"(database_name = ? AND table_name = ?)")
                        params.extend([db_name, table_name])
                    if filter_conditions:
                        filters = " AND (" + " OR ".join(filter_conditions) + ")"

                full_query = base_query.format(filter_condition=filters)

                query = await self.query_executor.arun(conn, full_query, params)
                result = query.fetchall()
                if not result:
                    return ""

                # 构建表信息字符串
                table_info_strings = []
                tables_data = {}  # 存储每个表的列信息，key为full_table_name，value为列信息列表

                # 按表分组处理结果，获取表与列信息
                for row in result:
                    database_name, schema_name, table_name, column_name, comment, is_nullable, data_type = row
                    full_table_name = f"{database_name}.{table_name}"

                    # 初始化该表的列信息列表（如果尚未存在）
                    if full_table_name not in tables_data:
                        tables_data[full_table_name] = []

                    # 构建当前列的信息
                    column_info = f"  {column_name} {data_type}"
                    if is_nullable:
                        column_info += " NULL"
                    else:
                        column_info += " NOT NULL"

                    if comment:
                        column_info += f" -- {comment}"

                        # 添加到该表的列信息列表中
                    tables_data[full_table_name].append(column_info)

                # 为每个表生成信息（包括列、索引、样本行）
                for full_table_name, columns_info in tables_data.items():
                    # 添加表的列信息
                    table_info = "\n".join(columns_info)
                    has_extra_info = (
                            indexes_in_table_info or sample_rows_in_table_info
                    )
                    if has_extra_info:
                        table_info += "\n\n/*"
                    if indexes_in_table_info:
                        table_indexes = await self.get_table_index(conn, full_table_name)
                        table_info += f"\n{table_indexes}\n"
                    if sample_rows_in_table_info > 0:
                        table_samples = await self.get_sample_rows(conn, full_table_name, sample_rows_in_table_info)
                        table_info += f"\n{table_samples}\n"
                    if has_extra_info:
                        table_info += "*/"
                    table_info_strings.append(table_info)

                table_info_strings.sort()
                final_str = "\n\n".join(table_info_strings)
                return final_str
        except ValueError as ve:
            return f"ValueError: {ve}"
        except Exception as e:
            return f"Error: {e}"

    async def get_table_index(self, conn, full_table_name: str) -> str:
        try:
            database_name, table_name = full_table_name.split(".")
            query = await self.query_executor.arun(
                conn,
                f"select index_name, is_unique, expressions, sql from duckdb_indexes() where database_name=? and table_name=?",
                [database_name, table_name]
            )
            query_result = query.fetchall()
            indexes_formatted = "\n".join(map(_format_index, query_result))
            return f"Table Indexes:\n{indexes_formatted}"

        except Exception as e:
            return f"获取索引信息时出错: {str(e)}"

    async def get_sample_rows(self, conn, full_table_name: str, sample_rows_in_table_info: int) -> str:
        columns_str = ""
        sample_rows_str = ""
        try:
            # 获取样本行数据
            sample_query = f"SELECT * FROM {full_table_name} USING SAMPLE {sample_rows_in_table_info};"
            sample_result = await self.query_executor.arun(conn, sample_query)

            if sample_result:
                # 获取列名
                column_names = [desc[0] for desc in sample_result.description]
                # 格式化样本行
                columns_str = "\t".join(column_names)
                # shorten values in the sample rows
                sample_rows = list(
                    map(lambda ls: [str(i)[:100] for i in ls], sample_result.fetchall())
                )

                # save the sample rows in string format
                sample_rows_str = "\n".join(["\t".join(row) for row in sample_rows])

        except Exception as e:
            sample_rows_str = ""

        return (
            f"{sample_rows_in_table_info} rows from {full_table_name} table:"
            f"{columns_str}\n"
            f"{sample_rows_str}"
        )

    async def get_memory_usage(
            self,
            db: AsyncSession,
            project_id: Optional[str] = None,
            dataset_id: Optional[str] = None,
            **kwargs
    ) -> List[Dict[str, Any]]:
        """
        获取当前DuckDB连接的内存使用情况

        Args:
            db: 数据库会话
            project_id: 项目ID
            dataset_id: 数据集ID
            kwargs: 包含装饰器注入的连接和源信息

        Returns:
            包含内存使用情况的字典列表
        """
        try:
            conn = kwargs.get('_conn')
            if not conn:
                raise ValueError("Connection not provided by decorator")

            result = conn.execute(
                "SELECT tag, memory_usage_bytes, temporary_storage_bytes FROM duckdb_memory();").fetchall()
            memory_info = []
            for row in result:
                memory_info.append({
                    "tag": row[0],
                    "memory_usage_bytes": row[1],
                    "temporary_storage_bytes": row[2]
                })
            return memory_info
        except Exception as e:
            await logger.awarning(f"Error getting memory usage: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error getting memory usage: {str(e)}"
            )


_engine_instance = None


async def init_engine(config):
    """初始化全局实例（由 main.py 调用）"""
    global _engine_instance
    _engine_instance = FederationQueryEngine(config)
    await _engine_instance.initialize()


def get_engine() -> FederationQueryEngine:
    """获取已初始化的实例"""
    if _engine_instance is None and not _engine_instance.is_initialized():
        raise RuntimeError("Engine not initialized")
    return _engine_instance

def get_connection_pool():
    engine = get_engine()
    return engine.connection_pool

async def shutdown_engine():
    """关闭实例"""
    global _engine_instance
    if _engine_instance is not None:
        await _engine_instance.shutdown()
        _engine_instance = None
