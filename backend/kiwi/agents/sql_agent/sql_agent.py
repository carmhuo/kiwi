from typing import Dict, List, Literal, cast, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.store.base import BaseStore
from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.agents.sql_agent.configuration import Configuration
from kiwi.agents.sql_agent.state import InputState, State
from kiwi.agents.sql_agent.utils import load_chat_model, get_current_time
from kiwi.agents.sql_agent.tools import ToolKits
from kiwi.core.engine.federation_query_engine import get_engine

query_engine = get_engine()

"""Define a custom Reasoning and Action agent.

Works with a chat model with tool calling support.
"""


async def retrieve(
        state: State, *, config: RunnableConfig
) -> dict[str, list[Document]]:
    """Retrieve documents based on the latest query in the state.

    This function takes the current state and configuration, uses the latest query
    from the state to retrieve relevant documents using the retriever, and returns
    the retrieved documents.

    Args:
        state (State): The current state containing queries and the retriever.
        config (RunnableConfig | None, optional): Configuration for the retrieval process.

    Returns:
        dict[str, list[Document]]: A dictionary with a single key "retrieved_docs"
        containing a list of retrieved Document objects.
    """
    # TODO: 实现文档检索逻辑
    return {"retrieved_docs": []}


async def call_model(state: State, config: RunnableConfig) -> Dict[str, List[AIMessage]]:
    """Call the LLM powering our "agent".

    This function prepares the prompt, initializes the model, and processes the response.

    Args:
        state (State): The current state of the conversation.
        config (RunnableConfig): Configuration for the model run.

    Returns:
        dict: A dictionary containing the model's response message.
    """
    config = Configuration.from_runnable_config(config)

    tool_kits = ToolKits(config.database, config.project_id, query_engine)
    # tools = await tool_manager.tools if hasattr(tool_manager.tools, '__await__') else tool_manager.tools
    # Initialize the model with tool binding. Change the model or add more tools here.
    model = load_chat_model(config.model).bind_tools(tool_kits.tools)

    dialect = "DuckDB"
    top_k = 10

    # Format the system prompt. Customize this to change the agent's behavior.
    system_message = config.system_prompt.format(
        dialect=dialect,
        top_k=top_k,
        system_time=get_current_time
    )
    try:
        # Get the model's response
        response = cast(
            AIMessage,
            await model.ainvoke(
                [{"role": "system", "content": system_message}, *state.messages],
                extra_body={"enable_thinking": False}
            ),
        )
    except Exception as e:
        return {
            "messages": [
                AIMessage(
                    id=state.messages[-1].id,
                    content=f"Sorry, Failed to generate a response. Error: {str(e)}",
                )
            ]
        }

    # Handle the case when it's the last step and the model still wants to use a tool
    if state.is_last_step and response.tool_calls:
        return {
            "messages": [
                AIMessage(
                    id=response.id,
                    content="Sorry, I could not find an answer to your question in the specified number of steps.",
                )
            ]
        }

    # Return the model's response as a list to be added to existing messages
    return {"messages": [response]}


# tools_by_name = {tool.name: tool for tool in tools}
# async def tool_node(state: dict):
#     """Performs the tool call"""
#
#     result = []
#     for tool_call in state["messages"][-1].tool_calls:
#         tool = tools_by_name[tool_call["name"]]
#         observation = tool.invoke(tool_call["args"])
#         result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"]))
#     return {"messages": result}

def should_continue(state: State) -> Literal["__end__", "tools"]:
    """Determine the next node based on the model's output.

    This function checks if the model's last message contains tool calls.

    Args:
        state (State): The current state of the conversation.

    Returns:
        str: The name of the next node to call ("__end__" or "tools").
    """
    last_message = state.messages[-1]
    if not isinstance(last_message, AIMessage):
        raise ValueError(
            f"Expected AIMessage in output edges, but got {type(last_message).__name__}"
        )
    # If there is no tool call, then we finish
    if not last_message.tool_calls:
        return "__end__"
    # Otherwise we execute the requested actions
    return "tools"


async def create_sql_agent(
        db: AsyncSession,
        project_id: str,
        checkpoint_saver: Optional[BaseCheckpointSaver] = None
) -> CompiledStateGraph:
    """Create a ReAct agent with DuckDB federation support"""
    builder = StateGraph(State, input=InputState, config_schema=Configuration)

    tool_kits = ToolKits(db, project_id, query_engine)

    # Add nodes
    builder.add_node("call_model", call_model)

    # tools = await tool_manager.tools if hasattr(tool_manager.tools, '__await__') else tool_manager.tools
    builder.add_node("tools", ToolNode(tool_kits.tools))

    # Set edges
    builder.add_edge("__start__", "call_model")
    builder.add_conditional_edges("call_model", should_continue, ["tools", "__end__"])
    builder.add_edge("tools", "call_model")
    # Compile the agent
    agent = builder.compile(checkpointer=checkpoint_saver, name="SQLAgent")
    return agent
