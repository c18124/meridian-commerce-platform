    #测试商品管理操作函数的测试集
import pytest

from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, Product, ProductSKU

from product_service import (
    create_product,
    get_product_by_id,
    update_product,
    update_product_sku,
    delete_product,
    delete_product_sku
)


# ==================================================
# 一、测试数据库环境
# ==================================================

@pytest.fixture
def db_session(tmp_path):

    test_db_path = tmp_path / "test_products.db"

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

    db = TestingSessionLocal()

    try:
        yield db

    finally:
        db.close()
        test_engine.dispose()


# ==================================================
# 二、测试辅助函数
# ==================================================

def make_product(
    db,
    product_code="TEST-P001",
    sku_codes=None
):
    if sku_codes is None:
        sku_codes = [
            "TEST-SKU001",
            "TEST-SKU002"
        ]

    skus = []

    for index, sku_code in enumerate(sku_codes):

        skus.append({
            "sku_code": sku_code,
            "color": "红色" if index == 0 else "黑色",
            "size": "M" if index == 0 else "L",
            "price": "59.90" if index == 0 else "69.90",
            "stock": 100 if index == 0 else 80
        })

    return create_product(
        db=db,
        product_code=product_code,
        name="测试纯棉T恤",
        category="服装",
        description="自动化测试商品",
        skus=skus
    )


# ==================================================
# 三、商品创建与查询测试
# ==================================================

def test_create_product_and_get_by_id(db_session):

    product = make_product(db_session)

    found = get_product_by_id(
        db_session,
        product.id
    )

    assert found is not None
    assert found.product_code == "TEST-P001"
    assert found.name == "测试纯棉T恤"
    assert len(found.skus) == 2

    sku_codes = {
        sku.sku_code for sku in found.skus
    }

    assert sku_codes == {
        "TEST-SKU001",
        "TEST-SKU002"
    }

    assert all(
        sku.product_id == found.id
        for sku in found.skus
    )


def test_create_product_rejects_duplicate_product_code(db_session):

    make_product(db_session)

    with pytest.raises(ValueError, match="商品编号已经存在"):

        make_product(db_session)


def test_create_product_rejects_duplicate_sku_in_request(db_session):

    with pytest.raises(ValueError, match="本次提交存在重复 SKU 编号"):

        create_product(
            db=db_session,
            product_code="TEST-P002",
            name="重复 SKU 测试",
            skus=[
                {
                    "sku_code": "DUPLICATE-SKU",
                    "price": "59.90",
                    "stock": 10
                },
                {
                    "sku_code": "DUPLICATE-SKU",
                    "price": "69.90",
                    "stock": 20
                }
            ]
        )


def test_create_product_rejects_duplicate_sku_in_database(db_session):

    make_product(
        db_session,
        product_code="TEST-P001",
        sku_codes=["SHARED-SKU"]
    )

    with pytest.raises(ValueError, match="商品编号或 SKU 编号已经存在"):

        make_product(
            db_session,
            product_code="TEST-P002",
            sku_codes=["SHARED-SKU"]
        )


def test_create_product_rejects_empty_product_code(db_session):

    with pytest.raises(ValueError, match="商品编号不能为空"):

        create_product(
            db_session,
            "   ",
            "测试商品",
            skus=[{
                "sku_code": "TEST-SKU",
                "price": "59.90",
                "stock": 10
            }]
        )


def test_create_product_rejects_empty_name(db_session):

    with pytest.raises(ValueError, match="商品名称不能为空"):

        create_product(
            db_session,
            "TEST-P002",
            "   ",
            skus=[{
                "sku_code": "TEST-SKU",
                "price": "59.90",
                "stock": 10
            }]
        )


def test_create_product_rejects_empty_skus(db_session):

    with pytest.raises(ValueError, match="至少需要一个商品 SKU"):

        create_product(
            db_session,
            "TEST-P002",
            "测试商品",
            skus=[]
        )


@pytest.mark.parametrize(
    ("price", "expected_message"),
    [
        ("abc", "SKU 价格必须是有效数字"),
        ("-1", "SKU 价格不能为负数或无效数字"),
        ("NaN", "SKU 价格不能为负数或无效数字")
    ]
)
def test_create_product_rejects_invalid_price(
    db_session,
    price,
    expected_message
):

    with pytest.raises(ValueError, match=expected_message):

        create_product(
            db_session,
            "TEST-P002",
            "测试商品",
            skus=[{
                "sku_code": "TEST-SKU",
                "price": price,
                "stock": 10
            }]
        )


