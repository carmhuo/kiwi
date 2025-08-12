from typing import Optional, List

from sqlalchemy.orm import selectinload

from kiwi.core.database import BaseCRUD
from kiwi.models import Conversation, Message
from sqlalchemy import select, desc, update, func
from sqlalchemy.ext.asyncio import AsyncSession


class ConversationCRUD(BaseCRUD):
    def __init__(self):
        super().__init__(Conversation)

    async def create_conversation(
            self, db: AsyncSession, project_id: str, user_id: str, title: str
    ) -> Conversation:
        conversation_dict = {
            "project_id": project_id,
            "user_id": user_id,
            "title": title
        }
        conversation = await self.create(db, conversation_dict)
        return conversation

    async def get_conversation(
            self, db: AsyncSession, conversation_id: str
    ) -> Optional[Conversation]:
        result = await db.execute(
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .where(Conversation.id == conversation_id)
        )
        return result.scalars().first()

    async def get_user_conversations(
            self,
            db: AsyncSession,
            user_id: str,
            skip,
            limit,
            project_id: str = None
    ):
        """获取用户的对话列表"""

        stmt = select(Conversation).where(
            Conversation.user_id == user_id
        )

        if project_id:
            stmt = stmt.where(Conversation.project_id == project_id)

        stmt = stmt.order_by(desc(Conversation.updated_at)).limit(limit).offset(skip)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def create_message(
            self,
            db: AsyncSession,
            conversation_id: str,
            user_id: str,
            content: str,
            sql_query: Optional[str] = None,
            raw_data: Optional[dict] = None,
            report_data: Optional[dict] = None,
            agent_version_id: Optional[str] = None
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            content=content,
            role="user" if agent_version_id is None else "assistant",
            sql_query=sql_query,
            raw_data=raw_data,
            report_data=report_data,
            agent_version_id=agent_version_id
        )
        db.add(message)
        await db.flush()
        await db.refresh(message)

        # 更新对话更新时间
        await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=func.now())
        )
        await db.flush()

        return message

    async def record_feedback(
            self, db: AsyncSession, message_id: str, feedback_type: int, feedback_text: Optional[str] = None
    ) -> Message:
        result = await db.execute(
            update(Message)
            .where(Message.id == message_id)
            .values(
                feedback_type=feedback_type,
                feedback_text=feedback_text
            )
            .returning(Message)
        )
        await db.flush()
        return result.scalars().first()

    async def get_conversation_history(
            self, db: AsyncSession, conversation_id: str, limit: int = 10
    ) -> List[Message]:
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def archive_old_conversations(
            self,
            db: AsyncSession,
            max_age_days: int = 180
    ):
        """归档超过指定天数的对话"""
        from datetime import datetime, timedelta
        cutoff_date = datetime.now() - timedelta(days=max_age_days)

        # 标记归档
        stmt = update(Conversation).where(
            Conversation.updated_at < cutoff_date,
            Conversation.archived == False
        ).values(archived=True)

        result = await db.execute(stmt)
        return result.rowcount


class MessageCRUD(BaseCRUD):
    def __init__(self):
        super().__init__(Message)

    async def create_with_feedback(
            self,
            db: AsyncSession,
            message_data: dict,
            feedback_type: int = None,
            feedback_text: str = None
    ):
        """创建消息并记录反馈"""
        if feedback_type is not None:
            message_data["feedback_type"] = feedback_type
        if feedback_text is not None:
            message_data["feedback_text"] = feedback_text

        return await self.create(db, message_data)

    async def get_conversation_messages(
            self,
            db: AsyncSession,
            conversation_id: int,
            limit: int = 50
    ):
        """获取对话的消息历史"""
        stmt = select(Message).where(
            Message.conversation_id == conversation_id
        ).order_by(Message.created_at).limit(limit)

        result = await db.execute(stmt)
        return result.scalars().all()

    async def record_feedback(
            self,
            db: AsyncSession,
            message_id: int,
            feedback_type: int,
            feedback_text: str = None
    ):
        """记录用户反馈"""
        message = await self.get(db, message_id)
        if not message:
            return None

        update_data = {"feedback_type": feedback_type}
        if feedback_text:
            update_data["feedback_text"] = feedback_text

        return await self.update(db, message, update_data)

    async def get_agent_training_data(
            self,
            db: AsyncSession,
            min_accuracy: float = 0.8,
            limit: int = 1000
    ):
        """获取高质量对话数据用于Agent训练"""
        # 获取高准确率的对话
        stmt = select(Message).where(
            Message.feedback_type == 1,  # 正确反馈
            Message.role == "user",  # 用户消息
            Message.sql_query.is_not(None)  # 有对应的SQL
        ).join(Conversation).order_by(
            desc(Conversation.updated_at)
        ).limit(limit)

        result = await db.execute(stmt)
        return result.scalars().all()
