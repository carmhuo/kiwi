"""Define the configurable parameters for the agent."""
import os
from typing import Any, Optional, Literal, Annotated

from pydantic import BaseModel, Field
from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.agents.sql_agent import prompts


class Configuration(BaseModel):
    class Config:
        arbitrary_types_allowed = True

    """The configuration for the agent."""
    user_id: str = Field(description="Unique identifier for the user.")

    project_id: str = Field(description="Unique identifier for the project.")

    dataset_id: str = Field(default=None, description="Unique identifier for the dataset.")

    system_prompt: str = Field(
        default=prompts.SYSTEM_PROMPT,
        description="The system prompt to use for the agent's interactions. "
                    "This prompt sets the context and behavior for the agent."
    )

    model: str = Field(
        default="Qwen/Qwen2.5-32B-Instruct",
        description="The name of the language model to use for the agent's main interactions. "
                    "Should be in the form: provider/model-name.",
    )

    max_search_results: int = Field(
        default=10,
        description="The maximum number of search results to return for each search query."
    )

    database: Annotated[
        AsyncSession, Field(default=..., description="kiwi databases, get datasource from  project or dataset ")]

    # New database configuration fields
    database_path: str = Field(
        default="/mnt/workspace/data/duckdb/gb_vhcl.db",
        description="Filesystem path to the DuckDB database file",
        examples=["/data/analytics.db", ":memory:"]
    )

    read_only: bool = Field(
        default=True,
        description="Whether to open the database in read-only mode"
    )

    @classmethod
    def from_runnable_config(
            cls, config: Optional[RunnableConfig] = None
    ) -> "Configuration":
        """Create a Configuration instance from a RunnableConfig."""
        configurable = (
            config["configurable"] if config and "configurable" in config else {}
        )

        # Get raw values from environment or config
        raw_values: dict[str, Any] = {
            name: os.environ.get(name.upper(), configurable.get(name))
            for name in cls.model_fields.keys()
        }

        # Filter out None values
        values = {k: v for k, v in raw_values.items() if v is not None}

        return cls(**values)


class IndexConfiguration(Configuration):
    """Configuration class for indexing and retrieval operations.

    This class defines the parameters needed for configuring the indexing and
    retrieval processes, including user identification, embedding model selection,
    retriever provider choice, and search parameters.
    """
    embedding_model: str = Field(
        default="openai/text-embedding-3-small",
        metadata={
            "description": "Name of the embedding model to use. Must be a valid embedding model name."
        },
    )

    retriever_provider: Literal[
        "elastic", "elastic-local", "pinecone", "mongodb", "milvus", "chroma", "in-memory"] = Field(
        default="chroma",
        metadata={
            "description": "The vector store provider to use for retrieval. Options are 'elastic', 'pinecone', or 'mongodb'."
        },
    )

    search_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        metadata={
            "description": "Additional keyword arguments to pass to the search function of the retriever."
        },
    )


class RetrievalConfiguration(IndexConfiguration):
    """The configuration for the retrieval agent."""
    retrieval_system_prompt: str = Field(
        default=prompts.RETRIEVAL_SYSTEM_PROMPT,
        metadata={"description": "The retrieval system prompt used for generating responses."},
    )

    retrieval_model: str = Field(
        default="Qwen/Qwen3-32B",
        metadata={
            "description": "The language model used for generating responses. Should be in the form: provider/model-name."
        },
    )

    query_system_prompt: str = Field(
        default=prompts.QUERY_SYSTEM_PROMPT,
        metadata={
            "description": "The system prompt used for processing and refining queries."
        },
    )

    query_model: str = Field(
        default="Qwen/Qwen3-32B",
        metadata={
            "description": "The language model used for processing and refining queries. Should be in the form: provider/model-name."
        },
    )
