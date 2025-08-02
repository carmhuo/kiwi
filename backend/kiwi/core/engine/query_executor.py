import asyncio
import re
from enum import Enum
from typing import Dict, List, Set, Optional, Any, Tuple

import duckdb
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from kiwi.schemas import QueryFormatType, QueryResult
from kiwi.models import ProjectDataSource, Dataset, DatasetProjectSource
from kiwi.core.config import logger
from kiwi.core.engine.data_source_attacher import DataSourceAttacher


class DuckDBQueryExecutor:
    """DuckDB 查询执行器"""

    def __init__(self, connection_pool, config: Dict[str, Any]):
        self.connection_pool = connection_pool
        self.config = config
        self.query_timeout = config["query_timeout"] or 60

    async def arun(
            self,
            conn: duckdb.DuckDBPyConnection,
            query,
            parameters=None,
            timeout=None
    ) -> duckdb.DuckDBPyConnection:
        """异步执行数据库查询操作

        Args:
            conn (duckdb.DuckDBPyConnection): DuckDB数据库连接对象
            query: 要执行的SQL查询语句
            parameters: SQL查询参数，默认为None
            timeout: 查询超时等待时间

        Returns:
            duckdb.DuckDBPyConnection: 执行查询后的数据库连接对象

        Raises:
            HTTPException: 当查询执行超时或发生数据库错误时抛出HTTP异常
        """
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(conn.execute, query, parameters),
                timeout=timeout or self.query_timeout
            )
            return result
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=504,
                detail="Query execution timeout"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Database execution error: {str(e)}"
            )

    async def _execute_sql(
            self,
            conn: duckdb.DuckDBPyConnection,
            sources_used: Set[str],
            sql: str,
            parameters=None,
            max_string_length: int = 500,
            preview: bool = False,
            connection_time: Optional[float] = None,
            query_timeout: Optional[int] = None
    ) -> QueryResult:
        """
        执行SQL查询的核心方法

        Args:
            conn: DuckDB连接对象
            sources_used: 已使用的数据源集合
            sql: 要执行的SQL语句
            parameters: optionally using prepared statements with parameters set
            max_string_length: 字符串最大截断长度
            preview: 是否为预览模式
            connection_time: 建立连接时间，包括attach datasource
            query_timeout: 查询超时时间(秒)

        Returns:
            QueryResult: 包含查询结果的对象

        Raises:
            HTTPException: 当查询执行失败时抛出
        """
        # 准备执行参数
        start_time = asyncio.get_event_loop().time()
        final_sql = self._prepare_sql(sql, preview)
        timeout = query_timeout or self.query_timeout

        try:
            # 执行查询（切换到线程池执行同步操作）
            result = await asyncio.wait_for(
                asyncio.to_thread(conn.execute, final_sql, parameters),
                timeout=timeout
            )

            # 处理结果
            execution_time = asyncio.get_event_loop().time() - start_time
            return self._process_query_result(
                result=result,
                sources_used=sources_used,
                connection_time=connection_time,
                execution_time=execution_time,
                max_string_length=max_string_length,
                generated_sql=final_sql if preview else None
            )

        except asyncio.TimeoutError:
            await logger.aerror(
                f"Query timeout after {timeout}s: {self._truncate_sql_for_log(final_sql)}",
                extra={"sources": sources_used}
            )
            raise HTTPException(
                status_code=504,
                detail=f"Query exceeded timeout of {timeout} seconds"
            )

        except duckdb.CatalogException as e:
            await logger.aerror(
                f"Catalog error: {str(e)} in query: {self._truncate_sql_for_log(final_sql)}",
                exc_info=True
            )
            raise HTTPException(
                status_code=400,
                detail=f"Metadata error: {str(e)}"
            )

        except duckdb.SyntaxException as e:
            await logger.aerror(
                f"Syntax error: {str(e)} in query: {self._truncate_sql_for_log(final_sql)}",
                exc_info=True
            )
            raise HTTPException(
                status_code=400,
                detail=f"SQL syntax error: {str(e)}"
            )

        except duckdb.PermissionException as e:
            await logger.aerror(
                f"Permission denied: {str(e)} in query: {self._truncate_sql_for_log(final_sql)}",
                exc_info=True
            )
            raise HTTPException(
                status_code=403,
                detail=f"Access denied: {str(e)}"
            )

        except Exception as e:
            await logger.aerror(
                f"Unexpected query error: {str(e)} in query: {self._truncate_sql_for_log(final_sql)}",
                exc_info=True
            )
            raise HTTPException(
                status_code=500,
                detail=f"Query execution failed: {str(e)}"
            )

    def _prepare_sql(self, sql: str, preview: bool) -> str:
        """预处理SQL语句"""
        sql = sql.strip()

        # 为预览模式添加LIMIT子句
        if preview and not self._has_limit_clause(sql):
            if sql.endswith(';'):
                sql = f"{sql[:-1]} LIMIT 100;"
            else:
                sql = f"{sql} LIMIT 100"

        return sql

    @staticmethod
    def _has_limit_clause(sql: str) -> bool:
        """检查SQL是否已包含LIMIT子句"""
        # 简单实现：不解析SQL，只检查关键字
        return bool(re.search(r'\bLIMIT\s+\d+\s*$', sql, re.IGNORECASE))

    def _process_query_result(
            self,
            result: duckdb.DuckDBPyConnection,
            sources_used: Set[str],
            connection_time: float,
            execution_time: float,
            max_string_length: int,
            generated_sql: Optional[str] = None
    ) -> QueryResult:
        """处理查询结果并构建返回对象"""
        # 获取列信息
        columns = [desc[0] for desc in result.description] if result.description else []

        # 分批获取结果（避免内存溢出）
        batch_size = 2000  # 可根据实际情况调整
        rows = []

        while True:
            batch = result.fetchmany(batch_size)
            if not batch:
                break

            # 处理每行数据
            for row in batch:
                processed_row = tuple(
                    self._truncate_value(value, length=max_string_length)
                    for value in row
                )
                rows.append(processed_row)

        return QueryResult(
            columns=columns,
            rows=rows,
            connection_time=connection_time,
            execution_time=execution_time,
            sources_used=list(sources_used),
            generated_sql=generated_sql
        )

    async def execute_query(
            self,
            db: AsyncSession,
            project_id: str,
            sql: str,
            parameters=None,
            dataset_id: Optional[str] = False,
            preview: bool = False,
            max_string_length: int = 500,
            reuse_connection: bool = True,
            force_reattach: bool = False
    ) -> QueryResult:
        """执行联邦查询

        Args:
            db (AsyncSession): 数据库会话对象，用于执行数据库查询。
            project_id (str): 项目 ID，用于限定数据集所属项目。
            sql (str): 要执行的 SQL 查询语句。
            parameters: optionally using prepared statements with parameters set
            dataset_id (str): 数据集 ID，用于确定需要加载的数据源和表。
            preview (bool): 是否为预览模式。若为 True，则自动添加 LIMIT 100 子句。
            max_string_length: 查询结果中字符串字段的最大长度，超出部分将被截断。
            reuse_connection:
            force_reattach:

        Returns:
            QueryResult: 查询结果对象，包含列信息、行数据、执行时间等元信息。
        """
        start_time = asyncio.get_event_loop().time()
        async with self.connection_pool.get_connection(
                project_id=project_id,
                dataset_id=dataset_id,
                reuse=reuse_connection
        ) as conn:
            sources_used = await self.attach_data_sources(
                conn, db, project_id, dataset_id, force_reattach
            )

            connection_time = asyncio.get_event_loop().time() - start_time
            # 执行查询
            return await self._execute_sql(
                conn,
                sources_used,
                sql,
                parameters=parameters,
                max_string_length=max_string_length,
                preview=preview,
                connection_time=connection_time
            )

    async def attach_data_sources(
            self,
            conn: duckdb.DuckDBPyConnection,
            db: AsyncSession,
            project_id: str,
            dataset_id: Optional[str] = None,
            force_reattach: bool = False
    ) -> Set[str]:
        """附加数据源到连接"""

        ctx = self.connection_pool.get_connection_context(conn)

        need_attach = (
                force_reattach or
                not ctx.get("sources_attached") or
                ctx.get("project_id") != project_id or
                (asyncio.get_event_loop().time() - ctx.get("last_attach_time",
                                                           0)) > DataSourceAttacher.DATA_SOURCE_TTL
        )

        if not need_attach:
            return ctx["sources_attached"]

        sources_used = set()

        if dataset_id and project_id:
            # 处理数据集数据源
            dataset_config = await self._get_dataset_config(db, project_id, dataset_id)
            sources_used, tables_used = await DataSourceAttacher.attach_dataset_tables(conn, db, project_id,
                                                                                       dataset_id,
                                                                                       dataset_config)

            self.connection_pool.update_connection_context(conn, {
                "project_id": project_id,
                "dataset_id": dataset_id,
                "sources_attached": sources_used,
                "tables_attached": tables_used,
                "last_attach_time": asyncio.get_event_loop().time()
            })
        elif project_id:
            # 处理项目数据源
            sources_used = await DataSourceAttacher.attach_project_sources(conn, db, project_id)
            self.connection_pool.update_connection_context(conn, {
                "project_id": project_id,
                "sources_attached": sources_used,
                "last_attach_time": asyncio.get_event_loop().time()
            })

        return sources_used

    @staticmethod
    async def _get_dataset_config(
            db: AsyncSession,
            project_id: str,
            dataset_id: str
    ) -> dict:
        """获取数据集配置"""
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
            raise HTTPException(
                status_code=404,
                detail=f"Dataset {dataset_id} not found in project {project_id}"
            )

        return dataset.configuration

    @staticmethod
    def _truncate_value(content: Any, *, length: int, suffix: str = "...") -> str:
        """截断字符串"""
        if not isinstance(content, str) or length <= 0:
            return content

        if len(content) <= length:
            return content

        return content[: length - len(suffix)].rsplit(" ", 1)[0] + suffix

    @staticmethod
    def _truncate_sql_for_log(sql: str, max_length: int = 200) -> str:
        """截断SQL用于日志记录"""
        if len(sql) <= max_length:
            return sql
        return sql[:max_length] + f"...[truncated, total {len(sql)} chars]"

    async def list_tables(
            self,
            db: AsyncSession,
            project_id: Optional[str] = None,
            dataset_id: Optional[str] = None,
            include_schema: bool = True,
            filter_system_tables: bool = True,
            **kwargs
    ) -> List[Dict[str, str]]:
        """
        列出所有可用的表（包括跨数据源的联邦表）

        Args:
            db: 数据库会话
            project_id: 项目ID（可选）
            dataset_id: 数据集ID（可选）
            include_schema: 是否包含schema信息
            filter_system_tables: 是否过滤系统表
            kwargs: 其他参数

        Returns:
            表信息列表，每个表包含database_name, schema_name, table_name等信息
        """
        if not project_id and not dataset_id:
            raise ValueError("project_id or dataset_id must be provided.")

        # 构建基础查询
        base_query = """
        SELECT 
            database_name, 
            schema_name, 
            table_name,
            column_count,
            estimated_size,
            comment
        FROM duckdb_tables()
        {filter_condition}
        ORDER BY database_name, schema_name, table_name
    """

        # 添加过滤条件
        filter_conditions = []
        params = []

        if filter_system_tables:
            filter_conditions.append("database_name NOT IN ('system', 'temp')")

        if dataset_id:
            # 如果是数据集查询，只返回数据集配置的表
            try:
                dataset_config = await self._get_dataset_config(db, project_id, dataset_id)
            except Exception as e:
                await logger.aerror(
                    f"Failed to get dataset config: {str(e)}",
                    exc_info=True
                )
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to get dataset config: {str(e)}"
                )
            dataset_tables = {
                f"{table['source_alias']}.{table['table_name']}"
                for table in dataset_config.get("tables", [])
            }
            if dataset_tables:
                conditions = []
                for full_table in dataset_tables:
                    db_name, tbl_name = full_table.split('.', 1)
                    conditions.append("(database_name = ? AND table_name = ?)")
                    params.extend([db_name, tbl_name])
                filter_conditions.append(f"({' OR '.join(conditions)})")

        filter_condition = f"WHERE {' AND '.join(filter_conditions)}" if filter_conditions else ""

        final_sql = base_query.format(filter_condition=filter_condition)

        try:
            query_result = await self.execute_query(db, project_id, final_sql, parameters=params)

            tables = [f"{row[0]}.{row[2]}" if include_schema else row[2] for row in query_result.rows]

            return ", ".join(tables) if tables else "No tables found"
        except Exception as e:
            await logger.aerror(
                f"Failed to list tables: {str(e)}",
                exc_info=True
            )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to list tables: {str(e)}"
            )
