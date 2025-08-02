import asyncio
import duckdb
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict, Any, Optional
from fastapi import HTTPException


class DuckDBConnectionPool:
    """DuckDB 连接池管理类"""

    def __init__(self):
        self._connection_queue = None
        self._connection_contexts = {}
        self._monitor_task = None
        self._initialized = False
        self._config = None
        self._init_lock = asyncio.Lock()  # 添加初始化锁

    async def initialize(self, config: Dict[str, Any]):
        """初始化连接池"""
        async with self._init_lock:
            if self._initialized:
                return

            self._config = config
            self._connection_queue = asyncio.Queue(maxsize=config["max_connections"])

            # 创建初始连接
            for _ in range(config["min_connections"]):
                conn = self._create_connection()
                await self._connection_queue.put(conn)

            # 启动监控任务
            self._monitor_task = asyncio.create_task(self._monitor_pool())
            self._initialized = True

    async def shutdown(self):
        """关闭连接池"""
        if not self._initialized:
            return

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        while not self._connection_queue.empty():
            conn = await self._connection_queue.get()
            conn.close()

        self._connection_queue = None
        self._connection_contexts = {}
        self._initialized = False

    def is_initialized(self) -> bool:
        """检查连接池是否已初始化"""
        return self._initialized

    def get_pool_stats(self) -> Dict[str, Any]:
        """获取连接池状态"""
        if not self._initialized:
            return {
                "initialized": False,
                "current_connections": 0,
                "max_connections": 0,
                "min_connections": 0
            }

        return {
            "initialized": True,
            "current_connections": self._connection_queue.qsize(),
            "max_connections": self._config["max_connections"],
            "min_connections": self._config["min_connections"]
        }

    @asynccontextmanager
    async def get_connection(
            self,
            project_id: Optional[str] = None,
            dataset_id: Optional[str] = None,
            reuse: bool = False
    ) -> AsyncGenerator[duckdb.DuckDBPyConnection, None]:
        """获取数据库连接"""
        if not self._initialized:
            raise HTTPException(
                status_code=503,
                detail="Connection pool not initialized"
            )

        conn = None
        try:
            # 尝试重用已有连接
            if reuse and (project_id or dataset_id):
                conn = await self._find_reusable_connection(project_id, dataset_id)

            # 获取新连接
            if not conn:
                conn = await self._get_new_connection(project_id, dataset_id)

            yield conn
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=503,
                detail="Database connection timeout"
            )
        finally:
            if conn:
                await self._release_connection(conn, reuse)

    async def _find_reusable_connection(
            self,
            project_id: Optional[str],
            dataset_id: Optional[str]
    ) -> Optional[duckdb.DuckDBPyConnection]:
        """查找可重用的连接"""
        for conn_id, ctx in self._connection_contexts.items():
            if ((project_id and ctx.get("project_id") == project_id) or
                    (dataset_id and ctx.get("dataset_id") == dataset_id)):
                # 从队列中查找匹配的连接
                for conn in list(self._connection_queue._queue):
                    if id(conn) == conn_id:
                        await self._connection_queue.get()  # 从队列移除
                        return conn
        return None

    async def _get_new_connection(
            self,
            project_id: Optional[str],
            dataset_id: Optional[str]
    ) -> duckdb.DuckDBPyConnection:
        """获取新连接"""
        conn = await asyncio.wait_for(
            self._connection_queue.get(),
            timeout=self._config["connection_timeout"]
        )

        if conn is None:
            raise HTTPException(
                status_code=503,
                detail="Invalid database connection"
            )

        # 初始化连接上下文
        self._connection_contexts[id(conn)] = {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "sources_attached": set()
        }

        return conn

    async def _release_connection(
            self,
            conn: duckdb.DuckDBPyConnection,
            reuse: bool
    ):
        """释放连接"""
        try:
            conn.execute("ROLLBACK")
            if not reuse:
                # 不重用则清除上下文
                self._connection_contexts.pop(id(conn), None)
                await self._connection_queue.put(conn)
        except Exception:
            conn.close()
            self._connection_contexts.pop(id(conn), None)

    async def _monitor_pool(self):
        """监控连接池状态"""
        while True:
            await asyncio.sleep(30)
            current_size = self._connection_queue.qsize()

            # 动态调整连接池大小
            if current_size < self._config["min_connections"]:
                needed = min(
                    self._config["min_connections"] - current_size,
                    self._config["max_connections"] - current_size
                )
                for _ in range(needed):
                    await self._connection_queue.put(self._create_connection())

    def _create_connection(self) -> duckdb.DuckDBPyConnection:
        """创建新的DuckDB连接"""
        conn = duckdb.connect(":memory:")

        # 加载扩展
        if self._config.get("enable_httpfs", False):
            conn.execute("INSTALL httpfs; LOAD httpfs;")

        conn.execute("INSTALL sqlite; LOAD sqlite;")
        return conn

    def get_connection_context(
            self,
            conn: duckdb.DuckDBPyConnection
    ) -> Dict[str, Any]:
        """获取连接上下文"""
        return self._connection_contexts.get(id(conn), {})

    def update_connection_context(
            self,
            conn: duckdb.DuckDBPyConnection,
            updates: Dict[str, Any]
    ):
        """更新连接上下文"""
        if id(conn) in self._connection_contexts:
            self._connection_contexts[id(conn)].update(updates)