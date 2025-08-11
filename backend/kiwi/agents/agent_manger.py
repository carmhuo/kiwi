import asyncio
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional, Callable

from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.schemas import AgentType
from kiwi.core.config import logger


class AgentInfo:
    """存储Agent实例及其元数据"""

    def __init__(
            self,
            agent: CompiledStateGraph,
            agent_type: AgentType
    ):
        self.agent = agent
        self.agent_type = agent_type
        self.last_active = datetime.now()
        self.created_at = datetime.now()

    def update_last_active(self):
        """更新最后活跃时间"""
        self.last_active = datetime.now()

    def is_expired(self, timeout: timedelta) -> bool:
        """检查Agent是否已过期"""
        return datetime.now() - self.last_active > timeout

    @property
    def info(self) -> Dict:
        """获取Agent信息"""
        return {
            "type": self.agent_type.value,
            "created_at": self.created_at,
            "last_active": self.last_active
        }


class AgentManager:
    """Agent管理器，用于创建、获取和销毁Agent实例"""

    def __init__(
            self,
            store: Optional[BaseStore] = None,
            active_time: int = 3600
    ):
        self._agents: Dict[str, AgentInfo] = {}
        self._store = store
        self.active_time = timedelta(seconds=active_time)
        self._cleanup_task: Optional[asyncio.Task] = None
        self._cleanup_interval = 60  # 默认每60秒检查一次过期agent
        # 添加异步锁保护共享资源
        # 读写锁分离
        self._read_semaphore = asyncio.Semaphore(20)  # 允许多个读操作并发
        self._write_lock = asyncio.Lock()  # 写操作互斥

    async def get_agent(
            self,
            conversation_id: str,
            db: AsyncSession,
            project_id: str,
            agent_type: AgentType = AgentType.TEXT_TO_SQL,
            agent_factory: Optional[Callable] = None
    ) -> CompiledStateGraph:
        """根据对话ID获取Agent，如果不存在则创建新的Agent

        Args:
            conversation_id: 对话ID
            db: 数据库会话
            project_id: 项目ID
            agent_type: Agent类型
            agent_factory: 可选的工厂函数，如果未提供则使用默认的

        Returns:
            CompiledStateGraph: Agent instance
        """
        async with self._write_lock:
            if conversation_id not in self._agents:
                if agent_factory is None:
                    raise ValueError("agent_factory must be provided")
                agent = await agent_factory(db, project_id)
                self._agents[conversation_id] = AgentInfo(agent, agent_type)
            else:
                # 更新最后活跃时间
                self._agents[conversation_id].update_last_active()

            return self._agents[conversation_id].agent

    async def destroy_agent(self, conversation_id: str) -> bool:
        """销毁指定对话ID的Agent

        Args:
            conversation_id: 对话ID

        Returns:
            bool: 是否成功销毁
        """
        async with self._write_lock:
            if conversation_id in self._agents:
                # 如果需要执行清理操作，可以在这里添加
                del self._agents[conversation_id]
                return True
            return False

    async def destroy_all_agents(self) -> int:
        """销毁所有Agent

        Returns:
            int: 销毁的Agent数量
        """
        async with self._write_lock:
            count = len(self._agents)
            self._agents.clear()
            return count

    async def has_agent(self, conversation_id: str) -> bool:
        """检查是否存在指定对话ID的Agent

        Args:
            conversation_id: 对话ID

        Returns:
            bool: 是否存在
        """
        async with self._read_semaphore:
            return conversation_id in self._agents

    async def get_agent_count(self) -> int:
        """获取当前管理的agent数量

        Returns:
            int: agent数量
        """
        async with self._read_semaphore:
            return len(self._agents)

    async def get_agent_info(self, conversation_id: str) -> Optional[Dict]:
        """获取指定agent的信息

        Args:
            conversation_id: 对话ID

        Returns:
            Dict: agent信息或None（如果不存在）
        """
        async with self._read_semaphore:
            if conversation_id in self._agents:
                return self._agents[conversation_id].info
            return None

    async def get_all_agents_info(self) -> Dict[str, Dict]:
        """获取所有agent的信息

        Returns:
            Dict: 所有agent的信息字典
        """
        async with self._read_semaphore:
            return {conv_id: agent_info.info for conv_id, agent_info in self._agents.items()}

    async def _cleanup_inactive_agents(self) -> int:
        """清理不活跃的Agent实例

        Returns:
            int: 清理的Agent数量
        """
        async with self._write_lock:
            now = datetime.now()
            inactive_conversations = [
                conv_id for conv_id, agent_info in self._agents.items()
                if now - agent_info.last_active > self.active_time
            ]

            for conv_id in inactive_conversations:
                del self._agents[conv_id]

            if inactive_conversations:
                await logger.ainfo(f"Cleaned up {len(inactive_conversations)} expired agents")

            return len(inactive_conversations)

    async def _periodic_cleanup(self):
        """周期性清理任务"""
        while True:
            try:
                cleaned_count = await self._cleanup_inactive_agents()
                if cleaned_count > 0:
                    await logger.ainfo(f"Cleaned up {cleaned_count} expired agents")
                await asyncio.sleep(self._cleanup_interval)
            except asyncio.CancelledError:
                await logger.ainfo("Periodic cleanup task was cancelled")
                break
            except Exception as e:
                await logger.aerror(f"Error during periodic cleanup: {e}")
                await asyncio.sleep(self._cleanup_interval)

    async def start_cleanup_task(self):
        """启动周期性清理任务"""
        async with self._write_lock:
            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
                await logger.ainfo("Started periodic cleanup task for agents")

    async def stop_cleanup_task(self):
        """停止周期性清理任务"""
        async with self._write_lock:
            if self._cleanup_task and not self._cleanup_task.done():
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
                finally:
                    self._cleanup_task = None
                await logger.ainfo("Stopped periodic cleanup task for agents")

    async def configure_cleanup(self, interval: int = 60, active_time: int = 3600):
        """配置清理参数

        Args:
            interval: 清理间隔（秒）
            active_time: agent活跃时间（秒）
        """
        async with self._write_lock:
            self._cleanup_interval = interval
            self.active_time = timedelta(seconds=active_time)

    async def manual_cleanup(self) -> int:
        """手动触发清理过期agent

        Returns:
            int: 清理的agent数量
        """
        async with self._write_lock:
            return await self._cleanup_inactive_agents()


# 全局Agent管理器实例
agent_manager = AgentManager()
