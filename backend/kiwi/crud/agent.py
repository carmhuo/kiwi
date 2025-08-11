import hashlib
import json
import re
from typing import Optional, List

from kiwi.core.database import BaseCRUD
from kiwi.core.monitoring import track_errors, AGENT_ERRORS
from kiwi.models import Agent, AgentVersion, AgentMetric
from sqlalchemy import select, func, update, and_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from sqlalchemy.orm import selectinload

AGENT_INIT_VERSION = "v1.0.0"


class AgentCRUD(BaseCRUD):
    def __init__(self):
        super().__init__(Agent)

    @track_errors(AGENT_ERRORS)
    async def create_agent(
            self, db: AsyncSession, agent_data: dict, user_id: str
    ) -> Agent:
        # 生成配置校验和
        config_str = json.dumps(agent_data["config"], sort_keys=True)
        checksum = hashlib.sha256(config_str.encode()).hexdigest()

        db_agent = Agent(
            **agent_data,
            created_by=user_id,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        # 创建初始版本
        initial_version = AgentVersion(
            agent=db_agent,
            version=AGENT_INIT_VERSION,
            config=agent_data["config"],
            checksum=checksum,
            created_by=user_id,
            is_current=True
        )

        db.add(db_agent)
        db.add(initial_version)
        await db.flush()
        await db.refresh(db_agent)
        # 添加审计
        # await audit_log(
        #     action="CREATE",
        #     target_type="AGENT",
        #     target_id=db_agent.id,
        #     user_id=user_id
        # )
        return db_agent

    async def get_agent(self, db: AsyncSession, agent_id: str) -> Optional[Agent]:
        result = await db.execute(
            select(Agent)
            .options(selectinload(Agent.versions))
            .where(Agent.id == agent_id)
        )
        return result.scalars().first()

    async def update_agent(
            self, db: AsyncSession, agent_id: str, update_data: dict, user_id: str
    ) -> Optional[Agent]:
        # 获取当前Agent
        agent = await self.get_agent(db, agent_id)
        if not agent:
            return None

        # 如果配置变更则创建新版本
        if "config" in update_data:
            config_str = json.dumps(update_data["config"], sort_keys=True)
            new_checksum = hashlib.sha256(config_str.encode()).hexdigest()

            # 查找最新版本
            latest_version = max(agent.versions, key=lambda v: v.created_at)

            # 仅当配置变更时创建新版本
            if new_checksum != latest_version.checksum:
                # 生成新版本号 (自动递增小版本)
                major, minor, patch = latest_version.version[1:].split(".")
                new_version = f"v{major}.{minor}.{int(patch) + 1}"

                # 创建新版本
                new_version = AgentVersion(
                    agent_id=agent_id,
                    version=new_version,
                    config=update_data["config"],
                    checksum=new_checksum,
                    created_by=user_id,
                    is_current=True
                )

                # 将旧版本标记为非当前
                await db.execute(
                    update(AgentVersion)
                    .where(AgentVersion.agent_id == agent_id)
                    .values(is_current=False)
                )

                db.add(new_version)
                update_data["updated_at"] = datetime.now()
            # 更新Agent基础信息
            # await db.execute(
            #     update(Agent)
            #     .where(Agent.id == agent_id)
            #     .values(**update_data)
            # )
        return await self.update(db, agent, update_data)

    async def rollback_version(
            self, db: AsyncSession, agent_id: str, version: str, user_id: str
    ) -> Optional[Agent]:
        # 获取目标版本
        result = await db.execute(
            select(AgentVersion)
            .where(
                (AgentVersion.agent_id == agent_id) &
                (AgentVersion.version == version)
            )
        )
        target_version = result.scalars().first()

        if not target_version:
            return None
        next_version = await self.get_next_version(db, agent_id)
        # 创建回滚版本 (使用原始配置)
        rollback_version = AgentVersion(
            agent_id=agent_id,
            version=next_version,
            config=target_version.config,
            checksum=target_version.checksum,
            created_by=user_id,
            is_current=True
        )

        # 将旧版本标记为非当前
        await db.execute(
            update(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .values(is_current=False)
        )

        # 更新Agent配置
        await db.execute(
            update(Agent)
            .where(Agent.id == agent_id)
            .values(config=target_version.config)
        )

        db.add(rollback_version)
        await db.flush()
        return await self.get_agent(db, agent_id)

    @staticmethod
    async def get_next_version(db: AsyncSession, agent_id: str) -> Optional[str]:
        result = await db.execute(
            select(func.max(AgentVersion.version))
            .where(AgentVersion.agent_id == agent_id)
        )
        latest_version = result.scalar_one_or_none()
        if not latest_version:
            return AGENT_INIT_VERSION

        # 使用正则确保版本号格式正确
        match = re.match(r"^v(\d+)\.(\d+)\.(\d+)$", latest_version)
        if not match:
            # 可选：抛出异常或记录日志
            return None

        major, minor, patch = match.groups()
        new_version = f"v{major}.{minor}.{int(patch) + 1}"
        return new_version

    @staticmethod
    async def record_metric(
            db: AsyncSession, version_id: str, metric_data: dict
    ) -> AgentMetric:
        db_metric = AgentMetric(
            version_id=version_id,
            **metric_data,
            created_at=datetime.now()
        )
        db.add(db_metric)
        await db.flush()
        await db.refresh(db_metric)
        return db_metric

    async def calculate_metric(
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

    async def get_active_agent(self, db, project_id, agent_type) -> Optional[Agent]:
        """获取指定项目和类型的活跃Agent

        Args:
            db: 异步数据库会话
            project_id: 项目ID
            agent_type: Agent类型

        Returns:
            Agent对象 或 None(如果不存在)
        """
        stmt = (
            select(Agent)
            .where(and_(
                Agent.is_active == True,
                Agent.project_id == project_id,
                Agent.type == agent_type
            ))
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_active_agent_with_history_versions(self, db, project_id, agent_type) -> Optional[Agent]:
        """获取指定项目和类型的活跃Agent及其所有版本

        Args:
            db: 异步数据库会话
            project_id: 项目ID
            agent_type: Agent类型

        Returns:
            Agent对象(包含所有版本) 或 None(如果不存在)
        """
        stmt = (
            select(Agent)
            .options(
                selectinload(Agent.versions)
            )
            .where(and_(
                Agent.is_active == True,
                Agent.project_id == project_id,
                Agent.type == agent_type
            ))
            .order_by(Agent.created_at.desc())
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_agent_by_name(self, db, name) -> Optional[Agent]:
        """通过名称获取Agent信息"""
        result = await db.execute(
            select(Agent)
            .where(Agent.name == name)
        )
        return result.scalars().first()

    async def list_agents(self, db, project_id, skip, limit) -> List[Agent]:
        """获取指定项目的所有代理
        Args:
            db: 数据库连接对象，用于执行SQL查询
            project_id: 项目ID，用于筛选特定项目的代理
            skip: 跳过指定数量的代理
            limit: 返回指定数量的代理
        Returns:
            指定项目的代理列表
        """
        return await self.get_multi(db, skip, limit, project_id=project_id)

    async def list_agent_versions(self, db, agent_id, skip, limit) -> List[AgentVersion]:
        """获取指定Agent的所有版本
        Args:
            db: 数据库连接对象，用于执行SQL查询
            agent_id: 代理ID，用于筛选特定代理的版本
            skip: 跳过指定数量的版本
            limit: 返回指定数量的版本
        Returns:
            指定Agent的版本列表
        """
        result = await db.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.version.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    async def count_agent_versions(self, db, agent_id):
        """统计指定代理的所有版本数量
        Args:
            db: 数据库连接对象，用于执行SQL查询
            agent_id: 代理ID，用于筛选特定代理的版本
        Returns:
            指定代理的版本数量，如果查询结果为空则返回0
        """
        stmt = (select(func.count()).select_from(AgentVersion)
                .where(AgentVersion.agent_id == agent_id))  # type: ignore
        result = await db.execute(stmt)
        return result.scalar() or 0
