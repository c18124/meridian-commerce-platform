import pytest

from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import ai
import database

import redis_client as redis_module
from redis.exceptions import ConnectionError as RedisConnectionError

@pytest.fixture
def test_db(tmp_path, monkeypatch):

    # 1. 创建临时 SQLite 数据库
    test_db_path = tmp_path / "test_ai.db"
    #
    test_engine = create_engine(
        f"sqlite:///{test_db_path}",
        connect_args={"check_same_thread": False}
    )

    # 2. 创建数据表
    database.Base.metadata.create_all(test_engine)

    # 3. 创建测试 Session 工厂
    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False
    )

    # 4. 替换 ai.py 中的 SessionLocal
    monkeypatch.setattr(
        ai,
        "SessionLocal",
        TestingSessionLocal
    )
    # 5. 返回测试 Session 工厂
    yield TestingSessionLocal

    # 6. 清理测试数据库
    test_engine.dispose()

    #fixture  mock 模拟分布式锁的
@pytest.fixture(autouse=True)
def mock_redis_lock(monkeypatch):

    monkeypatch.setattr(
        ai,
        "acquire_lock",
        lambda lock_key, expire=120: "test-lock-token"
    )

    monkeypatch.setattr(
        ai,
        "release_lock",
        lambda lock_key, lock_value: True
    )

    monkeypatch.setattr(
    ai,
    "start_lock_renewal",
    lambda lock_key, lock_value, expire=120: (
        None,
        None,
        None
    )
)




    #测试流式回答
def test_chat_stream_cache_hit(
    test_db,
    monkeypatch
):


    # 1. 模拟 Redis 已经存在缓存
    def fake_get_cache(key):
        return "你好！这是 Redis 中的缓存回答。"

    monkeypatch.setattr(
        ai,
        "get_cache",
        fake_get_cache
    )

    # 2. 缓存命中时，不允许执行任何锁操作
    def unexpected_lock_call(*args, **kwargs):
        pytest.fail("缓存命中时不应该执行分布式锁操作")

    # 如果尝试获取锁，测试立即失败
    monkeypatch.setattr(
        ai,
        "acquire_lock",
        unexpected_lock_call
    )

    # 如果尝试启动自动续期线程，测试立即失败
    monkeypatch.setattr(
        ai,
        "start_lock_renewal",
        unexpected_lock_call
    )

    # 如果尝试释放锁，测试立即失败
    monkeypatch.setattr(
        ai,
        "release_lock",
        unexpected_lock_call
    )

    # 2. 如果调用 DeepSeek，测试直接失败
    def fake_create(*args, **kwargs):
        pytest.fail("缓存命中时不应该调用 DeepSeek")

    monkeypatch.setattr(
        ai.client.chat.completions,
        "create",
        fake_create
    )

    # 3. 执行流式聊天
    result = list(
        ai.chat_stream(
            "user001",
            "你好",
            cache_mode="context"
        )
    )

    # 4. 验证返回内容
    assert result == [
        "你好！这是 Redis 中的缓存回答。"
    ]

    # 5. 验证 MySQL 是否保存了对话
    db = test_db()

    try:
        messages = database.get_messages(
            db,
            "user001"
        )

        assert messages == [
            {
                "role": "user",
                "content": "你好"
            },
            {
                "role": "assistant",
                "content": "你好！这是 Redis 中的缓存回答。"
            }
        ]

    finally:
        db.close()


