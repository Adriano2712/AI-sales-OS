from functools import lru_cache

import redis
from rq import Queue

from app.core.config import get_settings


@lru_cache
def get_redis_connection() -> redis.Redis:
    settings = get_settings()
    return redis.from_url(settings.redis_url)


@lru_cache
def get_queue(name: str = "default") -> Queue:
    return Queue(name, connection=get_redis_connection())
