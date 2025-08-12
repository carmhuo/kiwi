from abc import ABC, abstractmethod
from typing import Any, Optional
import uuid
import json
from kiwi.core.config import settings

"""
CacheManager 类提供了一个静态方法来创建和配置缓存实例。它根据设置选择合适的缓存类型，并通过代理添加启用/禁用缓存的功能。
方法：get_cache()
获取全局唯一的缓存实例（单例模式）。

    根据 `settings.CACHE_TYPE` 的值选择缓存类型：
    - 如果是 "memory"，则创建一个 MemoryCache 实例。
    - 如果是 "redis"，则创建一个 RedisCache 实例。
    - 如果是不支持的类型，则抛出 ValueError 异常。

    最后，使用 CacheProxy 包装基础缓存实例，以控制缓存的启用或禁用。

    Returns:
        Cache: 一个缓存实例，具体类型由 `settings.CACHE_TYPE` 决定。

使用样例：
    
# 初始化缓存
cache = await CacheFactory.create_cache()

# 检查缓存状态
if cache.is_enabled():
    print("缓存已启用")
else:
    print("缓存已禁用")

# 动态启用/禁用缓存
cache.disable()  # 临时禁用缓存

# 即使缓存禁用，生成ID仍可用（用于其他目的）
cache_id = await cache.generate_key()
print(f"生成的ID: {cache_id}")

# 禁用状态下设置缓存（无操作）
await cache.set(cache_id, "test", "value")

# 重新启用缓存
cache.enable()

# 正常使用缓存
await cache.set(cache_id, "user", {"name": "Alice", "age": 30})
user_data = await cache.get(cache_id, "user")
print(user_data)  # {'name': 'Alice', 'age': 30}
"""


class Cache(ABC):
    @abstractmethod
    async def generate_key(self, *args, **kwargs) -> str:
        """生成唯一缓存key"""
        pass

    @abstractmethod
    async def get(self, key: str, field: str) -> Any:
        """获取缓存字段值"""
        pass

    @abstractmethod
    async def get_all(self, field_list: list) -> list:
        """获取所有缓存数据"""
        pass

    @abstractmethod
    async def set(self, key: str, field: str, value: Any, ttl: Optional[int] = None) -> None:
        """设置缓存字段值"""
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """删除缓存键"""
        pass

    @abstractmethod
    async def close(self) -> None:
        """关闭缓存并释放资源"""
        pass


class CacheProxy(Cache):
    """缓存代理，提供启用/禁用开关"""

    def __init__(self, cache: Cache, enabled: bool = True):
        self.cache = cache
        self.enabled = enabled

    async def generate_key(self, *args, **kwargs) -> str:
        """始终生成ID，即使缓存禁用"""
        return await self.cache.generate_key(*args, **kwargs)

    async def get(self, key: str, field: str) -> Any:
        if not self.enabled:
            return None
        return await self.cache.get(key, field)

    async def get_all(self, field_list: list) -> list:
        if not self.enabled:
            return []
        return await self.cache.get_all(field_list)

    async def set(self, key: str, field: str, value: Any, ttl: Optional[int] = None) -> None:
        if not self.enabled:
            return
        await self.cache.set(key, field, value, ttl)

    async def delete(self, key: str) -> None:
        if not self.enabled:
            return
        await self.cache.delete(key)

    async def close(self) -> None:
        """关闭底层缓存"""
        await self.cache.close()

    def enable(self):
        """启用缓存"""
        self.enabled = True

    def disable(self):
        """禁用缓存"""
        self.enabled = False

    def is_enabled(self) -> bool:
        """检查缓存是否启用"""
        return self.enabled


class MemoryCache(Cache):
    def __init__(self):
        self.cache = {}

    async def generate_key(self, *args, **kwargs) -> str:
        return str(uuid.uuid4())

    async def set(self, key: str, field: str, value: Any, ttl: Optional[int] = None) -> None:
        if key not in self.cache:
            self.cache[key] = {}
        self.cache[key][field] = value

    async def get(self, key: str, field: str) -> Any:
        return self.cache.get(key, {}).get(field)

    async def get_all(self, field_list: list) -> list:
        result = []
        for key, fields in self.cache.items():
            item = {"id": key}
            for field in field_list:
                item[field] = fields.get(field)
            result.append(item)
        return result

    async def delete(self, key: str) -> None:
        if key in self.cache:
            del self.cache[key]

    async def close(self) -> None:
        """内存缓存无需清理资源"""
        pass


class RedisCache(Cache):
    def __init__(self):
        self.redis = None
        self.prefix = "cache:"

    async def _get_redis(self):
        if not self.redis:
            import aioredis
            self.redis = await aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
        return self.redis

    async def generate_key(self, *args, **kwargs) -> str:
        return f"{self.prefix}{uuid.uuid4()}"

    async def set(self, key: str, field: str, value: Any, ttl: Optional[int] = None) -> None:
        redis = await self._get_redis()
        # 哈希表操作
        await redis.hset(key, field, json.dumps(value))
        if ttl:
            await redis.expire(key, ttl)

    async def get(self, key: str, field: str) -> Any:
        redis = await self._get_redis()
        value = await redis.hget(key, field)
        return json.loads(value) if value else None

    async def get_all(self, field_list: list) -> list:
        redis = await self._get_redis()
        result = []

        # 使用SCAN安全遍历所有键
        async for key in redis.scan_iter(f"{self.prefix}*"):
            item = {"id": key}
            # 批量获取多个字段
            values = await redis.hmget(key, *field_list)
            for idx, field in enumerate(field_list):
                item[field] = json.loads(values[idx]) if values[idx] else None
            result.append(item)
        return result

    async def delete(self, key: str) -> None:
        redis = await self._get_redis()
        await redis.delete(key)

    async def close(self) -> None:
        """关闭Redis连接"""
        if self.redis:
            await self.redis.close()
            await self.redis.wait_closed()
            self.redis = None


class CacheManager:
    """
        CacheManager 类提供了一个静态方法来创建和配置缓存实例。
        它根据设置选择合适的缓存类型，并通过代理添加启用/禁用缓存的功能。
    """

    @classmethod
    async def get_cache(cls) -> Cache:
        """
        获取全局唯一的缓存实例（单例模式）
        """
        if cls._instance is None:
            # 创建基础缓存实例
            if settings.CACHE_TYPE == "memory":
                base_cache = MemoryCache()
            elif settings.CACHE_TYPE == "redis":
                base_cache = RedisCache()
            else:
                raise ValueError(f"Unsupported cache type: {settings.CACHE_TYPE}")

            # 使用代理包装基础缓存
            cls._instance = CacheProxy(
                cache=base_cache,
                enabled=settings.CACHE_ENABLED
            )
        return cls._instance

    @classmethod
    async def close_cache(cls) -> None:
        """关闭缓存并释放资源"""
        if cls._instance:
            await cls._instance.close()
            cls._instance = None

    @classmethod
    def reset_cache(cls):
        """
        重置缓存实例（主要用于测试）
        """
        cls._instance = None
