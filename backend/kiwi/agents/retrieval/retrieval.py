"""Manage the configuration of various retrievers.

This module provides functionality to create and manage retrievers for different
vector store backends, specifically Elasticsearch, Pinecone, and MongoDB.

The retrievers support filtering results by user_id to ensure data isolation between users.
"""

import os
from contextlib import contextmanager
from typing import Generator

from langchain_core.embeddings import Embeddings
from langchain_core.runnables import RunnableConfig
from langchain_core.vectorstores import VectorStoreRetriever

from kiwi.react_agent.configuration import Configuration, IndexConfiguration


## Encoder constructors


def make_text_encoder(model: str) -> Embeddings:
    """Connect to the configured text encoder."""
    provider, model = model.split("/", maxsplit=1)
    match provider:
        case "openai":
            from langchain_openai import OpenAIEmbeddings

            return OpenAIEmbeddings(model=model)
        # case "cohere":
        #     from langchain_cohere import CohereEmbeddings
        #
        #     return CohereEmbeddings(model=model)  # type: ignore
        case "default":
            from kiwi.embedding.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2
            return ONNXMiniLM_L6_V2()
        case _:
            raise ValueError(f"Unsupported embedding provider: {provider}")

## Retriever constructors


@contextmanager
def make_elastic_retriever(
        configuration: IndexConfiguration, embedding_model: Embeddings
) -> Generator[VectorStoreRetriever, None, None]:
    """Configure this agent to connect to a specific elastic index."""
    from langchain_elasticsearch import ElasticsearchStore

    connection_options = {}
    if configuration.retriever_provider == "elastic-local":
        connection_options = {
            "es_user": os.environ["ELASTICSEARCH_USER"],
            "es_password": os.environ["ELASTICSEARCH_PASSWORD"],
        }

    else:
        connection_options = {"es_api_key": os.environ["ELASTICSEARCH_API_KEY"]}

    vstore = ElasticsearchStore(
        **connection_options,  # type: ignore
        es_url=os.environ["ELASTICSEARCH_URL"],
        index_name="langchain_index",
        embedding=embedding_model,
    )

    search_kwargs = configuration.search_kwargs

    search_filter = search_kwargs.setdefault("filter", [])
    search_filter.append({"term": {"metadata.user_id": configuration.user_id}})
    yield vstore.as_retriever(search_kwargs=search_kwargs)


@contextmanager
def make_pinecone_retriever(
        configuration: IndexConfiguration, embedding_model: Embeddings
) -> Generator[VectorStoreRetriever, None, None]:
    """Configure this agent to connect to a specific pinecone index."""
    from langchain_pinecone import PineconeVectorStore

    search_kwargs = configuration.search_kwargs

    search_filter = search_kwargs.setdefault("filter", {})
    search_filter.update({"user_id": configuration.user_id})
    vstore = PineconeVectorStore.from_existing_index(
        os.environ["PINECONE_INDEX_NAME"], embedding=embedding_model
    )
    yield vstore.as_retriever(search_kwargs=search_kwargs)


@contextmanager
def make_mongodb_retriever(
        configuration: IndexConfiguration, embedding_model: Embeddings
) -> Generator[VectorStoreRetriever, None, None]:
    """Configure this agent to connect to a specific MongoDB Atlas index & namespaces."""
    from langchain_mongodb.vectorstores import MongoDBAtlasVectorSearch

    vstore = MongoDBAtlasVectorSearch.from_connection_string(
        os.environ["MONGODB_URI"],
        namespace="langgraph_retrieval_agent.default",
        embedding=embedding_model,
    )
    search_kwargs = configuration.search_kwargs
    pre_filter = search_kwargs.setdefault("pre_filter", {})
    pre_filter["user_id"] = {"$eq": configuration.user_id}
    yield vstore.as_retriever(search_kwargs=search_kwargs)


@contextmanager
def make_milvus_retriever(
        configuration: IndexConfiguration, embedding_model: Embeddings
) -> Generator[VectorStoreRetriever, None, None]:
    """Configure this agent to connect to in memory index."""
    from langchain_milvus import Milvus
    user_id = configuration.user_id
    # 创建 vector store
    vstore = Milvus(
        embedding_function=embedding_model,
        collection_name=f"{user_id}_userspace",
        connection_args={"uri": os.environ["MILVUS_DB_URI"]},
        index_params={"index_type": "FLAT", "metric_type": "L2"},
    )

    search_kwargs = configuration.search_kwargs
    yield vstore.as_retriever(search_kwargs=search_kwargs)


@contextmanager
def make_chroma_retriever(
        configuration: IndexConfiguration, embedding_model: Embeddings
) -> Generator[VectorStoreRetriever, None, None]:
    """Configure this agent to connect to chroma index."""
    from langchain_chroma import Chroma
    user_id = configuration.user_id
    # Where to save data locally, remove if not necessary
    persist_dir = os.environ.get("CHROMA_DB_PATH", "./chroma_langchain_db")

    import chromadb
    chroma_client = chromadb.PersistentClient(path=persist_dir)

    vector_store = Chroma(
        collection_name=f"{user_id}_userspace_query_examples",
        embedding_function=embedding_model,
        persist_directory=persist_dir,  # Where to save data locally, remove if not necessary
        client=chroma_client
    )

    search_kwargs = configuration.search_kwargs
    yield vector_store.as_retriever(search_kwargs=search_kwargs)


@contextmanager
def make_in_memory_retriever(
        configuration: IndexConfiguration, embedding_model: Embeddings
) -> Generator[VectorStoreRetriever, None, None]:
    """Configure this agent to connect to in memory index."""
    from langchain_core.vectorstores import InMemoryVectorStore
    vstore = InMemoryVectorStore(embedding_model)
    search_kwargs = configuration.search_kwargs
    yield vstore.as_retriever(search_kwargs=search_kwargs)

@contextmanager
def make_retriever(
        config: RunnableConfig,
) -> Generator[VectorStoreRetriever, None, None]:
    """Create a retriever for the agent, based on the current configuration."""
    configuration = IndexConfiguration.from_runnable_config(config)
    embedding_model = make_text_encoder(configuration.embedding_model)
    user_id = configuration.user_id
    if not user_id:
        raise ValueError("Please provide a valid user_id in the configuration.")
    match configuration.retriever_provider:
        case "elastic" | "elastic-local":
            with make_elastic_retriever(configuration, embedding_model) as retriever:
                yield retriever

        case "pinecone":
            with make_pinecone_retriever(configuration, embedding_model) as retriever:
                yield retriever

        case "mongodb":
            with make_mongodb_retriever(configuration, embedding_model) as retriever:
                yield retriever
        case "milvus" | "milvus-lite":
            with make_milvus_retriever(configuration, embedding_model) as retriever:
                yield retriever
        case "chroma":
            with make_chroma_retriever(configuration, embedding_model) as retriever:
                yield retriever
        case "in-memory":
            with make_in_memory_retriever(configuration, embedding_model) as retriever:
                yield retriever
        case _:
            raise ValueError(
                "Unrecognized retriever_provider in configuration. "
                f"Expected one of: {', '.join(Configuration.__annotations__['retriever_provider'].__args__)}\n"
                f"Got: {configuration.retriever_provider}"
            )