@pytest.mark.parametrize(
    ("stock", "expected_message"),
    [
        (-1, "库存不能小于 0"),
        (1.5, "库存必须是整数"),
        (True, "库存必须是整数")
    ]
)
def test_create_product_rejects_invalid_stock(
    db_session,
    stock,
    expected_message
):

    with pytest.raises(ValueError, match=expected_message):

        create_product(
            db_session,
            "TEST-P002",
            "测试商品",
            skus=[{
                "sku_code": "TEST-SKU",
                "price": "59.90",
                "stock": stock
            }]
        )


def test_get_product_by_id_returns_none(db_session):

    result = get_product_by_id(
        db_session,
        999
    )

    assert result is None


@pytest.mark.parametrize("product_id", [0, -1])
def test_get_product_by_id_rejects_invalid_id(
    db_session,
    product_id
):

    with pytest.raises(ValueError, match="商品 ID 必须大于 0"):

        get_product_by_id(
            db_session,
            product_id
        )


# ==================================================
# 四、商品基本信息更新测试
# ==================================================

def test_update_product_success(db_session):

    product = make_product(db_session)

    updated = update_product(
        db_session,
        product.id,
        {
            "name": "  夏季纯棉T恤  ",
            "category": " 夏季服装 ",
            "description": "  2027夏季新品  ",
            "is_active": False
        }
    )

    assert updated is not None
    assert updated.name == "夏季纯棉T恤"
    assert updated.category == "夏季服装"
    assert updated.description == "2027夏季新品"
    assert updated.is_active is False


def test_update_product_rejects_empty_updates(db_session):

    product = make_product(db_session)

    with pytest.raises(ValueError, match="更新内容不能为空"):

        update_product(
            db_session,
            product.id,
            {}
        )


def test_update_product_rejects_invalid_field(db_session):

    product = make_product(db_session)

    with pytest.raises(ValueError, match="不允许更新这些字段"):

        update_product(
            db_session,
            product.id,
            {
                "product_code": "NEW-CODE"
            }
        )


def test_update_product_rejects_empty_name(db_session):

    product = make_product(db_session)

    with pytest.raises(ValueError, match="商品名称不能为空"):

        update_product(
            db_session,
            product.id,
            {
                "name": "   "
            }
        )


def test_update_product_rejects_invalid_active_type(db_session):

    product = make_product(db_session)

    with pytest.raises(ValueError, match="商品状态必须是布尔值"):

        update_product(
            db_session,
            product.id,
            {
                "is_active": "false"
            }
        )


def test_update_product_returns_none_when_missing(db_session):

    result = update_product(
        db_session,
        999,
        {
            "name": "不存在的商品"
        }
    )

    assert result is None


def test_update_product_rejects_invalid_id(db_session):

    with pytest.raises(ValueError, match="商品 ID 必须大于 0"):

        update_product(
            db_session,
            0,
            {
                "name": "测试商品"
            }
        )


# ==================================================
# 五、SKU 信息更新测试
# ==================================================

def test_update_product_sku_success(db_session):

    product = make_product(db_session)

    sku = product.skus[0]

    updated = update_product_sku(
        db_session,
        sku.id,
        {
            "sku_code": "TEST-SKU001-NEW",
            "color": "深红色",
            "size": "XL",
            "price": "64.90",
            "stock": 120,
            "is_active": False
        }
    )

    assert updated is not None
    assert updated.sku_code == "TEST-SKU001-NEW"
    assert updated.color == "深红色"
    assert updated.size == "XL"
    assert updated.price == Decimal("64.90")
    assert updated.stock == 120
    assert updated.is_active is False


def test_update_product_sku_rejects_duplicate_code(db_session):

    product = make_product(db_session)

    sku1 = product.skus[0]
    sku2 = product.skus[1]

    with pytest.raises(ValueError, match="SKU 编号已经存在"):

        update_product_sku(
            db_session,
            sku1.id,
            {
                "sku_code": sku2.sku_code
            }
        )


