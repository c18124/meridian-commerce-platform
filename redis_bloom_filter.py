    #分布式 redis
import json
import logging

from redis.exceptions import RedisError

from bloom_filter import BloomFilter
from redis_client import redis_client


logger = logging.getLogger(__name__)


class RedisBloomFilter:

    def __init__(
        self,
        capacity: int,
        error_rate: float,
        key: str = "bloom:documents:v1"
    ):

        # 1. 创建本地哈希计算器
        self.filter = BloomFilter(
            capacity,
            error_rate
        )

        self.key = key
        self.meta_key = f"{key}:meta"

        # 2. 保存过滤器配置
        self.metadata = {
            "version": 1,
            "capacity": capacity,
            "error_rate": error_rate,
            "bit_size": self.filter.bit_size,
            "hash_count": self.filter.hash_count
        }
        #固定 key 的顺序
        metadata_json = json.dumps(
            self.metadata,
            sort_keys=True
        )

        # 3. 如果配置不存在，就初始化
        redis_client.set(
            self.meta_key,
            metadata_json,
            nx=True
        )

        # 4. 检查 Redis 中已有的配置
        saved_metadata = redis_client.get(
            self.meta_key
        )

        if saved_metadata is None:
            raise RuntimeError("Redis 过滤器配置初始化失败")

        if json.loads(saved_metadata) != self.metadata:
            raise ValueError("Redis 中的过滤器配置不一致")

    # 添加元素
    def add(self, item: str):

        try:
            # 1. 计算哈希位置
            positions = self.filter._get_positions(item)

            # 2. 创建 Redis Pipeline
            pipe = redis_client.pipeline(transaction=True)

            # 3. 批量设置位
            for position in positions:
                pipe.setbit(self.key, position, 1)

            # 4. 执行 Redis 命令
            pipe.execute()

            return True

        except RedisError:
            logger.exception(
                "Redis 布隆过滤器添加失败,item=%s",
                item
            )

        # 返回 False，表示过滤器没有成功更新
        return False


    # 查询元素
    def contains(self, item: str):

        # 1. 计算哈希位置
        positions = self.filter._get_positions(item)

        try:
            # 2. 创建 Redis Pipeline
            pipe = redis_client.pipeline(transaction=True)

            # 3. 批量查询位数组
            for position in positions:
                pipe.getbit(self.key, position)

            results = pipe.execute()

            # 4. 所有位置都是 1，才可能存在
            return all(results)

        except RedisError:
            logger.exception(
                "Redis 布隆过滤器查询失败,item=%s",
                item
            )

            # 故障降级：放行后续 MySQL 查询
            return True
