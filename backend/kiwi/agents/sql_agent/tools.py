"""This module provides example tools for web scraping and search functionality.

It includes a basic Tavily search function (as an example)

These tools are intended as free examples to get started. For production use,
consider implementing more robust and specialized tools tailored to your needs.
"""
import asyncio
import json
import threading
import uuid
from functools import lru_cache
from typing import Any, Callable, List, Union, Sequence, Dict, Annotated, Optional, Tuple

from duckdb.duckdb import DatabaseError
from kiwi.agents.sql_agent.prompts import QUERY_DOUBLE_CHECKER
from langchain_core.prompts import PromptTemplate
from sqlalchemy.ext.asyncio import AsyncSession

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from langgraph.store.base import BaseStore

from kiwi.agents.sql_agent.configuration import Configuration
from kiwi.agents.sql_agent.utils import load_chat_model
from kiwi.schemas import QueryResult
from kiwi.core.config import logger


async def upsert_memory(
        content: str,
        context: str,
        *,
        memory_id: Optional[uuid.UUID] = None,
        # Hide these arguments from the model.
        config: Annotated[RunnableConfig, InjectedToolArg],
        store: Annotated[BaseStore, InjectedToolArg],
):
    """Upsert a memory in the database.

    If a memory conflicts with an existing one, then just UPDATE the
    existing one by passing in memory_id - don't create two memories
    that are the same. If the user corrects a memory, UPDATE it.

    Args:
        content: The main content of the memory. For example:
            "User expressed interest in learning about French."
        context: Additional context for the memory. For example:
            "This was mentioned while discussing career options in Europe."
        memory_id: ONLY PROVIDE IF UPDATING AN EXISTING MEMORY.
        The memory to overwrite.
    """
    mem_id = memory_id or uuid.uuid4()
    user_id = Configuration.from_runnable_config(config).user_id
    await store.aput(
        ("memories", user_id),
        key=str(mem_id),
        value={"content": content, "context": context},
    )
    return f"Stored memory {mem_id}"


async def qa_example_selector(query: str, config: Annotated[RunnableConfig, InjectedToolArg]) -> Union[
    str, Sequence[Dict[str, Any]]]:
    """Get some examples of natural language problems and corresponding SQL query.

    Input is a user question, output is a comma-separated list of QUERY-SQL pairs.

    Args:
        query: str type, natural language questions.

    Returns:
        list[dict]: The extracted documents, or an empty list or single document if an error occurred.

    Examples:
        [{'question': 'List all artists.', 'sql': 'SELECT * FROM Artist;'},
         {'question': 'How many employees are there','sql': 'SELECT COUNT(*) FROM "Employee"'},
         {'question': 'How many tracks are there in the album with ID 5?',
          'sql': 'SELECT COUNT(*) FROM Track WHERE AlbumId = 5;'}
        ]
    """
    import chromadb
    configuration = Configuration.from_runnable_config()
    # import chromadb
    client = await chromadb.AsyncHttpClient(host='localhost', port=8000)
    collection = await client.get_or_create_collection(name="query_sql")
    query_results = await collection.query(query_texts=[query], n_results=5)
    if query_results is None:
        return []

    if "documents" in query_results:
        documents = query_results["documents"]
        if len(documents) == 1 and isinstance(documents[0], list):
            try:
                documents = [json.loads(doc) for doc in documents[0]]
            except Exception as e:
                return []

        return documents


class ExampleSelector:
    """Enhanced example selector with caching and fallback"""

    def __init__(self, chroma_host: str = "localhost", chroma_port: int = 8000):
        import chromadb
        self.client = chromadb.AsyncHttpClient(host=chroma_host, port=chroma_port)
        self._cache = {}
        self._cache_ttl = 3600  # 1 hour

    @lru_cache(maxsize=100)
    async def get_examples(self, query: str, n_results: int = 5) -> List[Dict]:
        """Get cached examples with fallback"""
        try:
            if query in self._cache:
                return self._cache[query]

            collection = await self.client.get_or_create_collection(name="query_sql_pairs")
            results = await collection.query(query_texts=[query], n_results=n_results)

            if not results or "documents" not in results:
                return self._get_fallback_examples()

            examples = self._parse_results(results["documents"])
            self._cache[query] = examples
            return examples
        except Exception as e:
            logger.warning(f"Example query failed: {e}")
            return self._get_fallback_examples()

    def _parse_results(self, documents: List) -> List[Dict]:
        """Parse chromaDB documents into examples"""
        try:
            if len(documents) == 1 and isinstance(documents[0], list):
                return [json.loads(doc) for doc in documents[0]]
            return documents
        except json.JSONDecodeError:
            return self._get_fallback_examples()

    def _get_fallback_examples(self) -> List[Dict]:
        """Default examples when query fails"""
        return [
            {"question": "List all artists", "sql": "SELECT * FROM Artist;"},
            {"question": "Count employees", "sql": "SELECT COUNT(*) FROM Employee;"}
        ]


class ToolKits:
    """集中管理工具，避免重复创建"""

    def __init__(self, db: AsyncSession, project_id: str, query_engine):
        self.db = db
        self.project_id = project_id
        self.query_engine = query_engine
        self._tools: Optional[List[Callable]] = None
        self._lock = threading.Lock()

    @property
    def tools(self) -> List[Callable]:
        if self._tools is None:
            with self._lock:
                if self._tools is None:
                    duckdb_tools = DatabaseTools(self.db, self.project_id, self.query_engine)
                    self._tools = [
                        duckdb_tools.list_tables,
                        duckdb_tools.get_table_schema,
                        duckdb_tools.sql_query_checker,
                        duckdb_tools.execute_query
                    ]
        return self._tools


