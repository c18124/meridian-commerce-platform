import uuid
import pytest

from redis_client import redis_client
from redis_bloom_filter import RedisBloomFilter

import redis_bloom_filter
from redis.exceptions import RedisError

    #夹具函数为测试函数做好前置工作
@pytest.fixture
def redis_bloom():
    # 创建唯一 Redis Key，避免测试之间互相影响
    key = f"test:bloom:{uuid.uuid4().hex}"

    bf = RedisBloomFilter(
        capacity=1000,
        error_rate=0.01,
        key=key
    )

    yield bf

    # 测试结束后清理 Redis 数据
    redis_client.delete(
        key,
        f"{key}:meta"
    )


def test_redis_bloom_add_and_contains(redis_bloom):

    redis_bloom.add("python_notes.txt")

    assert redis_bloom.contains("python_notes.txt") is True


def test_redis_bloom_empty_filter_returns_false(redis_bloom):

    assert redis_bloom.contains("unknown_document.txt") is False

    #测试模拟两个fastapi实例能不能共通位组
def test_two_instances_share_data(redis_bloom):

    # 第一个实例添加文档
    redis_bloom.add("shared_document.txt")

    # 创建第二个实例，使用相同 Redis Key
    second = RedisBloomFilter(
        capacity=1000,
        error_rate=0.01,
        key=redis_bloom.key
    )

    # 第二个实例应该能够查询到
    assert second.contains("shared_document.txt") is True

    #测试capacity等元数据不同时能不能报错
def test_redis_bloom_rejects_config_mismatch(redis_bloom):

    with pytest.raises(ValueError):

        RedisBloomFilter(
            capacity=2000,
            error_rate=0.01,
            key=redis_bloom.key
        )

    #测试当id写入redis故障时
def test_add_returns_false_when_redis_fails(
    redis_bloom, monkeypatch
):

    def fake_pipeline(*args, **kwargs):
        raise RedisError("模拟 Redis 故障")

    monkeypatch.setattr(
        redis_bloom_filter.redis_client,
        "pipeline",
        fake_pipeline
    )

    result = redis_bloom.add("failure_test.txt")

    assert result is False

    #测试redis查询故障时放行，故障降级
def test_contains_fails_open_when_redis_fails(
    redis_bloom, monkeypatch
):

    def fake_pipeline(*args, **kwargs):
        raise RedisError("模拟 Redis 故障")

    monkeypatch.setattr(
        redis_bloom_filter.redis_client,
        "pipeline",
        fake_pipeline
    )

    result = redis_bloom.contains("failure_test.txt")

    assert result is True