def test_chat_stream_cache_miss(
    test_db,
    monkeypatch
):

    # 1. 模拟 Redis 缓存未命中
    monkeypatch.setattr(
        ai,
        "get_cache",
        lambda key: None
    )


    # 记录自动续期的完整生命周期
    renewal_calls = []
    lifecycle = []

    # 模拟线程事件
    class FakeEvent:

        def __init__(self, event_name=None):
            self.value = False
            self.event_name = event_name

        def set(self):
            self.value = True

            if self.event_name:
                lifecycle.append(self.event_name)

        def is_set(self):
            return self.value

    # 模拟后台线程
    class FakeThread:

        def join(self):
            lifecycle.append("join")

    stop_event = FakeEvent("stop")
    lost_event = FakeEvent()

    # 模拟启动自动续期线程
    def fake_start_lock_renewal(
        lock_key,
        lock_value,
        expire=120
    ):

        lifecycle.append("start")

        renewal_calls.append({
            "lock_key": lock_key,
            "lock_value": lock_value,
            "expire": expire
        })

        return stop_event, FakeThread(), lost_event

    monkeypatch.setattr(
        ai,
        "start_lock_renewal",
        fake_start_lock_renewal
    )

    # 记录锁释放
    def fake_release_lock(lock_key, lock_value):

        lifecycle.append("release")

        return True

    monkeypatch.setattr(
        ai,
        "release_lock",
        fake_release_lock
    )

    # 2. 记录 DeepSeek 是否被调用
    api_calls = []

    def fake_create(*args, **kwargs):

        api_calls.append(kwargs)

        # 模拟 DeepSeek 流式响应
        chunks = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="你好，"
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="我是 AI 助手。"
                        )
                    )
                ]
            )
        ]

        return iter(chunks)

    monkeypatch.setattr(
        ai.client.chat.completions,
        "create",
        fake_create
    )

    # 3. 记录 Redis 是否写入缓存
    cache_writes = []

    def fake_set_cache(key, value, expire=600):

        cache_writes.append({
            "key": key,
            "value": value,
            "expire": expire
        })

        return True

    monkeypatch.setattr(
        ai,
        "set_cache",
        fake_set_cache
    )

    # 4. 执行流式聊天
    result = list(
        ai.chat_stream(
            "user002",
            "你好",
            cache_mode="context"
        )
    )

    # 5. 验证流式返回内容
    assert result == [
        "你好，",
        "我是 AI 助手。"
    ]

    # 6. 验证 DeepSeek 确实被调用
    assert len(api_calls) == 1

    # 7. 验证 Redis 写入完整答案
    assert len(cache_writes) == 1

    assert cache_writes[0]["value"] == (
        "你好，我是 AI 助手。"
    )

    # 8. 验证 MySQL 保存聊天记录
    db = test_db()

    try:

        messages = database.get_messages(
            db,
            "user002"
        )

        assert messages == [
            {
                "role": "user",
                "content": "你好"
            },
            {
                "role": "assistant",
                "content": "你好，我是 AI 助手。"
            }
        ]

    finally:
        db.close()


    # 9. 验证自动续期线程确实启动
    assert len(renewal_calls) == 1

    assert renewal_calls[0]["lock_key"].startswith("lock:")

    assert renewal_calls[0]["lock_value"] == "test-lock-token"

    assert renewal_calls[0]["expire"] == ai.CACHE_LOCK_EXPIRE

    # 10. 验证自动续期线程收到停止通知
    assert stop_event.is_set()

    # 11. 验证线程停止、等待、释放锁的顺序
    assert lifecycle == [
        "start",
        "stop",
        "join",
        "release"
    ]




    #测试当redis写入失败时 redis故障降级是否成功
def test_chat_stream_redis_write_failure(
    test_db,
    monkeypatch
):

    # 1. 模拟 Redis 缓存未命中
    monkeypatch.setattr(
        ai,
        "get_cache",
        lambda key: None
    )

    # 2. 模拟 DeepSeek 正常返回
    def fake_create(*args, **kwargs):

        chunks = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="AI 正常回答"
                        )
                    )
                ]
            )
        ]

        return iter(chunks)

    monkeypatch.setattr(
        ai.client.chat.completions,
        "create",
        fake_create
    )

    # 3. 模拟 Redis 写入失败
    def fake_set_cache(key, value, expire=600):
        return False

    monkeypatch.setattr(
        ai,
        "set_cache",
        fake_set_cache
    )

    # 4. 执行流式聊天
    result = list(
        ai.chat_stream(
            "user003",
            "你好",
            cache_mode="context"
        )
    )

    # 5. 验证 AI 仍然正常返回
    assert result == ["AI 正常回答"]

    # 6. 验证 MySQL 仍然保存了聊天记录
    db = test_db()

    try:

        messages = database.get_messages(
            db,
            "user003"
        )

        assert messages == [
            {
                "role": "user",
                "content": "你好"
            },
            {
                "role": "assistant",
                "content": "AI 正常回答"
            }
        ]

    finally:
        db.close()


    #模拟在redis连接异常时不影响大模型正常回答，故障降级
def test_chat_stream_redis_connection_failure(
    test_db,
    monkeypatch,
    caplog
):

    # 1. 模拟 Redis 连接异常
    def fake_redis_get(key):
        raise RedisConnectionError(
            "模拟 Redis 连接失败"
        )

    monkeypatch.setattr(
        redis_module.redis_client,
        "get",
        fake_redis_get
    )

    # 2. 模拟 DeepSeek 正常返回
    def fake_create(*args, **kwargs):

        chunks = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="Redis 故障，但 AI 仍然正常工作"
                        )
                    )
                ]
            )
        ]

        return iter(chunks)

    monkeypatch.setattr(
        ai.client.chat.completions,
        "create",
        fake_create
    )

    # 3. 避免测试时真正连接 Redis 写入
    monkeypatch.setattr(
        ai,
        "set_cache",
        lambda key, value, expire=600: False
    )

    # 4. 执行流式聊天，并捕获 Redis 日志
    with caplog.at_level(
        "ERROR",
        logger="redis_client"
    ):

        result = list(
            ai.chat_stream(
                "user004",
                "你好",
                cache_mode="context"
            )
        )

    # 5. 验证 AI 仍然正常返回
    assert result == [
        "Redis 故障，但 AI 仍然正常工作"
    ]

    # 6. 验证 Redis 异常日志
    assert "Redis 缓存读取失败" in caplog.text

    assert "模拟 Redis 连接失败" in caplog.text

    # 7. 验证 MySQL 仍然保存聊天记录
    db = test_db()

    try:

        messages = database.get_messages(
            db,
            "user004"
        )

        assert messages == [
            {
                "role": "user",
                "content": "你好"
            },
            {
                "role": "assistant",
                "content": "Redis 故障，但 AI 仍然正常工作"
            }
        ]

    finally:
        db.close()

    #测试流式回答出错时