class DatabaseTools:
    """Tools for interacting with federated DuckDB databases"""

    MAX_PREVIEW_ROWS = 5
    MAX_FULL_RESULTS = 10000

    def __init__(self, db: AsyncSession, project_id: str, query_engine):
        self.db = db
        self.project_id = project_id
        self.query_engine = query_engine
        self._query_timeout = 60  # seconds

    async def list_tables(self) -> str:
        """Get a comma-separated list of table names.

        Input is an empty string, output is a comma-separated list of tables in the database.
        Examples output: db1.table1, db1.table2, db2.table1
        """
        try:
            return await self.query_engine.list_tables(self.db, project_id=self.project_id)
        except Exception as e:
            await logger.aerror(f"Table listing failed: {e}")
            return f"Error listing tables: {str(e)}"

    async def get_table_schema(self, table_names: str) -> str:
        """Get the schema for tables in a comma-separated list.

        Input to this tool is a comma-separated list of tables, output is the schema and sample rows for those tables.
        Be sure that the tables actually exist by calling `list_tables` first! "

        Args:
            table_names (str): a comma-separated list of tables, example Input: db1.table1, db1.table2, db2.table1
        """
        full_table_names = [t.strip() for t in table_names.split(",") if t.strip()]
        if not full_table_names:
            return "Error: No valid table names provided"
        return await self.query_engine.get_table_info(
            self.db,
            project_id=self.project_id,
            full_table_names=full_table_names
        )

    async def sql_query_checker(self, query: str) -> str:
        """Use the LLM to check the query.

        Use this tool to double-check if your query is correct before executing it.
        Always use this tool before executing a query with `execute_query`!
        """
        # 对查询进行基本的SQL注入防护
        if not query or not isinstance(query, str):
            return "Validation error: Invalid query input"

        await logger.adebug(f"Validating SQL query: {query[:100]}...")
        try:
            # return db.explain(query)
            prompt = PromptTemplate(
                template=QUERY_DOUBLE_CHECKER,
                input_variables=["dialect", "query"]
            )

            llm = load_chat_model()

            chain = prompt | llm

            response = await chain.ainvoke({
                "query": query,
                "dialect": "DuckDB"
            })

            if hasattr(response, "content"):
                return str(response.content)
            else:
                return str(response)
        except Exception as e:
            await logger.aerror(f"SQL validation failed for query: {query[:100]}... Error: {str(e)}")
            return f"SQL validation failed: {str(e)}"

    async def validate_sql(self, query: str) -> str:
        """Validate if a SQL query is correct before execution

        This function validates a SQL query by executing an EXPLAIN statement
        against it to check for syntax and semantic correctness without actually
        running the query. It returns the SQL query string if valid, or an error
        message if invalid.

        Args:
            query (str): The SQL query string to validate

        Returns:
            str: Either sql query if validation succeeds, or
                 sql query string with an error message describing what went wrong during validation
        """
        try:
            # 对查询进行基本的SQL注入防护
            if not query or not isinstance(query, str):
                return "Validation error: Invalid query input"

            # Basic check for dangerous statements
            forbidden_keywords = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "GRANT"]
            if any(keyword in query.upper() for keyword in forbidden_keywords):
                return "Validation error: Query contains forbidden operation"

            await self.query_engine.execute_query(
                self.db,
                self.project_id,
                f"EXPLAIN {query}"
            )
            # explain_info = "\n".join([str(row) for row in explain_result.rows])
            return f"SQL validation successful :\n{query}"
        except Exception as e:
            return f"sql\n{query}\nValidation error: {str(e)}"

    async def execute_query(self, query: str) -> Union[str, List[Tuple[Any]]]:
        """Execute the query, return the results or an error message.

        Input to this tool is a detailed and correct SQL query, output is a
        result from the database. If the query is not correct, an error message
        will be returned. If an error is returned, rewrite the query, check the
        query, and try again. If you encounter an issue with Unknown column
        'xxxx' in 'field list', use `get_table_schema` to query the correct table fields.

        Args:
            query (str): 要执行的SQL查询语句，必须是详细且正确的SQL查询

        Return:
            Union[str, List[Tuple[Any]]]:
                - 如果查询成功且结果行数不超过10行，返回所有行的字符串表示
                - 如果查询成功且结果行数超过10行，返回前5行预览及总行数信息
                - 如果执行超时，返回超时错误信息
                - 如果数据库错误，返回数据库错误信息
                - 如果其他异常，返回通用错误信息

        """
        try:
            result = await self._safe_execute(query)

            if not result.rows:
                return ""

            return str(result.rows)

        except Exception as e:
            return f"Error executing query: {e}"

    async def _safe_execute(self, query: str, is_explain: bool = False) -> QueryResult:
        """Safe execute helper with timeout"""
        try:
            if is_explain:
                query = f"EXPLAIN {query}"

            result = await self.query_engine.execute_query(
                self.db,
                self.project_id,
                query
            )
            return result
        except asyncio.TimeoutError:
            raise TimeoutError("Query execution timed out")
        except DatabaseError as e:
            raise ValueError(f"Database error: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"Query execution failed: {str(e)}")
