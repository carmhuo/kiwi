from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.agents.agent_manger import AgentType
from kiwi.core.exceptions import AgentProcessingError
from kiwi.core.monitoring import track_errors, AGENT_ERRORS, AGENT_SQL_GEN_LATENCY, timing_metrics, \
    DATABASE_QUERY_DURATION
from kiwi.core.retry import async_retry
from kiwi.core.security import DataMasker, SQLValidator
from kiwi.crud.agent import AgentCRUD
from kiwi.crud.conversation import ConversationCRUD


@dataclass
class ProcessingContext:
    """Context for message processing operations"""
    db: AsyncSession
    user_id: str
    conversation_id: str
    project_id: str


class LLMService:
    """Handles message processing logic"""

    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id
        self.conversation_crud = ConversationCRUD()
        self.agent_crud = AgentCRUD()
        self.data_masker = DataMasker()
        self.sql_validator = SQLValidator()

    @asynccontextmanager
    async def processing_context(self, conversation_id: str, project_id: str):
        """Context manager for processing operations"""
        context = ProcessingContext(
            db=self.db,
            user_id=self.user_id,
            conversation_id=conversation_id,
            project_id=project_id
        )
        try:
            yield context
            await self.db.commit()
        except Exception as e:
            await self.db.rollback()
            raise AgentProcessingError(f"Message processing failed: {str(e)}") from e

    @async_retry(
        max_retries=3,
        initial_delay=1.0,
        backoff_factor=2.0
    )
    @track_errors(AGENT_ERRORS)
    async def generate_sql(
            self,
            query: str,
            conversation_id: str,
            project_id: str
    ) -> str:
        """Generate SQL query from natural language"""
        async with timing_metrics(AGENT_SQL_GEN_LATENCY, {"project_id": project_id}):
            agent = await self.agent_crud.get_active_agent(
                self.db, project_id, AgentType.TEXT_TO_SQL.value
            )
            if not agent:
                raise ValueError("No active TEXT2SQL agent found for project")

            history = await self.conversation_crud.get_conversation_history(
                self.db, conversation_id, limit=5
            )

            from kiwi.agents.text2sql_agent import TextToSQLAgent
            text2sql_agent = TextToSQLAgent(agent.config)
            sql_query = await text2sql_agent.generate_sql(query, history)

            self.sql_validator.validate(sql_query)
            return sql_query

    @async_retry(
        max_retries=3,
        initial_delay=1.0,
        backoff_factor=2.0
    )
    async def execute_query(self, sql: str, project_id: str) -> Dict[str, Any]:
        """Execute SQL query and return results"""
        async with timing_metrics(DATABASE_QUERY_DURATION, {"project_id": project_id}):
            from kiwi.core.engine.federation_query_engine import get_engine
            query_engine = get_engine()
            result = await query_engine.execute_query(sql)

            result["data"] = self.data_masker.mask_sensitive_data(
                result["data"],
                project_id
            )

            return result
