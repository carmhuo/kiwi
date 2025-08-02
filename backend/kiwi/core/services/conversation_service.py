import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, Literal, List

from fastapi import HTTPException
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.agents.agent_manger import agent_manager, AgentType

from kiwi.core.retry import async_retry
from kiwi.core.security import DataMasker, SQLValidator
from kiwi.crud.conversation import ConversationCRUD
from kiwi.crud.agent import AgentCRUD
from kiwi.schemas import MessageCreate, MessageResponse
from kiwi.models import Conversation
from kiwi.core.monitoring import (
    timing_metrics,
    AGENT_SQL_GEN_LATENCY,
    DATABASE_QUERY_DURATION,
    track_errors,
    AGENT_ERRORS
)
from kiwi.core.config import logger

StreamMode = Literal["values", "messages", "updates", "events", "debug", "custom"]


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


class ConversationService:
    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id

    @track_errors(AGENT_ERRORS)
    async def process_message(self, message_data: MessageCreate, project_id: str) -> MessageResponse:
        """
        处理用户消息的全流程
        """
        # 检查是否缓存命中
        # cache = await CacheManager.get_cache()
        # cache_key = f"conv:{project_id}:{message_data.content[:50]}"
        # if cached := await cache.get(cache_key):
        #     logger.info(f"Cache hit for query: {message_data.content[:50]}")
        #     return MessageResponse(**json.loads(cached))

        # 获取或创建对话
        conversation = await self._get_or_create_conversation(
            message_data.conversation_id, project_id, message_data.content
        )

        # 创建用户消息记录
        user_message = await ConversationCRUD().create_message(
            self.db, conversation.id, self.user_id, message_data.content
        )

        await self.db.commit()

        # 调用TEXT2SQL Agent生成SQL
        sql_query = await self._generate_sql(
            message_data.content,
            conversation.id,
            project_id
        )

        # 执行SQL查询
        query_result = await self._execute_query(sql_query, project_id)

        # 生成图表
        chart_config = await self._generate_chart(
            message_data.content,
            query_result,
            project_id
        )

        # 创建系统消息记录
        system_message = await ConversationCRUD().create_message(
            self.db,
            conversation.id,
            self.user_id,
            content=self._format_response(query_result, chart_config),
            sql_query=sql_query,
            raw_data=query_result,
            report_data=chart_config,
            agent_version_id=await self._get_active_agent_version(project_id, "TEXT2SQL")
        )

        # 构建响应
        response = MessageResponse(
            id=system_message.id,
            role=system_message.role,
            content=system_message.content,
            sql_query=sql_query,
            report_data=chart_config,
            created_at=system_message.created_at
        )

        # 缓存结果 (5分钟)
        # await self.cache.set(cache_key, response.model_dump(), ttl=300)

        return response

    async def _get_or_create_conversation(
            self,
            conv_id: Optional[str],
            project_id: str,
            first_message: str
    ) -> Conversation:
        """获取现有对话或创建新对话

        如果提供了conv_id，则尝试获取现有的对话；如果不存在则抛出ValueError。
        如果没有提供conv_id，则根据project_id和first_message创建一个新的对话。

        Args:
            conv_id: 对话ID，如果提供则尝试获取现有对话
            project_id: 项目ID，用于创建新对话时关联项目
            first_message: 首条消息内容，用于创建新对话时生成对话标题

        Returns:
            Conversation对象

        Raises:
            ValueError: 当提供的conv_id对应的对话不存在时抛出异常
        """
        if conv_id:
            conversation = await ConversationCRUD().get_conversation(self.db, conv_id)
            if not conversation:
                raise ValueError(f"Conversation {conv_id} not found")
            return conversation

        # 创建新对话
        title = first_message[:50] + "..." if len(first_message) > 50 else first_message
        return await ConversationCRUD().create_conversation(
            self.db, project_id, self.user_id, title
        )

    async def _get_active_agent_version(self, project_id: str, agent_type: str) -> Optional[str]:
        """获取项目中指定类型Agent的当前版本ID

        Args:
            project_id: 项目ID
            agent_type: 代理类型（如TEXT2SQL、CHART_GENERATOR等）

        Returns:
            当前激活的Agent版本ID，如果没有找到则返回None
        """
        agent = await AgentCRUD().get_active_agent(self.db, project_id, agent_type)
        if agent and agent.versions:
            for version in agent.versions:
                if version.is_current:
                    return version.id
        return None

    @async_retry(max_retries=3, initial_delay=0.1, backoff_factor=2)
    async def _generate_sql(self, query: str, conv_id: str, project_id: str) -> str:
        # 获取项目配置和Agent
        async with timing_metrics(AGENT_SQL_GEN_LATENCY, {"project_id": project_id}):
            agent = await AgentCRUD().get_active_agent(self.db, project_id, AgentType.TEXT_TO_SQL.value)
            if not agent:
                raise ValueError("No active TEXT2SQL agent found for project")

            # 获取对话历史
            history = await ConversationCRUD().get_conversation_history(self.db, conv_id, limit=5)

            # 调用Agent
            # from kiwi.agents.text2sql_agent import TextToSQLAgent
            text2sql_agent = TextToSQLAgent(agent.config)
            sql_query = await text2sql_agent.generate_sql(query, history)

            # SQL安全校验
            SQLValidator.validate(sql_query)

            return sql_query

    @async_retry(max_retries=3, initial_delay=0.1, backoff_factor=2)
    async def _execute_query(self, sql: str, project_id: str) -> Dict[str, Any]:
        async with timing_metrics(DATABASE_QUERY_DURATION, {"project_id": project_id}):
            query_engine = QueryEngine(self.db, project_id)
            result = await query_engine.execute_query(sql)

            # 数据脱敏
            result["data"] = DataMasker.mask_sensitive_data(
                result["data"],
                project_id
            )

            return result

    async def _generate_chart(
            self,
            query: str,
            query_result: Dict[str, Any],
            project_id: str
    ) -> Dict[str, Any]:
        # 获取图表生成Agent
        agent = await AgentCRUD().get_active_agent(self.db, project_id, "CHART_GENERATOR")
        if not agent:
            logger.warning("No chart generator agent configured, returning raw data")
            return {
                "type": "table",
                "title": f"{query} - 结果",
                "data": query_result["data"],
                "columns": query_result["columns"]
            }
        try:
            # 调用Agent生成图表配置
            from kiwi.agents.chart_agent import ChartGeneratorAgent
            chart_agent = ChartGeneratorAgent(agent.config)
            return await chart_agent.generate_chart_config(query, query_result)
        except Exception as e:
            logger.error(f"图表生成失败: {str(e)}")
            # 降级为表格视图
            return {
                "type": "table",
                "title": f"{query} - 结果",
                "data": query_result["data"],
                "columns": query_result["columns"]
            }

    def _format_response(self, query_result: Dict[str, Any], chart_config: Dict[str, Any]) -> str:
        # 根据图表类型生成自然语言描述
        if chart_config.get("type") == "table":
            return (
                f"查询成功，共返回 {len(query_result['data'])} 条记录。\n"
                f"字段: {', '.join(query_result['columns'])}"
            )

            # 柱状图/折线图
        elif chart_config.get("type") in ["bar", "line"]:
            title = chart_config.get("title", "分析结果")
            x_axis = chart_config.get("x_axis", "X轴")
            y_axis = chart_config.get("y_axis", "Y轴")

            if isinstance(y_axis, list):
                y_axis = "、".join(y_axis)

            group_by = chart_config.get("group_by")
            group_text = f"，按 {group_by} 分组" if group_by else ""

            return (
                f"{title}\n"
                f"• X轴: {x_axis}\n"
                f"• Y轴: {y_axis}{group_text}"
            )

        # 饼图
        elif chart_config.get("type") == "pie":
            title = chart_config.get("title", "占比分析")
            category = chart_config.get("category", "类别")
            value = chart_config.get("value", "值")

            return (
                f"{title}\n"
                f"• 分类: {category}\n"
                f"• 数值: {value}"
            )

        # 默认响应
        return "数据分析已完成，请查看下方可视化结果"

    @track_errors(AGENT_ERRORS)
    async def record_feedback(self, feedback_data: Dict[str, Any]):
        await ConversationCRUD().record_feedback(
            self.db,
            feedback_data["message_id"],
            feedback_data["feedback_type"],
            feedback_data.get("feedback_text")
        )

        # 如果反馈为负面，触发Agent优化
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
        # 获取消息详情
        message = await ConversationCRUD().get_message(self.db, message_id)
        if not message:
            return

        # 记录到Agent训练数据集
        training_data = {
            "input": message.content,
            "sql": message.sql_query,
            "output": message.report_data,
            "feedback": feedback_type,
            "comment": feedback_text
        }

        # 实际生产中应使用消息队列处理
        logger.info(f"Recording feedback for agent improvement: {training_data}")
        # 这里可以添加将数据发送到训练管道的逻辑

    async def get_user_conversations(
            self,
            project_id: Optional[str] = None,
            skip: int = 0,
            limit: int = 100
    ):
        if project_id:
            count = await ConversationCRUD().count(self.db, user_id=self.user_id, project_id=project_id)
        else:
            count = await ConversationCRUD().count(self.db, user_id=self.user_id)

        conversations = await ConversationCRUD().get_user_conversations(
            self.db, self.user_id, project_id=project_id, skip=skip, limit=limit
        )

        return conversations, count

    async def get_conversation_detail(self, conversation_id: str) -> Dict[str, Any]:
        conversation = await ConversationCRUD().get_conversation(self.db, conversation_id)
        if not conversation:
            return None

        # 验证用户权限
        if conversation.user_id != self.user_id:
            raise PermissionError("User not authorized to access this conversation")

        messages = []
        for msg in conversation.messages:
            messages.append({
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "sql_query": msg.sql_query,
                "report_data": msg.report_data,
                "created_at": msg.created_at
            })

        return {
            "id": conversation.id,
            "title": conversation.title,
            "project_id": conversation.project_id,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "messages": messages
        }

    async def event_stream_generator(self, messages: List[MessageCreate], project_id: str):
        # Convert Pydantic model messages to LangChain HumanMessage objects
        # Note: graph input schema (InputState) is Dict[str, Any], expecting a 'messages' key
        # with a list of BaseMessage-compatible objects.
        conv_id = None
        input_messages: List[BaseMessage] = []
        for msg_item in messages:
            if msg_item.role.lower() == "user":
                input_messages.append(HumanMessage(content=msg_item.content))
                conv_id = msg_item.conversation_id
            # Add elif for "ai", "system", "tool" if your graph expects them in initial input
            else:
                # Fallback or raise error for unsupported roles in initial input
                print(f"Unsupported role in initial message: {msg_item.role}")

        if not input_messages:
            raise HTTPException(status_code=400, detail="No valid user messages provided")

        input = {"messages": input_messages}
        # https://python.langchain.com/docs/concepts/runnables/#runnableconfig
        # Prepare configurable parameters

        # TODO get cofig from DB
        kwargs = {
            "stream_mode": ["updates"]
        }
        # config = kwargs.pop("config")
        config = {
            'run_name': 'SQLAgent',
            'tags': ['kiwi', 'sql agent', 'graph'],
            "configurable": {
                "model": "Qwen/Qwen2.5-32B-Instruct",
                "thread_id": conv_id
            }
        }
        # stream_mode: list[StreamMode] = kwargs.pop("stream_mode")
        # stream_modes_set: set[StreamMode] = set(stream_mode) - {"events"}
        # if "debug" not in stream_modes_set:
        #     stream_modes_set.add("debug")

        # graph_id = "dasdsadsad"
        # store = (await api_store.get_store())
        # checkpointer = None if temporary else Checkpointer(conn)

        # 获取或创建Agent
        from kiwi.agents.sql_agent.sql_agent import create_sql_agent

        agent = await agent_manager.get_agent(conv_id, self.db, project_id, agent_factory=create_sql_agent)
        # graph: CompiledStateGraph = get_graph(graph_id, config, store=store, checkpointer=checkpointer)

        # stream_mode="values" makes event_chunk the direct output of a node
        # stream_mode="updates" (default) gives dict like {"node_name": output}
        # Let's use "updates" as it's more common to check node names
        async for event_chunk_update in agent.astream(input, config, stream_mode="update", **kwargs):
            # event_chunk_update will be like {"node_name": output_value}
            for node_name, output_value in event_chunk_update.items():
                if node_name == "call_model" and isinstance(output_value, dict) and "messages" in output_value:
                    last_message = output_value["messages"][-1]
                    if isinstance(last_message, AIMessage):  # Check if it's an AIMessage
                        # Use Pydantic model for consistent serialization if desired
                        # streamed_msg = StreamedChatMessage(**last_message.dict())
                        # yield f"data: {streamed_msg.model_dump_json()}\n\n"
                        # Or simpler, direct dump if AIMessage has model_dump_json
                        if hasattr(last_message, 'model_dump_json'):
                            yield f"data: {last_message.model_dump_json()}\n\n"
                        else:  # Fallback if model_dump_json isn't present or for simpler dicts
                            simple_dict = {"role": getattr(last_message, "role", "assistant"),
                                           "content": getattr(last_message, "content", "")}
                            yield f"data: {json.dumps(simple_dict)}\n\n"

                # You can add handling for other nodes like "tools" if needed
                # elif node_name == "tools":
                #     # output_value here would be the list of ToolMessage objects
                #     # You could stream these too if the frontend needs to know about tool calls/results
                #     if isinstance(output_value, list):
                #         for tool_message in output_value:
                #             if isinstance(tool_message, ToolMessage):
                #                 tool_data = {"role": "tool", "tool_call_id": tool_message.tool_call_id, "content": tool_message.content}
                #                 yield f"data: {json.dumps(tool_data)}\n\n"
                # Pass, ignore other updates, or handle them as needed
                pass

    async def invoke_agent_endpoint(self, message: MessageCreate, project_id: str, generate_chart: bool = False):
        # 获取或创建对话， 并持久化用户消息
        conversation = await self._get_or_create_conversation(
            message.conversation_id, project_id, message.content
        )
        user_message = await ConversationCRUD().create_message(
            self.db, conversation.id, self.user_id, message.content
        )
        await self.db.commit()

        # 调用Agent
        try:
            input_messages = None
            if message.role.lower() == "user":
                input_messages = HumanMessage(id=user_message.id, content=message.content)

            if not input_messages:
                raise HTTPException(status_code=400, detail="No valid user messages provided")

            user_input = {"messages": [input_messages]}

            config = {
                'run_name': 'SQLAgent',
                'tags': ['kiwi', 'SQLAgent', 'agent'],
                "configurable": {
                    "model": "Qwen/Qwen2.5-32B-Instruct",
                    "user_id": self.user_id,
                    "database": self.db,
                    "project_id": project_id,
                    "thread_id": message.conversation_id
                }
            }

            # 获取或创建Agent
            from kiwi.agents.sql_agent.sql_agent import create_sql_agent

            agent = await agent_manager.get_agent(
                message.conversation_id,
                self.db,
                project_id,
                agent_factory=create_sql_agent)

            final_state = await agent.ainvoke(user_input, config=config)
            generated_sql = None
            query_result = None
            response_messages = []
            if final_state and "messages" in final_state:
                for msg in final_state["messages"]:
                    # Convert LangChain messages to Pydantic model or simple dict for response
                    if isinstance(msg, BaseMessage):  # AIMessage, HumanMessage, etc.
                        response_messages.append(MessageResponse(
                            id=getattr(msg, 'id', None),
                            role=getattr(msg, 'type', 'assistant'),  # .type is common for LC messages
                            content=getattr(msg, 'content', ''),
                            name=getattr(msg, 'name', None),
                            tool_calls=getattr(msg, 'tool_calls', None),
                            created_at=datetime.now()
                        ).model_dump(exclude_none=True))
                    # 从tool_calls中提取SQL语句
                    if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
                        for tool_call in msg.tool_calls:
                            if tool_call.get('name') == 'execute_query':
                                # 假设execute_query工具的参数中包含SQL
                                tool_args = tool_call.get('args', {})
                                if 'query' in tool_args:
                                    generated_sql = tool_args['query']

                    if isinstance(msg, ToolMessage) and msg.name == 'execute_query':
                        # 这里可以提取工具执行的结果
                        tool_result = getattr(msg, 'content', None)
                        # 如果工具返回的是查询结果，可以解析它
                        if tool_result and 'Error executing query' not in tool_result:
                            query_result = tool_result
            # Assistant 消息持久化
            # 创建系统消息记录
            chart_content = ""
            chart_config = {}
            if generate_chart:
                chart_config = await self._generate_chart(message.content, query_result, project_id)
                chart_content = self._format_response(query_result, chart_config)

            system_message = await ConversationCRUD().create_message(
                self.db,
                conversation.id,
                self.user_id,
                content=chart_content,
                sql_query=generated_sql,
                raw_data=query_result,
                report_data=chart_config,
                agent_version_id=await self._get_active_agent_version(project_id, "TEXT2SQL")
            )

            return {
                "conversation_id": conversation.id,
                "response": response_messages
            }

        except HTTPException:
            # 不捕获 HTTPException，让它继续向上抛出
            raise
        except Exception as e:
            import traceback
            await logger.aerror(f"Error in /completion/ainvoke: {e}\n{traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

    @staticmethod
    async def _check_message(messages: List[MessageCreate]) -> dict:
        input_messages: List[BaseMessage] = []
        for msg_item in messages:
            if msg_item.role.lower() == "user":
                input_messages.append(HumanMessage(content=msg_item.content))
            # Add elif for "ai", "system", "tool" if your graph expects them in initial input
            else:
                # Fallback or raise error for unsupported roles in initial input
                print(f"Unsupported role in initial message: {msg_item.role}")

        if not input_messages:
            raise HTTPException(status_code=400, detail="No valid user messages provided")

        return {"messages": input_messages}

    async def end_conversation(conversation_id: str):
        """结束对话并销毁Agent"""
        destroyed = await agent_manager.destroy_agent(conversation_id)
        if destroyed:
            print(f"Agent for conversation {conversation_id} has been destroyed")
        else:
            print(f"No agent found for conversation {conversation_id}")

    async def _persist_message(self, message_data: MessageCreate, project_id: str, role: str = "user") -> Any:
        """
        通用消息持久化方法

        Args:
            message: 消息上下文对象

        Returns:
            持久化后的消息对象
        """
        # 可以在这里添加通用的预处理逻辑
        # 如：数据验证、日志记录、权限检查等

        # 获取或创建对话
        conversation = await self._get_or_create_conversation(
            message_data.conversation_id, project_id, message_data.content
        )

        # 创建用户消息记录
        user_message = await ConversationCRUD().create_message(
            self.db, conversation.id, self.user_id, message_data.content
        )

        await self.db.commit()

        # 记录消息持久化操作
        await logger.ainfo(f"Persisting {role} message for conversation {conversation.conversation_id}")
        return conversation.id
