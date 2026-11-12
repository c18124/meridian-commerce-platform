    #第一部分：测试 Redis 缓存模块自身。
    #第二部分：测试商品 API 是否真正使用缓存，以及修改数据后是否自动失效。
import pytest

from redis.exceptions import RedisError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import api
import product_cache

from database import Base, get_db


# ==================================================
# 第一部分：Redis 缓存模块测试
# ==================================================


@pytest.fixture
def memory_cache(monkeypatch):
    """使用内存字典模拟 Redis"""

    storage = {}
    ttls = {}

    def fake_get(key):
        return storage.get(key)

    def fake_set(key, value, expire=600):
        storage[key] = value
        ttls[key] = expire
        return True

    def fake_delete(key):
        existed = key in storage
        storage.pop(key, None)
        return int(existed)

    monkeypatch.setattr(
        product_cache,
        "get_cache",
        fake_get
    )

    monkeypatch.setattr(
        product_cache,
        "set_cache",
        fake_set
    )

    monkeypatch.setattr(
        product_cache,
        "delete_cache",
        fake_delete
    )

    return storage, ttls


def test_product_detail_cache_round_trip(memory_cache):
    """商品详情缓存写入和读取"""

    storage, ttls = memory_cache

    data = {
        "id": 1,
        "name": "测试商品",
        "category": "服装"
    }

    result = product_cache.set_product_detail_cache(
        1,
        data,
        version=2
    )

    assert result is True

    cached = product_cache.get_product_detail_cache(
        1,
        version=2
    )

    assert cached == data

    assert list(ttls.values()) == [
        product_cache.PRODUCT_DETAIL_CACHE_TTL
    ]


def test_product_list_cache_round_trip(memory_cache):
    """商品列表缓存写入和读取"""

    data = {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 20
    }

    product_cache.set_product_list_cache(
        1,
        20,
        data,
        version=1
    )

    cached = product_cache.get_product_list_cache(
        1,
        20,
        version=1
    )

    assert cached == data


def test_product_list_cache_separates_pages(memory_cache):
    """不同分页参数不能共用缓存"""

    data1 = {
        "items": [{"id": 1}],
        "total": 30,
        "page": 1,
        "page_size": 10
    }

    data2 = {
        "items": [{"id": 11}],
        "total": 30,
        "page": 2,
        "page_size": 10
    }

    product_cache.set_product_list_cache(
        1, 10, data1, 1
    )

    product_cache.set_product_list_cache(
        2, 10, data2, 1
    )

    assert product_cache.get_product_list_cache(
        1, 10, 1
    ) == data1

    assert product_cache.get_product_list_cache(
        2, 10, 1
    ) == data2


def test_corrupted_cache_is_deleted(memory_cache):
    """损坏的 JSON 缓存应该被删除"""

    storage, _ = memory_cache

    key = "cache:products:v2:detail:10"

    storage[key] = "{invalid-json"

    result = product_cache.get_product_detail_cache(
        10,
        version=2
    )

    assert result is None

    assert key not in storage


def test_cache_version_defaults_to_zero(memory_cache):
    """没有缓存版本号时默认返回 0"""

    assert product_cache.get_product_cache_version() == 0


def test_cache_invalidation_increments_version(
    memory_cache,
    monkeypatch
):
    """商品缓存失效时版本号递增"""

    storage, _ = memory_cache

    class FakeRedis:

        def incr(self, key):

            current = int(
                storage.get(key, "0")
            )

            current += 1

            storage[key] = str(current)

            return current

    monkeypatch.setattr(
        product_cache,
        "redis_client",
        FakeRedis()
    )

    assert product_cache.get_product_cache_version() == 0

    assert product_cache.invalidate_product_cache() is True

    assert product_cache.get_product_cache_version() == 1

    assert product_cache.invalidate_product_cache() is True

    assert product_cache.get_product_cache_version() == 2


def test_old_cache_is_unreachable_after_invalidation(
    memory_cache,
    monkeypatch
):
    """版本更新后旧缓存不再被读取"""

    storage, _ = memory_cache

    product_cache.set_product_detail_cache(
        10,
        {"id": 10, "name": "旧商品"},
        version=0
    )

    class FakeRedis:

        def incr(self, key):

            version = int(storage.get(key, "0")) + 1

            storage[key] = str(version)

            return version

    monkeypatch.setattr(
        product_cache,
        "redis_client",
        FakeRedis()
    )

    product_cache.invalidate_product_cache()

    assert product_cache.get_product_detail_cache(
        10,
        version=1
    ) is None


def test_redis_failure_does_not_crash_invalidation(
    monkeypatch
):
    """Redis 不可用时缓存失效函数不向外抛异常"""

    class BrokenRedis:

        def incr(self, key):
            raise RedisError("Redis unavailable")

    monkeypatch.setattr(
        product_cache,
        "redis_client",
        BrokenRedis()
    )

    result = product_cache.invalidate_product_cache()

    assert result is False


# ==================================================
# 第二部分：商品 API 缓存集成测试
# ==================================================


