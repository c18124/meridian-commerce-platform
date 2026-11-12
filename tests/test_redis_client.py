    #测试redis缓存的基础函数的测试集
import redis_client as cache_module

    #测试redis key的写入操作，和随机TTL
def test_set_cache_uses_randomized_ttl(monkeypatch):

    # 1. 用于记录 Redis 实际收到的参数
    captured = {}

    # 2. 模拟 Redis SET 命令
    def fake_set(key, value, ex):

        captured["key"] = key
        captured["value"] = value
        captured["expire"] = ex

        return True

    # 3. 模拟随机数生成
    def fake_randint(min_value, max_value):

        assert min_value == 540
        assert max_value == 660

        return 630

    # 4. 替换真实 Redis SET
    monkeypatch.setattr(
        cache_module.redis_client,
        "set",
        fake_set
    )

    # 5. 替换随机数函数
    monkeypatch.setattr(
        cache_module.random,
        "randint",
        fake_randint
    )

    # 6. 调用真实缓存写入函数
    result = cache_module.set_cache(
        "test:cache",
        "hello",
        expire=600
    )

    # 7. 验证写入结果
    assert result is True

    # 8. 验证实际传入 Redis 的 TTL
    assert captured["expire"] == 630

    assert captured["key"] == "test:cache"
    assert captured["value"] == "hello"
