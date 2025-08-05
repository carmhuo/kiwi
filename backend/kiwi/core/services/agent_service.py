import json
from datetime import datetime
from typing import Any, Dict, AsyncGenerator, Optional, List

from langchain_core.messages import HumanMessage, BaseMessage, AIMessage, ToolMessage, ToolCall
from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.agents import agent_manager
from kiwi.core.config import logger
from kiwi.core.exceptions import AgentProcessingError
from kiwi.schemas import MessageCreate, MessageResponse


class AgentService:
    """Handles interactions with AI agents"""

    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id

    async def invoke_agent(
            self,
            message: MessageCreate,
            project_id: str,
            generate_chart: bool = False
    ) -> Dict[str, Any]:
        """Invoke agent for synchronous processing"""
        # conversation_id = await self.message_service.persist_user_message(message, project_id)
        conv_id = message.conversation_id
        try:
            config = self._create_agent_config(project_id, conv_id)

            agent = await self._get_sql_agent(conv_id, project_id)

            input_message = HumanMessage(content=message.content)

            final_state = await agent.ainvoke(
                {"messages": [input_message]},
                config=config
            )

            temp_messages = []
            generated_sql = None
            raw_data = None
            final_content = None

            if final_state and "messages" in final_state:
                for msg in final_state["messages"]:
                    if isinstance(msg, BaseMessage):
                        temp_messages.append(self._create_message_response(msg))

                        if isinstance(msg, AIMessage):
                            final_content = msg.content

                    if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls'):
                        generated_sql = self._extract_sql_from_tool_calls(msg.tool_calls)

                    if isinstance(msg, ToolMessage) and msg.name == 'execute_query':
                        raw_data = msg.content
            await logger.adebug(f"ReAct Processing: \n{temp_messages}\n")
            return {
                "conversation_id": conv_id,
                "generated_sql": generated_sql,
                "raw_data": raw_data,
                "content": final_content
            }
        except Exception as e:
            await logger.aerror(f"Agent invocation failed: {str(e)}")
            raise AgentProcessingError(f"Agent processing failed: {str(e)}") from e

    async def stream_agent_events(
            self,
            message: MessageCreate,
            project_id: str,
            generate_chart: bool = False,
            on_complete: Optional[callable] = None
    ) -> AsyncGenerator[str, None]:
        """Stream agent events for asynchronous processing"""

        conv_id = message.conversation_id
        try:
            config = self._create_agent_config(project_id, conv_id)

            agent = await self._get_sql_agent(conv_id, project_id)

            input_message = HumanMessage(content=message.content)

            generated_sql = None
            query_result = None
            final_content = None

            async for event_chunk in agent.astream({"messages": [input_message]}, config=config, stream_mode="updates"):
                for node_name, output_value in event_chunk.items():
                    if node_name == "call_model" and isinstance(output_value, dict) and "messages" in output_value:
                        last_message = output_value["messages"][-1]
                        if isinstance(last_message, AIMessage):
                            # 获取SQL语句
                            if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                                generated_sql = self._extract_sql_from_tool_calls(last_message.tool_calls)

                            yield self._format_stream_message(last_message)
                            final_content = last_message.content

                    # You can add handling for other nodes like "tools" if needed
                    elif node_name == "tools":
                        # output_value here would be the list of ToolMessage objects
                        # You could stream these too if the frontend needs to know about tool calls/results
                        if isinstance(output_value, list):
                            for tool_message in output_value:
                                if isinstance(tool_message, ToolMessage) and tool_message.name == 'execute_query':
                                    # 这里可以提取工具执行的结果
                                    tool_result = getattr(tool_message, 'content', None)
                                    # 如果工具返回的是查询结果，可以解析它
                                    if tool_result and 'Error executing query' not in tool_result:
                                        query_result = tool_result
                    # Pass, ignore other updates, or handle them as needed
                    pass

            if on_complete:
                final_result = await on_complete({
                    "conversation_id": conv_id,
                    "user_query": message.content,
                    "generated_sql": generated_sql,
                    "raw_data": query_result,
                    "content": final_content
                })
                yield f"data: {final_result}\n\n"
        except Exception as e:
            yield self._create_error_event(e)
            await logger.aerror(f"Agent streaming failed: {e}")
            raise AgentProcessingError(f"Agent streaming failed: {str(e)}") from e

    async def _get_sql_agent(self, conversation_id: str, project_id: str):
        """Get or create SQL agent"""
        from kiwi.agents.sql_agent.sql_agent import create_sql_agent
        return await agent_manager.get_agent(
            conversation_id,
            self.db,
            project_id,
            agent_factory=create_sql_agent
        )

    def _create_agent_config(self, project_id: str, conversation_id: str) -> Dict[str, Any]:
        """Create agent configuration"""
        return {
            'run_name': 'SQLAgent',
            'tags': ['kiwi', 'sql agent', 'graph'],
            "configurable": {
                "user_id": self.user_id,
                "database": self.db,
                "project_id": project_id,
                "thread_id": conversation_id
            }
        }


    def _process_stream_event(self, event_chunk: Dict[str, Any]) -> str:
        """Process streaming event chunk"""
        for node_name, output_value in event_chunk.items():
            if node_name == "call_model" and isinstance(output_value, dict):
                last_message = output_value.get("messages", [])[-1]
                if isinstance(last_message, AIMessage):
                    return self._format_stream_message(last_message)
        return ""

    async def _process_final_results(
            self,
            message: MessageCreate,
            conversation_id: str,
            project_id: str,
            generate_chart: bool
    ):
        """Process final results after streaming completes"""
        if generate_chart:
            # In a real implementation, you would need to capture
            # the final SQL and results during streaming
            await self._persist_system_message(
                conversation_id,
                project_id,
                message.content,
                None,  # Would be actual SQL in real implementation
                None  # Would be actual results in real implementation
            )


    def _create_message_response(self, message: BaseMessage) -> Dict[str, Any]:
        """Create message response from BaseMessage"""
        return MessageResponse(
            id=getattr(message, 'id', None),
            role=getattr(message, 'type', 'assistant'),
            content=getattr(message, 'content', ''),
            name=getattr(message, 'name', None),
            tool_calls=getattr(message, 'tool_calls', None),
            created_at=datetime.now()
        ).model_dump(exclude_none=True)

    def _extract_sql_from_tool_calls(self, tool_calls: List[ToolCall]) -> Optional[str]:
        """Extract SQL query from tool calls"""
        for tool_call in tool_calls or []:
            if tool_call.get('name') == 'execute_query':
                tool_args = tool_call.get('args', {})
                if 'query' in tool_args:
                    return tool_args['query']
        return None

    def _format_stream_message(self, message: AIMessage) -> str:
        """Format streaming message for SSE"""
        if hasattr(message, 'model_dump_json'):
            return f"data: {message.model_dump_json()}\n\n"
        else:
            simple_dict = {
                "role": getattr(message, "role", "assistant"),
                "content": getattr(message, "content", "")
            }
            return f"data: {json.dumps(simple_dict)}\n\n"

    def _create_error_event(self, error: Exception) -> str:
        """Create error event for SSE"""
        error_data = {
            "role": "system",
            "content": f"Error: {str(error)}",
            "error": True
        }
        return f"data: {json.dumps(error_data)}\n\n"
