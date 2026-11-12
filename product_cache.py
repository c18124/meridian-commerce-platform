    #管理商品查询 redis缓存的 操作函数
"""商品 Redis 缓存服务"""

import json
import logging
from typing import Any

from redis.exceptions import RedisError

from redis_client import (
    redis_client,
    get_cache,
    set_cache,
    delete_cache
)


logger = logging.getLogger(__name__)


# 商品缓存版本号
PRODUCT_CACHE_VERSION_KEY = "cache:products:version"

# 商品详情缓存 180 秒
PRODUCT_DETAIL_CACHE_TTL = 180

# 商品列表缓存 60 秒
PRODUCT_LIST_CACHE_TTL = 60


# 1. 获取当前商品缓存版本
def get_product_cache_version() -> int:

    version = get_cache(PRODUCT_CACHE_VERSION_KEY)

    if version is None:
        return 0

    try:
        return max(0, int(version))

    except (TypeError, ValueError):

        logger.warning("商品缓存版本号异常")

        return 0


# 2. 生成商品详情缓存 Key
def _detail_key(
    product_id: int,
    version: int
) -> str:

    return (
        f"cache:products:v{version}:"
        f"detail:{product_id}"
    )


# 3. 生成商品列表缓存 Key
def _list_key(
    page: int,
    page_size: int,
    version: int
) -> str:

    return (
        f"cache:products:v{version}:"
        f"list:{page}:{page_size}"
    )


# 4. 读取 JSON 缓存
def _get_json(key: str) -> dict | None:

    value = get_cache(key)

    if value is None:
        return None

    try:

        result = json.loads(value)

        if not isinstance(result, dict):
            raise ValueError("缓存数据格式不正确")

        return result

    except (json.JSONDecodeError, TypeError, ValueError):

        logger.warning(
            "商品缓存数据损坏，删除缓存 Key=%s",
            key
        )

        delete_cache(key)

        return None


# 5. 写入 JSON 缓存
def _set_json(
    key: str,
    value: dict[str, Any],
    expire: int
) -> bool:

    try:

        content = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":")
        )

    except (TypeError, ValueError):

        logger.exception("商品缓存 JSON 序列化失败")

        return False

    return set_cache(
        key,
        content,
        expire=expire
    )


# 6. 获取商品详情缓存
def get_product_detail_cache(
    product_id: int,
    version: int
) -> dict | None:

    key = _detail_key(
        product_id,
        version
    )

    return _get_json(key)


# 7. 写入商品详情缓存
def set_product_detail_cache(
    product_id: int,
    data: dict[str, Any],
    version: int
) -> bool:

    key = _detail_key(
        product_id,
        version
    )

    return _set_json(
        key,
        data,
        PRODUCT_DETAIL_CACHE_TTL
    )


# 8. 获取商品列表缓存
def get_product_list_cache(
    page: int,
    page_size: int,
    version: int
) -> dict | None:

    key = _list_key(
        page,
        page_size,
        version
    )

    return _get_json(key)


# 9. 写入商品列表缓存
def set_product_list_cache(
    page: int,
    page_size: int,
    data: dict[str, Any],
    version: int
) -> bool:

    key = _list_key(
        page,
        page_size,
        version
    )

    return _set_json(
        key,
        data,
        PRODUCT_LIST_CACHE_TTL
    )


# 10. 商品数据发生变化，统一使旧缓存失效
def invalidate_product_cache() -> bool:

    try:

        new_version = redis_client.incr(
            PRODUCT_CACHE_VERSION_KEY
        )

        logger.info(
            "商品缓存版本已更新：%s",
            new_version
        )

        return True

    except RedisError:

        logger.exception("商品缓存失效处理失败")

        return False
