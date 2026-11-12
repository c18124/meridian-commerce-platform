    #给 分布式锁 编写的自动化测试集
import pytest

from redis.exceptions import RedisError

import redis_lock

    #测试获取锁
def test_acquire_lock_success(monkeypatch):

    captured = {}

    def fake_set(key, value, nx, ex):

        captured["key"] = key
        captured["value"] = value
        captured["nx"] = nx
        captured["ex"] = ex

        return True

    monkeypatch.setattr(
        redis_lock.redis_client,
        "set",
        fake_set
    )

    lock_value = redis_lock.acquire_lock(
        "lock:test",
        expire=120
    )

    assert lock_value is not None
    assert captured["key"] == "lock:test"
    assert captured["value"] == lock_value
    assert captured["nx"] is True
    assert captured["ex"] == 120


    #测试2当锁已经被占用
def test_acquire_lock_returns_none_when_occupied(monkeypatch):

    monkeypatch.setattr(
        redis_lock.redis_client,
        "set",
        lambda *args, **kwargs: None
    )

    result = redis_lock.acquire_lock(
        "lock:test"
    )

    assert result is None

    #获取锁失败
def test_acquire_lock_redis_failure(monkeypatch):

    def fake_set(*args, **kwargs):
        raise RedisError("Redis unavailable")

    monkeypatch.setattr(
        redis_lock.redis_client,
        "set",
        fake_set
    )
        #预期这段代码会抛出指定异常
    with pytest.raises(RedisError):
        redis_lock.acquire_lock("lock:test")

    #测试锁释放成功
def test_release_lock_success(monkeypatch):

    captured = {}

    def fake_eval(script, numkeys, key, value):

        captured["script"] = script
        captured["numkeys"] = numkeys
        captured["key"] = key
        captured["value"] = value

        return 1

    monkeypatch.setattr(
        redis_lock.redis_client,
        "eval",
        fake_eval
    )

    result = redis_lock.release_lock(
        "lock:test",
        "abc123"
    )

    assert result is True
    assert captured["numkeys"] == 1
    assert captured["key"] == "lock:test"
    assert captured["value"] == "abc123"
    assert "GET" in captured["script"]
    assert "DEL" in captured["script"]

    #测试不能删除其他人的锁
def test_release_lock_does_not_delete_other_lock(monkeypatch):

    monkeypatch.setattr(
        redis_lock.redis_client,
        "eval",
        lambda *args: 0
    )

    result = redis_lock.release_lock(
        "lock:test",
        "old_token"
    )

    assert result is False


    #测试释放锁时 Redis 故障
def test_release_lock_redis_failure(monkeypatch):

    def fake_eval(*args):
        raise RedisError("Redis unavailable")

    monkeypatch.setattr(
        redis_lock.redis_client,
        "eval",
        fake_eval
    )

    result = redis_lock.release_lock(
        "lock:test",
        "abc123"
    )

    assert result is False



@pytest.mark.parametrize(
    "expire",
    [0, -1, True, 1.5]
)


def test_acquire_lock_rejects_invalid_expire(expire):

    with pytest.raises(ValueError):
        redis_lock.acquire_lock(
            "lock:test",
            expire=expire
        )
