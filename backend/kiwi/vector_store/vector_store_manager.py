import asyncio
from functools import lru_cache
from typing import Dict, Any

from kiwi.vector_store.base import VectorStore
from kiwi.vector_store.chromadb_vector import ChromadbVectorStore

# 全局唯一的VectorStore实例
_vector_store_instance = None
_init_lock = asyncio.Lock()
_is_initialized = False


# @lru_cache(maxsize=1)
async def get_vector_store(store_type: str = "chromadb", config: Dict[str, Any] = None) -> VectorStore:
    """
    获取全局唯一的VectorStore实例
    使用lru_cache确保全局只有一个实例

    Args:
        store_type: 向量存储类型，目前支持"chromadb"
        config: 向量存储配置字典

    Returns:
        VectorStore: 初始化好的向量存储实例
    """
    global _vector_store_instance, _is_initialized

    if _is_initialized and _vector_store_instance is not None:
        return _vector_store_instance

    async with _init_lock:  # 防止并发重复初始化
        # 再次检查，防止在等待锁时其他协程已经完成初始化
        if _is_initialized and _vector_store_instance is not None:
            return _vector_store_instance

        config = config or {}

        if store_type == "chromadb":
            # 假设ChromadbVectorStore有异步初始化方法
            _vector_store_instance = await ChromadbVectorStore.create_async(config)
        elif store_type == "milvus":
            raise NotImplementedError("Milvus is not supported yet.")
        else:
            raise ValueError(f"Unsupported vector store type: {store_type}")
        _is_initialized = True
        return _vector_store_instance


async def init_vector_store(store_type: str = "chromadb", config: Dict[str, Any] = None) -> VectorStore:
    """
    应用启动时初始化向量存储

    Args:
        store_type: 向量存储类型
        config: 向量存储配置

    Returns:
        VectorStore: 初始化好的向量存储实例
    """
    # 将字典转换为可哈希的元组
    return await get_vector_store(store_type, config)


async def close_vector_store():
    """
    关闭并清理向量存储实例
    """
    global _vector_store_instance, _is_initialized

    if _vector_store_instance is not None:
        if hasattr(_vector_store_instance, 'aclose'):
            await _vector_store_instance.aclose()
        elif hasattr(_vector_store_instance, 'close'):
            await asyncio.to_thread(_vector_store_instance.close)

        _vector_store_instance = None
        _is_initialized = False