def test_chat_stream_deepseek_failure(
    test_db,
    monkeypatch
):

    # 1. 模拟 Redis 缓存未命中
    monkeypatch.setattr(
        ai,
        "get_cache",
        lambda key: None
    )

    # 2. 模拟 DeepSeek 中途发生异常
    def fake_create(*args, **kwargs):

        def fake_response():

            # 第一块：正常生成
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="Python 是一种"
                        )
                    )
                ]
            )

            # 第二步：模拟模型服务故障
            raise RuntimeError(
                "模拟 DeepSeek 流式生成中断"
            )

        return fake_response()

    monkeypatch.setattr(
        ai.client.chat.completions,
        "create",
        fake_create
    )

    # 3. 记录 Redis 写入情况
    cache_writes = []

    def fake_set_cache(key, value, expire=600):

        cache_writes.append(value)

        return True

    monkeypatch.setattr(
        ai,
        "set_cache",
        fake_set_cache
    )

    # 4. 创建流式生成器
    stream = ai.chat_stream(
        "user005",
        "什么是 Python？",
        cache_mode="context"
    )

    # 5. 验证第一块内容正常返回
    first_chunk = next(stream)

    assert first_chunk == "Python 是一种"

    # 6. 验证第二次读取时发生异常
    with pytest.raises(
        RuntimeError,
        match="模拟 DeepSeek 流式生成中断"
    ):
        next(stream)

    # 7. 验证 Redis 没有保存半截答案
    assert cache_writes == []

    # 8. 验证 MySQL 没有保存半截 AI 回答
    db = test_db()

    try:

        messages = database.get_messages(
            db,
            "user005"
        )

        assert messages == [
            {
                "role": "user",
                "content": "什么是 Python？"
            }
        ]

    finally:
        db.close()


    #测试流式生成器的断开
def test_chat_stream_client_disconnect(
    test_db,
    monkeypatch
):

    # 1. 模拟 Redis 缓存未命中
    monkeypatch.setattr(
        ai,
        "get_cache",
        lambda key: None
    )


    # 记录资源清理的执行顺序
    lifecycle = []

    # 1. 模拟线程事件
    class FakeEvent:

        def __init__(self, name=None):
            self.value = False
            self.name = name

        def set(self):
            self.value = True

            if self.name:
                lifecycle.append(self.name)

        def is_set(self):
            return self.value

    # 停止续期事件
    stop_event = FakeEvent("renewal_stop")

    # 锁丢失事件
    lost_event = FakeEvent()

    # 2. 模拟后台续期线程
    class FakeThread:

        def __init__(self):
            self.joined = False

        def join(self):
            self.joined = True
            lifecycle.append("thread_join")

    fake_thread = FakeThread()

    # 3. 模拟启动自动续期线程
    def fake_start_lock_renewal(
        lock_key,
        lock_value,
        expire=120
    ):

        lifecycle.append("renewal_start")

        return (
            stop_event,
            fake_thread,
            lost_event
        )

    monkeypatch.setattr(
        ai,
        "start_lock_renewal",
        fake_start_lock_renewal
    )

    # 4. 模拟释放 Redis 锁
    release_calls = []

    def fake_release_lock(lock_key, lock_value):

        lifecycle.append("redis_lock_release")

        release_calls.append({
            "lock_key": lock_key,
            "lock_value": lock_value
        })

        return True

    monkeypatch.setattr(
        ai,
        "release_lock",
        fake_release_lock
    )

    # 2. 创建一个模拟的 DeepSeek 流
    class FakeResponse:

        def __init__(self):

            self.chunks = iter([
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="Python 是一种"
                            )
                        )
                    ]
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content="编程语言"
                            )
                        )
                    ]
                )
            ])

            self.closed = False

        def __iter__(self):
            return self

        def __next__(self):
            return next(self.chunks)

        def close(self):

            self.closed = True

            lifecycle.append("response_close")

    fake_response = FakeResponse()

    monkeypatch.setattr(
        ai.client.chat.completions,
        "create",
        lambda *args, **kwargs: fake_response
    )

    # 3. 记录 Redis 缓存写入
    cache_writes = []

    def fake_set_cache(key, value, expire=600):

        cache_writes.append(value)

        return True

    monkeypatch.setattr(
        ai,
        "set_cache",
        fake_set_cache
    )

    # 4. 创建流式生成器
    stream = ai.chat_stream(
        "user006",
        "什么是 Python？",
        cache_mode="context"
    )

    # 5. 获取第一块内容
    first_chunk = next(stream)

    assert first_chunk == "Python 是一种"

    # 6. 模拟用户中途断开连接
    stream.close()

    # 7. 验证 DeepSeek 流已经关闭
    assert fake_response.closed is True


    # 8. 验证自动续期线程收到了停止信号
    assert stop_event.is_set()

    # 9. 验证后台线程已经结束
    assert fake_thread.joined is True

    # 10. 验证 Redis 锁已经释放
    assert len(release_calls) == 1

    assert release_calls[0]["lock_value"] == "test-lock-token"

    # 11. 验证资源清理顺序
    assert lifecycle == [
        "renewal_start",
        "response_close",
        "renewal_stop",
        "thread_join",
        "redis_lock_release"
    ]

    # 8. 验证没有保存不完整答案到 Redis
    assert cache_writes == []

    # 9. 验证 MySQL 只保存了用户问题
    db = test_db()

    try:

        messages = database.get_messages(
            db,
            "user006"
        )

        assert messages == [
            {
                "role": "user",
                "content": "什么是 Python？"
            }
        ]

    finally:
        db.close()




    #当模型已经生成最后一个文本块，但是后台续期线程在结束过程中报告续期失败
