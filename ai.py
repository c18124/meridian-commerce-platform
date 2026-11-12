import hashlib
import json

import logging
import time
logger = logging.getLogger(__name__)

from openai import OpenAI
from sqlalchemy.orm import Session

from config import API_KEY, MODEL
from database import (
    SessionLocal,
    get_messages,
    save_messages,
)
from redis_client import get_cache, set_cache

from redis.exceptions import RedisError
from redis_lock import (
    acquire_lock,
    release_lock,
    start_lock_renewal
)

client = OpenAI(
    api_key=API_KEY,
    base_url="https://api.deepseek.com"
)


# 只限制发给模型的历史，不删除数据库中的记录。
MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_CHARS = 20000

# Redis 分布式锁配置
CACHE_LOCK_EXPIRE = 120

# 最多等待其他请求生成缓存的时间
CACHE_LOCK_WAIT_TIMEOUT = 30

# 每次重新检查的间隔
CACHE_LOCK_POLL_INTERVAL = 0.1



def build_messages(db: Session, user_id: str, question: str):
    history = get_messages(db, user_id)

    messages = []
    history_chars = 0

    # 从最新消息向前选取，保留连续的最近一段历史。
    for message in reversed(history[-MAX_HISTORY_MESSAGES:]):
        content_length = len(message["content"])

        if history_chars + content_length > MAX_HISTORY_CHARS:
            break

        messages.append(message)
        history_chars += content_length

    messages.reverse()

    # 避免截取后的上下文以孤立的 AI 回答开头。
    while messages and messages[0]["role"] == "assistant":
        messages.pop(0)

    # 当前问题始终保留，不计入历史消息的额度。
    messages.append({
        "role": "user",
        "content": question
    })

    return messages

def clean_messages(messages: list[dict]) -> list[dict]:

    clean_data = []

    for message in messages:

        clean_data.append({
            "role": message["role"],
            "content": message["content"]
        })

    return clean_data

    #以上下文记录和问题一起作为redis key
def make_context_cache_key(
        user_id: str,
        messages: list[dict]
    ) -> str:

    clean_data = clean_messages(messages)

    content = json.dumps(
        {
            "user_id": user_id,
            "messages": clean_data,
            "model": MODEL,
            "version": "v1"
        },
        ensure_ascii=False,
        sort_keys=True
    )

    key_hash = hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()

    return f"chat:context:v1:{key_hash}"

    #单独以问题作为redis key
def make_question_cache_key(
        user_id: str,
        question: str
    ) -> str:

    content = json.dumps(
        {
            "user_id": user_id,
            "question": question.strip(),
            "model": MODEL,
            "prompt_version": "v1",
            "cache_version": "v1"
        },
        ensure_ascii=False,
        sort_keys=True
    )

    key_hash = hashlib.sha256(
        content.encode("utf-8")  # 将内容编码为 UTF-8 字节
    ).hexdigest()  # 计算 SHA-256 哈希值

    return f"chat:question:v1:{key_hash}"

    #正常聊天问答流程
def chat(db: Session, user_id: str, question: str, cache_mode: str = "context"):

    # 1. 根据缓存模式选择聊天上下文和缓存 Key

    if cache_mode == "context":

        # 上下文模式：查询 MySQL 历史消息
        messages = build_messages(
            db,
            user_id,
            question
        )

        # 生成完整上下文缓存 Key
        cache_key = make_context_cache_key(
            user_id,
            messages
        )

    elif cache_mode == "question":

        # 独立问题模式：不读取历史上下文
        messages = [
            {
                "role": "user",
                "content": question.strip()
            }
        ]

        # 生成独立问题缓存 Key
        cache_key = make_question_cache_key(
            user_id,
            question
        )

    else:
        raise ValueError("不支持的缓存模式")
    # 3. 查询 Redis 缓存
    cache_start = time.perf_counter()

    cached_answer = get_cache(cache_key)

    cache_duration = time.perf_counter() - cache_start

    # 记录缓存查询耗时
    if cached_answer is not None:
        logger.info(
            "Redis 缓存命中，耗时 %.4f 秒",
            cache_duration
        )
    else:
        logger.info(
            "Redis 缓存未命中，耗时 %.4f 秒",
            cache_duration
        )

    # 4. 如果缓存命中
    if cached_answer is not None:

        # 保存本次用户问题
        save_messages(db, user_id, "user", question)

        # 保存缓存中的 AI 回答
        save_messages(db, user_id, "assistant", cached_answer)

        # 直接返回，不调用 DeepSeek
        return cached_answer

    # 5. 缓存未命中，保存用户问题
    save_messages(db, user_id, "user", question)

    # 记录模型调用开始时间
    ai_start = time.perf_counter()

    response = client.chat.completions.create(
        model=MODEL,
        messages=messages
    )

    ai_duration = time.perf_counter() - ai_start

    logger.info(
        "DeepSeek API 调用完成，耗时 %.4f 秒",
        ai_duration
    )

    answer = response.choices[0].message.content

    # 7. 保存 AI 回答到 MySQL
    save_messages(db, user_id, "assistant", answer)

    # 8. 将 AI 回答保存到 Redis，默认有效期 600 秒
    set_cache(cache_key, answer)

    # 9. 返回答案
    return answer



