"""Define the state structures for the agent."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Sequence, Union, Optional, Any, Literal

from langchain_core.documents import Document
from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages
from langgraph.managed import IsLastStep
from typing_extensions import Annotated

############################  Doc Indexing State  #############################


def reduce_docs(
    existing: Optional[Sequence[Document]],
    new: Union[
        Sequence[Document],
        Sequence[dict[str, Any]],
        Sequence[str],
        str,
        Literal["delete"],
    ],
) -> Sequence[Document]:
    """Reduce and process documents based on the input type.

    This function handles various input types and converts them into a sequence of Document objects.
    It can delete existing documents, create new ones from strings or dictionaries, or return the existing documents.

    Args:
        existing (Optional[Sequence[Document]]): The existing docs in the state, if any.
        new (Union[Sequence[Document], Sequence[dict[str, Any]], Sequence[str], str, Literal["delete"]]):
            The new input to process. Can be a sequence of Documents, dictionaries, strings, a single string,
            or the literal "delete".
    """
    if new == "delete":
        return []
    if isinstance(new, str):
        return [Document(page_content=new, metadata={"id": str(uuid.uuid4())})]
    if isinstance(new, list):
        coerced = []
        for item in new:
            if isinstance(item, str):
                coerced.append(
                    Document(page_content=item, metadata={"id": str(uuid.uuid4())})
                )
            elif isinstance(item, dict):
                coerced.append(Document(**item))
            else:
                coerced.append(item)
        return coerced
    return existing or []


# The index state defines the simple IO for the single-node index graph
@dataclass(kw_only=True)
class IndexState:
    """Represents the state for document indexing and retrieval.

    This class defines the structure of the index state, which includes
    the documents to be indexed and the retriever used for searching
    these documents.
    """

    docs: Annotated[Sequence[Document], reduce_docs]
    """A nlist of documents that the agent ca index."""


#############################  Agent State  ###################################


@dataclass
class InputState:
    """Defines the input state for the agent, representing a narrower interface to the outside world.

    This class is used to define the initial state and structure of incoming data.
    """

    messages: Annotated[Sequence[AnyMessage], add_messages] = field(
        default_factory=list
    )
    """
    Messages tracking the primary execution state of the agent.

    Typically accumulates a pattern of:
    1. HumanMessage - user input
    2. AIMessage with .tool_calls - agent picking tool(s) to use to collect information
    3. ToolMessage(s) - the responses (or errors) from the executed tools
    4. AIMessage without .tool_calls - agent responding in unstructured format to the user
    5. HumanMessage - user responds with the next conversational turn

    Steps 2-5 may repeat as needed.

    The `add_messages` annotation ensures that new messages are merged with existing ones,
    updating by ID to maintain an "append-only" state unless a message with the same ID is provided.
    """


@dataclass
class State(InputState):
    """Represents the complete state of the agent, extending InputState with additional attributes.

    This class can be used to store any information needed throughout the agent's lifecycle.
    """

    is_last_step: IsLastStep = field(default=False)
    """
    Indicates whether the current step is the last one before the graph raises an error.

    This is a 'managed' variable, controlled by the state machine rather than user code.
    It is set to 'True' when the step count reaches recursion_limit - 1.
    """

    retrieved_docs: list[Document] = field(default_factory=list)
    """Populated by the retriever. This is a list of documents that the agent can reference."""

    # Additional attributes can be added here as needed.
    # Common examples include:
    # retrieved_documents: List[Document] = field(default_factory=list)
    # extracted_entities: Dict[str, Any] = field(default_factory=dict)
    # api_connections: Dict[str, Any] = field(default_factory=dict)


#############################  Retrieval State  ###################################


def add_queries(existing: Sequence[str], new: Sequence[str]) -> Sequence[str]:
    """Combine existing queries with new queries.

    Args:
        existing (Sequence[str]): The current list of queries in the state.
        new (Sequence[str]): The new queries to be added.

    Returns:
        Sequence[str]: A new list containing all queries from both input sequences.
    """
    return list(existing) + list(new)


@dataclass(kw_only=True)
class RetrievalState(InputState):
    """The state of your graph / agent."""

    queries: Annotated[list[str], add_queries] = field(default_factory=list)
    """A list of search queries that the agent has generated."""

    retrieved_docs: list[Document] = field(default_factory=list)
    """Populated by the retriever. This is a list of documents that the agent can reference."""

    # Feel free to add additional attributes to your state as needed.
    # Common examples include retrieved documents, extracted entities, API connections, etc.