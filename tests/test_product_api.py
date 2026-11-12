    #测试商品 API 接口的自动化测试集
import pytest

from decimal import Decimal
from fastapi.testclient import TestClient

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api import app
from database import Base, get_db


# ==================================================
# 一、创建独立测试数据库
# ==================================================

@pytest.fixture
def client(tmp_path):

    test_db_path = tmp_path / "test_product_api.db"

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

    # 替换正式数据库依赖
    def override_get_db():

        db = TestingSessionLocal()

        try:
            yield db

        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:

        with TestClient(app) as test_client:
            yield test_client

    finally:

        app.dependency_overrides.pop(get_db, None)

        test_engine.dispose()


# ==================================================
# 二、测试辅助函数
# ==================================================

def create_test_product(
    client,
    product_code="API-P001",
    sku_codes=None
):

    if sku_codes is None:
        sku_codes = [
            "API-SKU001",
            "API-SKU002"
        ]

    payload = {
        "product_code": product_code,
        "name": "测试纯棉T恤",
        "category": "服装",
        "description": "API 自动化测试商品",
        "skus": [
            {
                "sku_code": sku_codes[0],
                "color": "红色",
                "size": "M",
                "price": "59.90",
                "stock": 100
            },
            {
                "sku_code": sku_codes[1],
                "color": "黑色",
                "size": "L",
                "price": "69.90",
                "stock": 80
            }
        ]
    }

    response = client.post(
        "/products",
        json=payload
    )

    assert response.status_code == 201, response.text

    return response.json()


# ==================================================
# 三、商品创建接口测试
# ==================================================

def test_create_product_api(client):

    response = client.post(
        "/products",
        json={
            "product_code": "API-P001",
            "name": "测试T恤",
            "category": "服装",
            "description": "测试商品",
            "skus": [
                {
                    "sku_code": "API-SKU001",
                    "color": "红色",
                    "size": "M",
                    "price": "59.90",
                    "stock": 100
                }
            ]
        }
    )

    assert response.status_code == 201

    data = response.json()

    assert data["product_code"] == "API-P001"
    assert data["name"] == "测试T恤"
    assert len(data["skus"]) == 1

    assert Decimal(
        str(data["skus"][0]["price"])
    ) == Decimal("59.90")


def test_create_product_duplicate_code(client):

    create_test_product(client)

    response = client.post(
        "/products",
        json={
            "product_code": "API-P001",
            "name": "重复商品",
            "skus": [
                {
                    "sku_code": "API-NEW-SKU",
                    "price": "39.90",
                    "stock": 10
                }
            ]
        }
    )

    assert response.status_code == 400


def test_create_product_invalid_payload(client):

    response = client.post(
        "/products",
        json={
            "product_code": "API-P002",
            "name": "测试商品",
            "skus": []
        }
    )

    assert response.status_code == 422


# ==================================================
# 四、商品列表和详情接口测试
# ==================================================

def test_list_products_api(client):

    create_test_product(
        client,
        "API-P001",
        ["API-SKU001", "API-SKU002"]
    )

    create_test_product(
        client,
        "API-P002",
        ["API-SKU003", "API-SKU004"]
    )

    response = client.get(
        "/products?page=1&page_size=10"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 10


def test_list_products_pagination(client):

    create_test_product(
        client,
        "API-P001",
        ["API-SKU001", "API-SKU002"]
    )

    create_test_product(
        client,
        "API-P002",
        ["API-SKU003", "API-SKU004"]
    )

    response = client.get(
        "/products?page=1&page_size=1"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 2
    assert len(data["items"]) == 1


def test_list_products_rejects_invalid_page(client):

    response = client.get(
        "/products?page=0&page_size=10"
    )

    assert response.status_code == 422


def test_get_product_detail_api(client):

    product = create_test_product(client)

    response = client.get(
        f"/products/{product['id']}"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["product_code"] == "API-P001"
    assert len(data["skus"]) == 2


def test_get_missing_product_returns_404(client):

    response = client.get(
        "/products/999"
    )

    assert response.status_code == 404


# ==================================================
# 五、商品更新接口测试
# ==================================================

def test_update_product_api(client):

    product = create_test_product(client)

    response = client.patch(
        f"/products/{product['id']}",
        json={
            "name": "夏季新款T恤",
            "category": "夏季服装",
            "is_active": False
        }
    )

    assert response.status_code == 200

    data = response.json()

    assert data["name"] == "夏季新款T恤"
    assert data["category"] == "夏季服装"
    assert data["is_active"] is False


def test_update_product_empty_body(client):

    product = create_test_product(client)

    response = client.patch(
        f"/products/{product['id']}",
        json={}
    )

    assert response.status_code == 400


def test_update_product_unknown_field(client):

    product = create_test_product(client)

    response = client.patch(
        f"/products/{product['id']}",
        json={
            "unknown_field": "test"
        }
    )

    assert response.status_code == 422


# ==================================================
# 六、SKU 更新接口测试
# ==================================================

def test_update_product_sku_api(client):

    product = create_test_product(client)

    sku_id = product["skus"][0]["id"]

    response = client.patch(
        f"/products/skus/{sku_id}",
        json={
            "price": "64.90",
            "stock": 120,
            "color": "深红色"
        }
    )

    assert response.status_code == 200

    data = response.json()

    assert Decimal(
        str(data["price"])
    ) == Decimal("64.90")

    assert data["stock"] == 120
    assert data["color"] == "深红色"


def test_update_product_sku_duplicate_code(client):

    product = create_test_product(client)

    sku1_id = product["skus"][0]["id"]
    sku2_code = product["skus"][1]["sku_code"]

    response = client.patch(
        f"/products/skus/{sku1_id}",
        json={
            "sku_code": sku2_code
        }
    )

    assert response.status_code == 400


def test_update_product_sku_invalid_price(client):

    product = create_test_product(client)

    sku_id = product["skus"][0]["id"]

    response = client.patch(
        f"/products/skus/{sku_id}",
        json={
            "price": "-10"
        }
    )

    assert response.status_code == 422


def test_update_missing_sku_returns_404(client):

    response = client.patch(
        "/products/skus/999",
        json={
            "stock": 100
        }
    )

    assert response.status_code == 404


# ==================================================
# 七、商品和 SKU 删除接口测试
# ==================================================

def test_delete_product_sku_api(client):

    product = create_test_product(client)

    product_id = product["id"]

    sku1_id = product["skus"][0]["id"]

    response = client.delete(
        f"/products/skus/{sku1_id}"
    )

    assert response.status_code == 200

    # 再次查询商品
    detail = client.get(
        f"/products/{product_id}"
    )

    assert detail.status_code == 200

    # 商品仍然存在，但只剩一个 SKU
    assert len(detail.json()["skus"]) == 1


def test_delete_product_api(client):

    product = create_test_product(client)

    product_id = product["id"]

    response = client.delete(
        f"/products/{product_id}"
    )

    assert response.status_code == 200

    # 验证商品已经删除
    detail = client.get(
        f"/products/{product_id}"
    )

    assert detail.status_code == 404


def test_delete_missing_product_returns_404(client):

    response = client.delete(
        "/products/999"
    )

    assert response.status_code == 404


def test_delete_missing_sku_returns_404(client):

    response = client.delete(
        "/products/skus/999"
    )

    assert response.status_code == 404
