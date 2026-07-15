import json
from typing import Any

import redis.asyncio as redis

from app.core.config import get_settings

settings = get_settings()

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def cache_get(key: str) -> Any | None:
    client = get_redis()
    raw = await client.get(key)
    if raw is None:
        return None
    return json.loads(raw)


async def cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    client = get_redis()
    await client.set(key, json.dumps(value, default=str), ex=ttl or settings.cache_ttl_seconds)