@pytest.fixture
def client(tmp_path):
    """创建独立 SQLite 测试数据库"""

    test_db_path = tmp_path / "test_product_cache.db"

    test_engine = create_engine(
        f"sqlite:///{test_db_path}",
        connect_args={"check_same_thread": False}
    )

    Base.metadata.create_all(test_engine)

    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False
    )

    def override_get_db():

        db = TestingSessionLocal()

        try:
            yield db

        finally:
            db.close()

    api.app.dependency_overrides[get_db] = override_get_db

    try:

        with TestClient(api.app) as test_client:
            yield test_client

    finally:

        api.app.dependency_overrides.pop(
            get_db,
            None
        )

        test_engine.dispose()


@pytest.fixture
def fake_product_cache(monkeypatch):
    """使用内存缓存模拟商品 Redis 缓存"""

    state = {
        "version": 0,
        "details": {},
        "lists": {}
    }

    def get_version():
        return state["version"]

    def get_detail(product_id, version):
        return state["details"].get(
            (version, product_id)
        )

    def set_detail(product_id, data, version):
        state["details"][
            (version, product_id)
        ] = data

        return True

    def get_list(page, page_size, version):
        return state["lists"].get(
            (version, page, page_size)
        )

    def set_list(page, page_size, data, version):
        state["lists"][
            (version, page, page_size)
        ] = data

        return True

    def invalidate():
        state["version"] += 1
        return True

    monkeypatch.setattr(
        api,
        "get_product_cache_version",
        get_version
    )

    monkeypatch.setattr(
        api,
        "get_product_detail_cache",
        get_detail
    )

    monkeypatch.setattr(
        api,
        "set_product_detail_cache",
        set_detail
    )

    monkeypatch.setattr(
        api,
        "get_product_list_cache",
        get_list
    )

    monkeypatch.setattr(
        api,
        "set_product_list_cache",
        set_list
    )

    monkeypatch.setattr(
        api,
        "invalidate_product_cache",
        invalidate
    )

    return state


def create_test_product(client, code):
    """创建用于缓存测试的商品"""

    response = client.post(
        "/products",
        json={
            "product_code": code,
            "name": "缓存测试商品",
            "category": "测试分类",
            "description": "商品缓存测试",
            "skus": [
                {
                    "sku_code": f"{code}-SKU001",
                    "color": "黑色",
                    "size": "M",
                    "price": "59.90",
                    "stock": 100
                }
            ]
        }
    )

    assert response.status_code == 201, response.text

    return response.json()


def test_product_detail_cache_hit_and_sku_update_invalidates(
    client,
    monkeypatch,
    fake_product_cache
):
    """详情缓存命中，以及 SKU 更新后缓存失效"""

    product = create_test_product(
        client,
        "CACHE-P001"
    )

    calls = {"count": 0}

    original_service = api.get_product_by_id_service

    def counted_service(db, product_id):

        calls["count"] += 1

        return original_service(
            db,
            product_id
        )

    monkeypatch.setattr(
        api,
        "get_product_by_id_service",
        counted_service
    )

    product_id = product["id"]

    # 第一次请求：查询 MySQL
    first = client.get(
        f"/products/{product_id}"
    )

    assert first.status_code == 200

    assert calls["count"] == 1

    # 第二次请求：读取缓存
    second = client.get(
        f"/products/{product_id}"
    )

    assert second.status_code == 200

    assert calls["count"] == 1

    assert first.json() == second.json()

    # 修改 SKU 价格
    sku_id = product["skus"][0]["id"]

    update_response = client.patch(
        f"/products/skus/{sku_id}",
        json={
            "price": "79.90"
        }
    )

    assert update_response.status_code == 200

    # 再次请求：缓存版本已改变，重新查询 MySQL
    third = client.get(
        f"/products/{product_id}"
    )

    assert third.status_code == 200

    assert calls["count"] == 2

    assert float(
        third.json()["skus"][0]["price"]
    ) == 79.90


def test_product_list_cache_hit_and_update_invalidates(
    client,
    monkeypatch,
    fake_product_cache
):
    """商品列表缓存命中，以及商品更新后缓存失效"""

    product = create_test_product(
        client,
        "CACHE-P002"
    )

    calls = {"count": 0}

    original_service = api.list_products_service

    def counted_service(db, page, page_size):

        calls["count"] += 1

        return original_service(
            db,
            page,
            page_size
        )

    monkeypatch.setattr(
        api,
        "list_products_service",
        counted_service
    )

    # 第一次请求：查询 MySQL
    first = client.get(
        "/products?page=1&page_size=20"
    )

    assert first.status_code == 200

    assert calls["count"] == 1

    # 第二次请求：读取缓存
    second = client.get(
        "/products?page=1&page_size=20"
    )

    assert second.status_code == 200

    assert calls["count"] == 1

    assert first.json() == second.json()

    # 修改商品基本信息
    product_id = product["id"]

    update_response = client.patch(
        f"/products/{product_id}",
        json={
            "name": "更新后的缓存测试商品"
        }
    )

    assert update_response.status_code == 200

    # 再次请求：缓存失效，重新查询 MySQL
    third = client.get(
        "/products?page=1&page_size=20"
    )

    assert third.status_code == 200

    assert calls["count"] == 2

    assert third.json()["items"][0]["name"] == (
        "更新后的缓存测试商品"
    )
