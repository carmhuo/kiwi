from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.core.services.agent_service import AgentService
from kiwi.core.services.chart_service import ChartService
from kiwi.core.services.conversation_message import ConversationManager, MessageManager
from kiwi.core.services.llm_service import LLMService
from kiwi.crud.conversation import ConversationCRUD
from kiwi.schemas import MessageCreate, MessageResponse
from kiwi.core.monitoring import (
    track_errors,
    AGENT_ERRORS
)
from kiwi.core.config import logger

StreamMode = Literal["values", "messages", "updates", "events", "debug", "custom"]


class FeedbackService:
    """Handles user feedback processing"""

    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id

    @track_errors(AGENT_ERRORS)
    async def record_feedback(self, feedback_data: Dict[str, Any]):
        """Record user feedback and trigger improvements if needed"""
        await ConversationCRUD().record_feedback(
            self.db,
            feedback_data["message_id"],
            feedback_data["feedback_type"],
            feedback_data.get("feedback_text")
        )

        if feedback_data["feedback_type"] in [0, 2, 3]:
            await self._trigger_agent_improvement(
                feedback_data["message_id"],
                feedback_data["feedback_type"],
                feedback_data.get("feedback_text")
            )

    async def _trigger_agent_improvement(
            self,
            message_id: str,
            feedback_type: int,
            feedback_text: Optional[str]
    ):
        """Trigger agent improvement based on negative feedback"""
        message = await ConversationCRUD().get_message(self.db, message_id)
        if not message:
            return

        training_data = {
            "input": message.content,
            "sql": message.sql_query,
            "output": message.report_data,
            "feedback": feedback_type,
            "comment": feedback_text
        }

        logger.info(f"Recording feedback for agent improvement: {training_data}")
        # In production, this would send to a training pipeline


class ConversationService:
    """Main service facade that coordinates all conversation operations

    Orchestrates the end-to-end conversation flow by coordinating various specialized services.

    Responsibilities:
    - Coordinates interactions between message processing, agent execution and conversation management
    - Provides high-level API for conversation operations
    - Maintains workflow consistency across different conversation scenarios

    """

    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id
        self.conversation_manager = ConversationManager(db, user_id)
        self.llm_service = LLMService(db, user_id)
        self.message_service = MessageManager(db, user_id)
        self.agent_service = AgentService(db, user_id)
        self.feedback_service = FeedbackService(db, user_id)
        self.chart_service = ChartService(db, user_id)

    async def process_message(self, message_data: MessageCreate, project_id: str) -> MessageResponse:
        """Process user message through full pipeline"""
        async with self.llm_service.processing_context(None, project_id) as context:
            # Persist user message
            conversation_id = await self.message_service.persist_user_message(
                message_data,
                project_id
            )
            context.conversation_id = conversation_id

            # Generate SQL
            sql_query = await self.llm_service.generate_sql(
                message_data.content,
                conversation_id,
                project_id
            )

            # Execute query
            query_result = await self.llm_service.execute_query(sql_query, project_id)

            # Generate chart
            chart_config = await self.chart_service.generate_chart(
                message_data.content,
                query_result,
                project_id
            )

            # Create system message
            system_message = await self.message_service.persist_system_message(
                conversation_id,
                project_id,
                content=self.llm_service.format_response(query_result, chart_config),
                sql_query=sql_query,
                raw_data=query_result,
                report_data=chart_config
            )

            return system_message

    # Delegate other methods to appropriate services
    async def get_conversation_detail(self, conversation_id: str) -> Dict[str, Any]:
        return await self.conversation_manager.get_conversation_detail(conversation_id)

    async def get_user_conversations(self, project_id: Optional[str] = None, skip: int = 0, limit: int = 100):
        return await self.conversation_manager.get_user_conversations(project_id, skip, limit)

    async def event_stream_generator(self, message: MessageCreate, project_id: str, generate_chart: bool = False):

        async def _handle_stream_result(result_message):
            try:
                await logger.adebug(f"on complete, {result_message}")
                sql_query = result_message.get("generated_sql")
                raw_data = result_message.get("raw_data")
                content = result_message.get("content")
                conv_id = result_message.get("conversation_id")
                user_query = result_message.get("user_query")

                report_data = None

                if generate_chart:
                    report_data = await self.chart_service.generate_chart(
                        user_query,
                        raw_data,
                        project_id
                    )

                message_response = await self.message_service.persist_system_message(
                    conv_id,
                    project_id,
                    content=content,
                    sql_query=sql_query,
                    raw_data=raw_data,
                    report_data=report_data
                )
                await self.db.commit()
                return message_response.model_dump_json()
            except Exception as e:
                await logger.aerror(f"Error handling stream result: {e}")
                return {
                    "error": True,
                    "role": "system",
                    "content": f"Error handling stream result: {e}"
                }

        conversation_id = await self.message_service.persist_user_message(message, project_id)

        async for event in self.agent_service.stream_agent_events(
                message,
                project_id,
                on_complete=_handle_stream_result
        ):
            yield event

    async def invoke_agent_endpoint(self, message: MessageCreate, project_id: str, generate_chart: bool = False):
        conversation_id = await self.message_service.persist_user_message(message, project_id)

        response_message = await self.agent_service.invoke_agent(message, project_id, generate_chart)

        user_query = message.content
        sql_query = response_message.get("generated_sql")
        raw_data = response_message.get("raw_data")
        content = response_message.get("content")

        report_data = None

        if generate_chart:
            report_data = await self.chart_service.generate_chart(
                user_query,
                raw_data,
                project_id
            )

        message_response = await self.message_service.persist_system_message(
            conversation_id,
            project_id,
            content=content,
            sql_query=sql_query,
            raw_data=raw_data,
            report_data=report_data
        )
        return message_response

    async def record_feedback(self, feedback_data: Dict[str, Any]):
        await self.feedback_service.record_feedback(feedback_data)
