    #redis 分布式锁 的操作函数集
import logging
import secrets
import threading
from redis.exceptions import RedisError

from redis_client import redis_client


logger = logging.getLogger(__name__)


# 1. Lua 脚本：安全释放分布式锁
RELEASE_LOCK_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

# 续期 Lua 脚本
RENEW_LOCK_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("EXPIRE", KEYS[1], tonumber(ARGV[2]))
else
    return 0
end
"""



# 2. 获取分布式锁
def acquire_lock(
    lock_key: str,
    expire: int = 120
) -> str | None:

    # 检查参数
    if not isinstance(lock_key, str) or not lock_key.strip():
        raise ValueError("lock_key 不能为空")

    if not isinstance(expire, int) or isinstance(expire, bool) or expire <= 0:
        raise ValueError("expire 必须是正整数")

    # 生成本次请求唯一的分布式锁标识,每一个请求都会生成一个独立的锁标识
    lock_value = secrets.token_urlsafe(16)

    try:

        # SET key value NX EX expire,如果这个 key 目前没有，就把 value 存进去，并且给它设一个自动过期时间
        acquired = redis_client.set(
            lock_key,
            lock_value,
            nx=True,
            ex=expire
        )

        # 获取成功，返回锁标识
        if acquired:
            return lock_value

        # 获取失败，说明其他请求已经持有锁
        return None

    except RedisError:

        logger.exception(
            "Redis 分布式锁获取失败,key=%s",
            lock_key
        )

        raise


# 3. 释放分布式锁
def release_lock(
    lock_key: str,
    lock_value: str
) -> bool:

    if not lock_key or not lock_value:
        raise ValueError("lock_key 和 lock_value 不能为空")

    try:

        # 使用 Lua 保证比较和删除操作的原子性
        result = redis_client.eval(
            RELEASE_LOCK_SCRIPT,
            1,
            lock_key,
            lock_value
        )

        return bool(result)

    except RedisError:

        logger.exception(
            "Redis 分布式锁释放失败,key=%s",
            lock_key
        )

        return False



    #分布式锁的续期
def renew_lock(
    lock_key: str,
    lock_value: str,
    expire: int = 120
) -> bool:

   # 1. 检查锁 Key
    if not isinstance(lock_key, str) or not lock_key.strip():
        raise ValueError("lock_key 不能为空")

    # 2. 检查锁 Token
    if not isinstance(lock_value, str) or not lock_value.strip():
        raise ValueError("lock_value 不能为空")

    # 3. 检查过期时间
    if (
        not isinstance(expire, int)
        or isinstance(expire, bool)
        or expire <= 0
    ):
        raise ValueError("expire 必须是正整数")

    try:

        # 2. 执行 Lua 续期脚本
        result = redis_client.eval(
            RENEW_LOCK_SCRIPT,
            1,
            lock_key,
            lock_value,
            expire          #EXPIRE 是重新设置锁的有效期，不是在剩余时间上累加
        )

        # 3. 返回续期结果
        return bool(result)

    except RedisError:

        logger.exception(
            "Redis 分布式锁续期失败,key=%s",
            lock_key
        )

        return False




# 4. 自动续期线程
def start_lock_renewal(
    lock_key: str,
    lock_value: str,
    expire: int = 120
):
    # 1. 创建停止信号
    stop_event = threading.Event()

    # 2. 创建续期失败信号
    lost_event = threading.Event()

    # 3. 设置续期间隔
    renew_interval = max(0.1, expire / 3)

    # 4. 定义后台线程执行的任务
    def renewal_worker():

        while not stop_event.wait(renew_interval):  #在续期等待时间内没有收到停止信号 就执行循环

            try:

                # 4.1 尝试延长锁的有效期
                renewed = renew_lock(
                    lock_key,
                    lock_value,
                    expire
                )

                # 4.2 续期失败
                if not renewed:

                    logger.error(
                        "分布式锁续期失败，锁可能已经失效,key=%s",
                        lock_key
                    )

                    lost_event.set()

                    return

                logger.info(
                    "分布式锁自动续期成功,key=%s",
                    lock_key
                )

            except Exception:

                logger.exception(
                    "分布式锁自动续期发生异常,key=%s",
                    lock_key
                )

                lost_event.set()

                return

    # 5. 创建后台线程
    thread = threading.Thread(
        target=renewal_worker,
        name="redis-lock-renewal",
        daemon=True
    )

    # 6. 启动后台线程
    thread.start()

    # 7. 返回线程控制对象
    return stop_event, thread, lost_event