def _wait_for_cache_or_lock(
    cache_key: str,
    lock_key: str
):
    # 1. 计算等待截止时间
    deadline = (
        time.monotonic()
        + CACHE_LOCK_WAIT_TIMEOUT
    )

    # 2. 不断检查缓存和锁
    while time.monotonic() < deadline:

        # 2.1 检查其他请求是否已经生成答案  #每次循环先检查reids中有没有回答后再抢锁
        cached_answer = get_cache(cache_key)

        if cached_answer is not None:
            return cached_answer, None

        # 2.2 尝试重新获取锁
        lock_value = acquire_lock(
            lock_key,
            expire=CACHE_LOCK_EXPIRE #锁的有效期时间
        )

        # 2.3 获取成功，返回锁标识
        if lock_value is not None:
            return None, lock_value

        # 2.4 没有获取成功，稍后继续检查
        time.sleep(CACHE_LOCK_POLL_INTERVAL)

    # 3. 等待超时
    return None, None



    #流式回答的业务函数
def chat_stream(
    user_id: str,
    question: str,
    cache_mode: str = "context"
):
    db = SessionLocal()

    answer = ""
    completed = False

    # 当前请求持有的锁
    lock_key = None
    lock_value = None

    # 自动续期线程的控制变量
    renewal_stop_event = None
    renewal_thread = None
    lock_lost_event = None


    try:

        # 1. 根据缓存模式构建 messages
        # 和 Cache Key

        if cache_mode == "context":

            messages = build_messages(
                db,
                user_id,
                question
            )

            cache_key = make_context_cache_key(
                user_id,
                messages
            )

        elif cache_mode == "question":

            messages = [
                {
                    "role": "user",
                    "content": question.strip()
                }
            ]

            cache_key = make_question_cache_key(
                user_id,
                question
            )

        else:
            raise ValueError("不支持的缓存模式")

        # 2. 第一次查询缓存

        cache_start = time.perf_counter()

        cached_answer = get_cache(cache_key)

        cache_duration = time.perf_counter() - cache_start

        if cached_answer is not None:

            logger.info(
                "流式聊天缓存命中，模式=%s,耗时 %.4f 秒",
                cache_mode,
                cache_duration
            )

            save_messages(
                db,
                user_id,
                "user",
                question
            )

            save_messages(
                db,
                user_id,
                "assistant",
                cached_answer
            )

            yield cached_answer
            return

        logger.info(
            "流式聊天缓存未命中，模式=%s,耗时 %.4f 秒",
            cache_mode,
            cache_duration
        )

        # 3. 构建分布式锁 Key

        lock_key = f"lock:{cache_key}"

        try:

            # 4. 第一次尝试获取锁

            lock_value = acquire_lock(
                lock_key,
                expire=CACHE_LOCK_EXPIRE
            )

            # 5. 如果锁被其他请求占用

            if lock_value is None:

                cached_answer, lock_value = (
                    _wait_for_cache_or_lock(
                        cache_key,
                        lock_key
                    )
                )

                # 5.1 其他请求已经生成缓存
                #并且 _wait_for_cache_or_lock 中已经return cached_answer
                if cached_answer is not None:

                    save_messages(
                        db,
                        user_id,
                        "user",
                        question
                    )

                    save_messages(
                        db,
                        user_id,
                        "assistant",
                        cached_answer
                    )

                    yield cached_answer
                    return

                # 5.2 等待超时

                if lock_value is None:

                    raise TimeoutError(
                        "等待其他请求生成缓存超时"
                    )

            # 6. Double Check：获得锁后再次检查缓存

            cached_answer = get_cache(cache_key)

            if cached_answer is not None:

                logger.info(
                    "分布式锁获取成功后发现缓存已生成"
                )

                save_messages(
                    db,
                    user_id,
                    "user",
                    question
                )

                save_messages(
                    db,
                    user_id,
                    "assistant",
                    cached_answer
                )

                yield cached_answer
                return

            # 7. 如果当前请求持有锁，启动自动续期线程
            if lock_value is not None:

                renewal_stop_event, renewal_thread, lock_lost_event = (
                    start_lock_renewal(
                        lock_key,
                        lock_value,
                        expire=CACHE_LOCK_EXPIRE
                    )
                )

        except RedisError:

            # Redis 锁服务不可用时，降级为无锁生成

            logger.exception(
                "Redis 分布式锁不可用，降级为无锁生成"
            )

        # 7. 缓存仍然不存在，保存用户问题

        save_messages(
            db,
            user_id,
            "user",
            question
        )

        # 8. 调用 DeepSeek 流式接口

        ai_start = time.perf_counter()

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            stream=True
        )

        # 9. 接收模型返回的内容

        try:

            for chunk in response:

                # 1. 检查分布式锁是否续期失败
                if (
                    lock_lost_event is not None
                    and lock_lost_event.is_set()
                ):
                    raise RuntimeError(
                        "Redis 分布式锁续期失败，停止本次模型生成"
                    )

                # 2. 获取模型返回的文本
                content = chunk.choices[0].delta.content

                # 3. 有内容才进行处理
                if content:

                    answer += content

                    # 4. 实时发送给前端
                    yield content


            # 5. 模型生成结束后，先停止自动续期线程

            if renewal_stop_event is not None:

                renewal_stop_event.set()

            # 6. 等待续期线程彻底结束

            if renewal_thread is not None:

                renewal_thread.join()

                logger.info("模型生成结束，自动续期线程已停止")

                # 避免外层 finally 重复等待
                renewal_thread = None

            renewal_stop_event = None

            # 7. 最终检查锁是否丢失

            if (
                lock_lost_event is not None
                and lock_lost_event.is_set()
            ):

                raise RuntimeError(
                    "Redis 分布式锁已经失效，不能保存本次回答"
                )

            # 8. 确认模型完整生成
            completed = True



        finally:

            # 10. 主动关闭模型响应

            close_response = getattr(
                response,
                "close",
                None
            )

            if callable(close_response):

                try:
                    close_response()

                except Exception:
                    logger.exception(
                        "DeepSeek 流式连接关闭失败"
                    )

            # 11. 只有完整生成成功才保存回答和缓存

            if completed and answer:

                save_messages(
                    db,
                    user_id,
                    "assistant",
                    answer
                )

                cache_saved = set_cache(
                    cache_key,
                    answer
                )

                logger.info(
                    "流式聊天缓存写入%s",
                    "成功" if cache_saved else "失败"
                )

            ai_duration = time.perf_counter() - ai_start

            logger.info(
                "DeepSeek 流式生成结束，耗时 %.4f 秒",
                ai_duration
            )

    finally:

        # 1. 通知自动续期线程停止
        try:

            if renewal_stop_event is not None:

                renewal_stop_event.set()

            # 2. 等待后台线程真正结束
            if renewal_thread is not None:

                renewal_thread.join()

                logger.info("分布式锁自动续期线程已停止")

        finally:

            try:

                # 3. 释放当前请求持有的锁
                if lock_key is not None and lock_value is not None:

                    released = release_lock(
                        lock_key,
                        lock_value
                    )

                    if not released:

                        logger.warning(
                            "分布式锁释放失败,key=%s",
                            lock_key
                        )

            finally:

                # 4. 无论如何关闭数据库连接
                db.close()