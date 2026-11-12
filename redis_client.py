import logging
import redis
import random
from redis.exceptions import RedisError

from config import (
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    REDIS_PASSWORD
)

logger = logging.getLogger(__name__)

# 缓存过期时间随机比例      ###    jitter的计算
CACHE_TTL_JITTER_RATIO = 0.1

# 创建 Redis 连接
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2
)


# 测试 Redis 连接
def check_redis():
    try:
        return redis_client.ping()

    except RedisError:
        logger.exception("Redis 连接检测失败")
        return False



# 写入缓存
def set_cache(
    key: str,
    value: str,
    expire: int = 600
):

    # 1. 检查 TTL 是否合法
    if not isinstance(expire, int) or isinstance(expire, bool) or expire <= 0:
        raise ValueError("expire 必须是正整数")

    # 2. 计算随机浮动范围
    jitter = max(
        1,      #至少保留 1 秒的浮动范围
        int(expire * CACHE_TTL_JITTER_RATIO)
    )

    # 3. 计算最小和最大过期时间
    min_expire = max(1, expire - jitter)
    max_expire = expire + jitter

    # 4. 随机生成实际 TTL
    actual_expire = random.randint(
        min_expire,
        max_expire
    )

    try:

        # 5. 使用随机后的 TTL 写入 Redis，Redis 存入时实际执行
        result = redis_client.set(
            key,
            value,
            ex=actual_expire
        )

        return bool(result)

    except RedisError:

        logger.exception(
            "Redis 缓存写入失败,key=%s",
            key
        )

        return False



# 获取缓存
def get_cache(key: str):
    try:
        return redis_client.get(key)

    except RedisError:
        logger.exception("Redis 缓存读取失败,key=%s", key)
        return None


# 删除缓存
def delete_cache(key: str):
    try:
        return redis_client.delete(key)

    except RedisError:
        logger.exception("Redis 缓存删除失败,key=%s", key)
        return 0