@pytest.mark.parametrize(
    ("price", "expected_message"),
    [
        ("abc", "SKU 价格必须是有效数字"),
        ("-1", "SKU 价格不能为负数或无效数字"),
        ("1.234", "SKU 价格最多保留两位小数"),
        ("100000000", "SKU 价格超出允许范围")
    ]
)
def test_update_product_sku_rejects_invalid_price(
    db_session,
    price,
    expected_message
):

    product = make_product(db_session)
    sku = product.skus[0]

    with pytest.raises(ValueError, match=expected_message):

        update_product_sku(
            db_session,
            sku.id,
            {
                "price": price
            }
        )


@pytest.mark.parametrize(
    ("stock", "expected_message"),
    [
        (-1, "库存不能小于 0"),
        (1.5, "库存必须是整数"),
        (True, "库存必须是整数")
    ]
)
def test_update_product_sku_rejects_invalid_stock(
    db_session,
    stock,
    expected_message
):

    product = make_product(db_session)
    sku = product.skus[0]

    with pytest.raises(ValueError, match=expected_message):

        update_product_sku(
            db_session,
            sku.id,
            {
                "stock": stock
            }
        )


def test_update_product_sku_rejects_empty_code(db_session):

    product = make_product(db_session)
    sku = product.skus[0]

    with pytest.raises(ValueError, match="SKU 编号不能为空"):

        update_product_sku(
            db_session,
            sku.id,
            {
                "sku_code": "   "
            }
        )


def test_update_product_sku_rejects_invalid_field(db_session):

    product = make_product(db_session)
    sku = product.skus[0]

    with pytest.raises(ValueError, match="不允许更新这些字段"):

        update_product_sku(
            db_session,
            sku.id,
            {
                "product_id": 999
            }
        )


def test_update_product_sku_rejects_invalid_active_type(db_session):

    product = make_product(db_session)
    sku = product.skus[0]

    with pytest.raises(ValueError, match="SKU 状态必须是布尔值"):

        update_product_sku(
            db_session,
            sku.id,
            {
                "is_active": "false"
            }
        )


def test_update_product_sku_returns_none_when_missing(db_session):

    result = update_product_sku(
        db_session,
        999,
        {
            "stock": 100
        }
    )

    assert result is None


def test_update_product_sku_rejects_invalid_id(db_session):

    with pytest.raises(ValueError, match="SKU ID 必须大于 0"):

        update_product_sku(
            db_session,
            0,
            {
                "stock": 100
            }
        )


# ==================================================
# 六、商品删除测试
# ==================================================

def test_delete_product_deletes_all_skus(db_session):

    product = make_product(db_session)

    product_id = product.id

    sku_ids = [
        sku.id for sku in product.skus
    ]

    result = delete_product(
        db_session,
        product_id
    )

    assert result is True

    assert db_session.get(
        Product,
        product_id
    ) is None

    for sku_id in sku_ids:

        assert db_session.get(
            ProductSKU,
            sku_id
        ) is None


def test_delete_product_returns_false_when_missing(db_session):

    result = delete_product(
        db_session,
        999
    )

    assert result is False


def test_delete_product_rejects_invalid_id(db_session):

    with pytest.raises(ValueError, match="商品 ID 必须大于 0"):

        delete_product(
            db_session,
            0
        )


# ==================================================
# 七、SKU 删除测试
# ==================================================

def test_delete_product_sku_only_deletes_target_sku(db_session):

    product = make_product(db_session)

    product_id = product.id

    sku1 = product.skus[0]
    sku2 = product.skus[1]

    sku1_id = sku1.id
    sku2_id = sku2.id

    result = delete_product_sku(
        db_session,
        sku1_id
    )

    assert result is True

    assert db_session.get(
        Product,
        product_id
    ) is not None

    assert db_session.get(
        ProductSKU,
        sku1_id
    ) is None

    assert db_session.get(
        ProductSKU,
        sku2_id
    ) is not None


def test_delete_product_sku_returns_false_when_missing(db_session):

    result = delete_product_sku(
        db_session,
        999
    )

    assert result is False


def test_delete_product_sku_rejects_invalid_id(db_session):

    with pytest.raises(ValueError, match="SKU ID 必须大于 0"):

        delete_product_sku(
            db_session,
            0
        )
