import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

from langchain_core.messages import BaseMessage, AIMessage
from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.core.exceptions import ConversationNotFoundError, UnauthorizedAccessError
from kiwi.crud.agent import AgentCRUD
from kiwi.crud.conversation import ConversationCRUD
from kiwi.models import Conversation
from kiwi.schemas import MessageResponse, MessageCreate


class MessageType(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


@dataclass
class MessageContext:
    """
    消息上下文数据类
    """
    conversation_id: str
    user_id: str
    content: str
    message_type: MessageType
    metadata: Optional[Dict[str, Any]] = None


class ConversationManager:
    """Handles conversation lifecycle operations"""

    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id
        self.crud = ConversationCRUD()

    async def get_or_create_conversation(
            self,
            conv_id: Optional[str],
            project_id: str,
            first_message: str
    ) -> Conversation:
        """Get existing conversation or create new one"""
        if conv_id:
            conversation = await self.crud.get_conversation(self.db, conv_id)
            if not conversation:
                raise ConversationNotFoundError(f"Conversation {conv_id} not found")
            return conversation

        title = first_message[:50] + "..." if len(first_message) > 50 else first_message
        return await self.crud.create_conversation(
            self.db, project_id, self.user_id, title
        )

    async def get_conversation_detail(self, conversation_id: str) -> Dict[str, Any]:
        """Get conversation details with messages"""
        conversation = await self.crud.get_conversation(self.db, conversation_id)
        if not conversation:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")

        if conversation.user_id != self.user_id:
            raise UnauthorizedAccessError("User not authorized to access this conversation")

        messages = [{
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "sql_query": msg.sql_query,
            "report_data": msg.report_data,
            "created_at": msg.created_at
        } for msg in conversation.messages]

        return {
            "id": conversation.id,
            "title": conversation.title,
            "project_id": conversation.project_id,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "messages": messages
        }

    async def get_user_conversations(
            self,
            project_id: Optional[str] = None,
            skip: int = 0,
            limit: int = 100
    ) -> tuple[List[Conversation], int]:
        """Get paginated list of user conversations"""
        if project_id:
            count = await self.crud.count(self.db, user_id=self.user_id, project_id=project_id)
        else:
            count = await self.crud.count(self.db, user_id=self.user_id)

        conversations = await self.crud.get_user_conversations(
            self.db,
            self.user_id,
            project_id=project_id,
            skip=skip,
            limit=limit
        )

        return conversations, count


class MessageManager:
    """Handles all message-related operations including persistence, formatting and conversion"""

    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id
        self.crud = ConversationCRUD()

    async def persist_user_message(
            self,
            message_data: MessageCreate,
            project_id: str
    ) -> str:
        """
        Persist user message and return conversation ID.
        Creates new conversation if conversation_id is not provided.
        """
        conversation = await ConversationManager(
            self.db, self.user_id
        ).get_or_create_conversation(
            message_data.conversation_id,
            project_id,
            message_data.content
        )

        await self.crud.create_message(
            self.db,
            conversation.id,
            self.user_id,
            message_data.content
        )

        await self.db.commit()

        return conversation.id

    async def persist_system_message(
            self,
            conversation_id: str,
            project_id: str,
            content: str,
            sql_query: Optional[str] = None,
            raw_data: Optional[Dict[str, Any]] = None,
            report_data: Optional[Dict[str, Any]] = None
    ) -> MessageResponse:
        """Persist system message with optional SQL and report data"""
        message = await self.crud.create_message(
            self.db,
            conversation_id,
            self.user_id,
            content=content,
            sql_query=sql_query,
            raw_data=raw_data,
            report_data=report_data,
            agent_version_id=await self._get_active_agent_version(project_id, "TEXT2SQL")
        )

        return MessageResponse(
            id=message.id,
            role=message.role,
            content=message.content,
            sql_query=sql_query,
            report_data=report_data,
            created_at=message.created_at
        )

    async def get_conversation_messages(
            self,
            conversation_id: str,
            limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get messages for a conversation"""
        messages = await self.crud.get_conversation_history(
            self.db, conversation_id, limit=limit
        )
        return [self._message_to_dict(msg) for msg in messages]

    def format_agent_message(self, message: BaseMessage) -> Dict[str, Any]:
        """Convert LangChain message to response format"""
        return {
            "id": getattr(message, 'id', None),
            "role": getattr(message, 'type', 'assistant'),
            "content": getattr(message, 'content', ''),
            "name": getattr(message, 'name', None),
            "tool_calls": getattr(message, 'tool_calls', None),
            "created_at": datetime.now()
        }

    def format_stream_message(self, message: AIMessage) -> str:
        """Format streaming message for SSE"""
        if hasattr(message, 'model_dump_json'):
            return f"data: {message.model_dump_json()}\n\n"

        return f"data: {json.dumps(self.format_agent_message(message))}\n\n"

    def create_error_message(self, error: Exception) -> Dict[str, Any]:
        """Create error message response"""
        return {
            "role": "system",
            "content": f"Error: {str(error)}",
            "error": True
        }

    async def _get_active_agent_version(
            self,
            project_id: str,
            agent_type: str
    ) -> Optional[str]:
        """Get active agent version ID (internal helper)"""
        agent = await AgentCRUD().get_active_agent_with_history_versions(
            self.db, project_id, agent_type
        )
        if agent and agent.versions:
            for version in agent.versions:
                if version.is_current:
                    return version.id
        return None

    def _message_to_dict(self, message: Any) -> Dict[str, Any]:
        """Convert ORM message to dict (internal helper)"""
        return {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "sql_query": message.sql_query,
            "report_data": message.report_data,
            "created_at": message.created_at
        }
