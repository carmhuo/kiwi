from typing import Any, Dict, List, Optional, TypedDict, Union, Annotated, AsyncIterator
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.agents.sql_agent.tools import qa_example_selector
# from kiwi.core.engine.federation_query_engine import get_engine
from kiwi.schemas import QueryResult
from kiwi.agents.sql_agent.utils import load_chat_model
import json
import asyncio

from kiwi.agents.prompts import TEXT2SQL_PROMPT
from kiwi.core.cache import CacheManager
from kiwi.agents.fallback import FallbackStrategy

from kiwi.core.config import logger


class TextToSQLAgent:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.fallback = FallbackStrategy(
            primary_model=config.get("model", "gpt-4"),
            fallback_model=config.get("fallback_model", "gpt-3.5-turbo")
        )




class AgentState(TypedDict):
    messages: Annotated[List[Union[HumanMessage, AIMessage]], lambda x, y: x + y]
    user_query: str
    generated_sql: Optional[str]
    confirmation: Optional[bool]
    intermediate_steps: Annotated[List[dict], lambda x, y: x + y]


class AsyncDuckDBReActAgent:
    def __init__(self, db: AsyncSession, project_id: str):
        self.db = db
        self.project_id = project_id
        self.llm = load_chat_model()
        self.tools = self._setup_tools()
        self.agent = self._create_agent()

    def _setup_tools(self) -> List[Any]:
        """使用@tool装饰器创建工具"""
        return [
            self.list_tables,
            self.get_table_schema,
            self.validate_sql,
            self.execute_sql,
            self.get_sql_examples
        ]

    def _create_agent(self):
        """创建异步react agent"""
        return create_react_agent(
            self.llm,
            self.tools,
            prompt=(
                "You are a helpful assistant that translates natural language to SQL queries "
                "for a federated DuckDB database. Follow these steps:\n"
                "1. Understand the request\n"
                "2. Check available tables if needed\n"
                "3. Examine table schemas if needed\n"
                "4. Generate SQL query\n"
                "5. Validate the query\n"
                "6. Execute after validation\n\n"
                "Always verify your SQL queries before executing them."
            )
        )

    async def astream(self, query: str) -> AsyncIterator[Dict[str, Any]]:
        """异步流式执行"""
        inputs = {"messages": [HumanMessage(content=query)]}
        async for chunk in self.agent.astream(inputs, stream_mode="updates"):
            yield chunk

    async def arun(self, query: str) -> Dict[str, Any]:
        """异步执行到完成"""
        inputs = {"messages": [HumanMessage(content=query)]}
        return await self.agent.ainvoke(inputs)

    # 使用@tool装饰器定义工具
    @tool
    async def list_tables(self, input: str = "") -> str:
        """List all available tables in the federated database"""
        try:
            async with get_engine().get_duckdb_connection() as conn:
                result = await asyncio.to_thread(conn.execute, "SELECT * FROM duckdb_tables()")
                tables = [f"{row[1]}.{row[2]}" for row in result.fetchall()]
                return ", ".join(tables) if tables else "No tables found"
        except Exception as e:
            return f"Error listing tables: {str(e)}"

    @tool
    async def get_table_schema(self, table_name: str) -> str:
        """Get schema and sample data for a specific table. Input should be the table name."""
        try:
            async with FederationQueryEngine.get_duckdb_connection() as conn:
                schema = await asyncio.to_thread(conn.execute, f"DESCRIBE {table_name}")
                schema_info = "\n".join([f"{row[0]}: {row[1]}" for row in schema.fetchall()])

                sample = await asyncio.to_thread(conn.execute, f"SELECT * FROM {table_name} LIMIT 3")
                sample_info = "\n".join([str(row) for row in sample.fetchall()])

                return f"Schema:\n{schema_info}\n\nSample data:\n{sample_info}"
        except Exception as e:
            return f"Error getting schema for table {table_name}: {str(e)}"

    @tool
    async def validate_sql(self, query: str) -> str:
        """Validate if a SQL query is correct before execution. Input should be the SQL query."""
        try:
            explain_result = await FederationQueryEngine.execute_query(
                self.db,
                self.project_id,
                f"EXPLAIN {query}"
            )
            explain_info = "\n".join([str(row) for row in explain_result.rows])
            return f"DuckDB Execution Plan:\n{explain_info}"
        except Exception as e:
            return f"Validation error: {str(e)}"

    @tool
    async def execute_sql(self, query: str) -> Union[str, QueryResult]:
        """Execute a SQL query and return results. Input should be a valid SQL query."""
        try:
            result = await FederationQueryEngine.execute_query(
                self.db,
                self.project_id,
                query
            )

            if len(result.rows) > 10:
                preview = "\n".join([str(row) for row in result.rows[:5]])
                return f"First 5 rows:\n{preview}\n\n... and {len(result.rows) - 5} more rows\n\nExecution time: {result.execution_time:.2f}s"
            return "\n".join([str(row) for row in result.rows])
        except Exception as e:
            return f"Error executing query: {str(e)}"

    @tool
    async def get_sql_examples(self, query: str) -> str:
        """Get examples of natural language questions and their corresponding SQL queries. Input should be the natural language question."""
        examples = await qa_example_selector(query)
        if not examples:
            return "No examples found for this question"

        formatted = []
        for example in examples[:3]:
            if isinstance(example, dict):
                formatted.append(f"Question: {example.get('question', '')}\nSQL: {example.get('sql', '')}")
            elif isinstance(example, str):
                try:
                    ex_data = json.loads(example)
                    formatted.append(f"Question: {ex_data.get('question', '')}\nSQL: {ex_data.get('sql', '')}")
                except:
                    formatted.append(example)

        return "\n\n".join(formatted)


class AsyncInteractiveDuckDBAgent:
    """异步交互式代理"""

    def __init__(self, db: AsyncSession, project_id: str):
        self.agent = AsyncDuckDBReActAgent(db, project_id)

    async def aexecute_interactive(self, query: str) -> AsyncIterator[str]:
        """带确认的异步交互式执行"""
        # 先显示示例
        examples = await self.agent.get_sql_examples(query)
        if examples and "No examples" not in examples:
            yield f"类似示例:\n{examples}\n\n"

        # 流式执行
        sql_to_execute = None
        async for chunk in self.agent.astream(query):
            if "messages" in chunk:
                for msg in chunk["messages"]:
                    if msg["role"] == "assistant" and "content" in msg:
                        yield msg["content"] + "\n"

            if "tool_calls" in chunk:
                for tool_call in chunk["tool_calls"]:
                    if tool_call["name"] == "execute_sql":
                        sql_to_execute = tool_call["args"]["query"]
                        yield f"\n生成的SQL:\n{sql_to_execute}\n"

                        # 在实际应用中，这里应该获取用户确认
                        confirm = True  # 设为False测试取消情况

                        if confirm:
                            result = await self.agent.execute_sql(sql_to_execute)
                            yield f"\n结果:\n{result}\n"
                        else:
                            yield "查询执行已取消\n"

    async def arun_interactive(self, query: str) -> str:
        """带交互的异步执行到完成"""
        full_response = ""
        async for chunk in self.aexecute_interactive(query):
            full_response += chunk
        return full_response