def test_chat_stream_rejects_answer_when_lock_lost_at_end(
    test_db,
    monkeypatch
):

    # 1. 模拟 Redis 缓存未命中
    monkeypatch.setattr(
        ai,
        "get_cache",
        lambda key: None
    )

    lifecycle = []

    # 2. 模拟线程事件
    class FakeEvent:

        def __init__(self, name=None):
            self.value = False
            self.name = name

        def set(self):

            self.value = True

            if self.name:
                lifecycle.append(self.name)

        def is_set(self):
            return self.value

    stop_event = FakeEvent("stop")
    lost_event = FakeEvent()

    # 3. 模拟后台续期线程
    class FakeThread:

        def join(self):

            lifecycle.append("join")

            # 模拟后台线程在退出前发现续期失败
            lost_event.set()

    # 4. 模拟启动自动续期
    def fake_start_lock_renewal(
        lock_key,
        lock_value,
        expire=120
    ):

        lifecycle.append("start")

        return (
            stop_event,
            FakeThread(),
            lost_event
        )

    monkeypatch.setattr(
        ai,
        "start_lock_renewal",
        fake_start_lock_renewal
    )

    # 5. 模拟模型响应
    def make_chunk(content):

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=content
                    )
                )
            ]
        )

    class FakeResponse:

        closed = False

        def __iter__(self):

            yield make_chunk("这是模型生成的回答")

        def close(self):

            self.closed = True

    response = FakeResponse()

    monkeypatch.setattr(
        ai.client.chat.completions,
        "create",
        lambda *args, **kwargs: response
    )

    # 6. 锁丢失后不允许写入缓存
    monkeypatch.setattr(
        ai,
        "set_cache",
        lambda *args, **kwargs: pytest.fail(
            "锁丢失后不应该写入缓存"
        )
    )

    # 7. 记录锁释放
    def fake_release_lock(lock_key, lock_value):

        lifecycle.append("release")

        return True

    monkeypatch.setattr(
        ai,
        "release_lock",
        fake_release_lock
    )

    # 8. 执行流式聊天
    stream = ai.chat_stream(
        "user_lock_test",
        "测试锁续期失败",
        cache_mode="context"
    )

    # 最后一个文本块可以正常返回
    assert next(stream) == "这是模型生成的回答"

    # 模型结束后，等待续期线程时发现锁丢失
    with pytest.raises(
        RuntimeError,
        match="已经失效"
    ):
        next(stream)

    # 9. 验证模型连接已经关闭
    assert response.closed is True

    # 10. 验证线程停止和锁释放
    assert stop_event.is_set()

    assert lifecycle == [
        "start",
        "stop",
        "join",
        "release"
    ]

    # 11. 验证 MySQL 没有保存不完整的 AI 回答
    db = test_db()

    try:

        messages = database.get_messages(
            db,
            "user_lock_test"
        )

        assert messages == [
            {
                "role": "user",
                "content": "测试锁续期失败"
            }
        ]

    finally:

        db.close()
