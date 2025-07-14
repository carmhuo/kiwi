from kiwi_backend.database import BaseCRUD
from kiwi_backend.models import Agent, AgentVersion, AgentMetric
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime


class AgentCRUD(BaseCRUD):
    def __init__(self):
        super().__init__(Agent)

    async def create_with_version(
            self,
            db: AsyncSession,
            agent_data: dict,
            version_data: dict
    ):
        """创建Agent并添加初始版本"""
        agent = await self.create(db, agent_data)

        # 创建初始版本
        await self.create_version(
            db,
            agent_id=agent.id,
            version_data=version_data
        )
        return agent

    async def create_version(
            self,
            db: AsyncSession,
            agent_id: int,
            version_data: dict
    ):
        """创建Agent新版本"""
        # 获取当前版本号
        stmt = select(func.max(AgentVersion.version)).where(
            AgentVersion.agent_id == agent_id
        )
        result = await db.execute(stmt)
        max_version = result.scalar_one_or_none()

        # 生成新版本号
        if max_version:
            major, minor, patch = map(int, max_version.split('.'))
            new_version = f"{major}.{minor}.{patch + 1}"
        else:
            new_version = "1.0.0"

        # 创建版本记录
        version = AgentVersion(
            agent_id=agent_id,
            version=new_version,
            config=version_data["config"],
            checksum=version_data["checksum"],
            created_by=version_data["created_by"],
            is_current=True
        )
        db.add(version)
        await db.flush()

        # 将其他版本标记为非当前
        stmt = update(AgentVersion).where(
            AgentVersion.agent_id == agent_id,
            AgentVersion.id != version.id
        ).values(is_current=False)
        await db.execute(stmt)

        return version

    async def rollback_version(
            self,
            db: AsyncSession,
            agent_id: int,
            target_version: str
    ):
        """回滚到指定版本"""
        # 获取目标版本
        stmt = select(AgentVersion).where(
            AgentVersion.agent_id == agent_id,
            AgentVersion.version == target_version
        )
        result = await db.execute(stmt)
        target = result.scalar_one_or_none()

        if not target:
            raise ValueError(f"版本 {target_version} 不存在")

        # 创建新版本（复制目标版本配置）
        new_version_data = {
            "config": target.config,
            "checksum": target.checksum,
            "created_by": target.created_by
        }
        return await self.create_version(db, agent_id, new_version_data)

    async def record_metric(
            self,
            db: AsyncSession,
            version_id: int,
            sql_gen_latency: float,
            query_success: bool
    ):
        """记录Agent性能指标"""
        # 获取当前指标记录
        stmt = select(AgentMetric).where(
            AgentMetric.agent_version_id == version_id
        ).order_by(AgentMetric.created_at.desc()).limit(1)
        result = await db.execute(stmt)
        last_metric = result.scalar_one_or_none()

        # 计算新成功率
        if last_metric:
            total = last_metric.total_queries + 1
            success = last_metric.success_queries + (1 if query_success else 0)
            success_rate = success / total
        else:
            total = 1
            success = 1 if query_success else 0
            success_rate = 1.0 if query_success else 0.0

        # 创建新指标记录
        metric = AgentMetric(
            agent_version_id=version_id,
            sql_gen_latency=sql_gen_latency,
            total_queries=total,
            success_queries=success,
            query_success_rate=success_rate
        )
        db.add(metric)
        await db.flush()
        return metric