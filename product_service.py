    #专门负责商品相关的数据库业务操作
"""商品业务服务模块"""

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from database import Product, ProductSKU

    #向数据库中增加商品信息
def create_product(
    db: Session,
    product_code: str, #商品编号
    name: str,
    skus: list[dict[str, Any]],
    category: str | None = None,
    description: str | None = None
) -> Product:

    # 1. 基础数据检查
    product_code = product_code.strip()
    name = name.strip()

    if not product_code:
        raise ValueError("商品编号不能为空")

    if not name:
        raise ValueError("商品名称不能为空")

    if not skus:
        raise ValueError("至少需要一个商品 SKU")

    # 2. 检查商品编号是否已经存在
    existing_id = db.scalar(
        select(Product.id).where(
            Product.product_code == product_code
        )
    )

    if existing_id is not None:
        raise ValueError("商品编号已经存在")

    # 3. 准备 SKU 对象
    sku_objects = []
    seen_sku_codes = set()

    for sku_data in skus:

        sku_code = str(
            sku_data.get("sku_code", "")
        ).strip()

        if not sku_code:
            raise ValueError("SKU 编号不能为空")

        if sku_code in seen_sku_codes:
            raise ValueError("本次提交存在重复 SKU 编号")

        seen_sku_codes.add(sku_code)

        # 金额使用 Decimal，避免浮点精度问题
        try:
            price = Decimal(str(sku_data["price"]))
        except (InvalidOperation, TypeError, ValueError, KeyError) as exc:
            raise ValueError("SKU 价格必须是有效数字") from exc

        if not price.is_finite() or price < 0:
            raise ValueError("SKU 价格不能为负数或无效数字")

        stock = sku_data.get("stock", 0)

        if isinstance(stock, bool) or not isinstance(stock, int):
            raise ValueError("库存必须是整数")

        if stock < 0:
            raise ValueError("库存不能小于 0")

        sku = ProductSKU(
            sku_code=sku_code,
            color=sku_data.get("color"),
            size=sku_data.get("size"),
            price=price,
            stock=stock,
            is_active=sku_data.get("is_active", True)
        )

        sku_objects.append(sku)

    # 4. 创建商品对象，并关联 SKU
    product = Product(
        product_code=product_code,
        name=name,
        category=category,
        description=description,
        skus=sku_objects
    )

    # 5. 保存到 MySQL
    try:
        db.add(product)

        db.commit()

        db.refresh(product)

        for sku in product.skus:
            db.refresh(sku)

        return product

    except IntegrityError as exc:
        db.rollback()
        raise ValueError(
            "商品编号或 SKU 编号已经存在"
        ) from exc

    except Exception:
        db.rollback()
        raise



        #查询商品
def get_product_by_id(
    db: Session,
    product_id: int
) -> Product | None:

    # 1. 检查商品 ID
    if product_id <= 0:
        raise ValueError("商品 ID 必须大于 0")

    # 2. 根据主键查询商品
    product = db.get(Product, product_id)

    # 3. 返回商品对象
    return product




# 更新商品基本信息 product主表
def update_product(
    db: Session,
    product_id: int,
    updates: dict[str, Any]
) -> Product | None:

    # 1. 检查商品 ID
    if product_id <= 0:
        raise ValueError("商品 ID 必须大于 0")

    # 2. 检查更新内容
    if not updates:
        raise ValueError("更新内容不能为空")

    # 3. 只允许修改指定字段
    allowed_fields = {
        "name",
        "category",
        "description",
        "is_active"
    }

    invalid_fields = set(updates) - allowed_fields

    if invalid_fields:
        raise ValueError(
            f"不允许更新这些字段：{invalid_fields}"
        )

    # 4. 根据商品 ID 查询商品
    product = db.get(Product, product_id)

    if product is None:
        return None

    # 5. 校验准备更新的数据
    validated_updates = {}

    for field, value in updates.items():

        if field == "name":

            if not isinstance(value, str):
                raise ValueError("商品名称必须是字符串")

            value = value.strip()

            if not value:
                raise ValueError("商品名称不能为空")

        elif field in ("category", "description"):

            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field} 必须是字符串或 None")

            if isinstance(value, str):
                value = value.strip()

        elif field == "is_active":

            if not isinstance(value, bool):
                raise ValueError("商品状态必须是布尔值")

        validated_updates[field] = value

    # 6. 修改商品对象
    try:

        for field, value in validated_updates.items():
            setattr(product, field, value)

        # 7. 提交事务
        db.commit()

        # 8. 刷新商品对象
        db.refresh(product)

        return product

    except Exception:
        db.rollback()
        raise





# 只更新商品 下的单独的一个 SKU
def update_product_sku(
    db: Session,
    sku_id: int,
    updates: dict[str, Any]
) -> ProductSKU | None:

    # 1. 检查 SKU ID
    if sku_id <= 0:
        raise ValueError("SKU ID 必须大于 0")

    # 2. 检查更新内容
    if not updates:
        raise ValueError("更新内容不能为空")

    # 3. 允许更新的字段
    allowed_fields = {
        "sku_code",
        "color",
        "size",
        "price",
        "stock",
        "is_active"
    }

    invalid_fields = set(updates) - allowed_fields

    if invalid_fields:
        raise ValueError(
            f"不允许更新这些字段：{invalid_fields}"
        )

    # 4. 根据 SKU ID 查询
    sku = db.get(ProductSKU, sku_id)

    if sku is None:
        return None

    # 5. 校验更新数据
    validated_updates = {}

    for field, value in updates.items():

        if field == "sku_code":

            if not isinstance(value, str):
                raise ValueError("SKU 编号必须是字符串")

            value = value.strip()

            if not value:
                raise ValueError("SKU 编号不能为空")

            existing_id = db.scalar(
                select(ProductSKU.id).where(
                    ProductSKU.sku_code == value,
                    ProductSKU.id != sku_id
                )
            )

            if existing_id is not None:
                raise ValueError("SKU 编号已经存在")

        elif field in ("color", "size"):

            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field} 必须是字符串或 None")

            if isinstance(value, str):
                value = value.strip() or None

        elif field == "price":

            try:
                value = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError("SKU 价格必须是有效数字") from exc

            if not value.is_finite() or value < 0:
                raise ValueError("SKU 价格不能为负数或无效数字")

            if value > Decimal("99999999.99"):
                raise ValueError("SKU 价格超出允许范围")

            if value.quantize(Decimal("0.01")) != value:
                raise ValueError("SKU 价格最多保留两位小数")

        elif field == "stock":

            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("库存必须是整数")

            if value < 0:
                raise ValueError("库存不能小于 0")

        elif field == "is_active":

            if not isinstance(value, bool):
                raise ValueError("SKU 状态必须是布尔值")

        validated_updates[field] = value

    # 6. 修改 SKU 对象
    try:

        for field, value in validated_updates.items():
            setattr(sku, field, value)

        # 7. 提交事务
        db.commit()

        # 8. 刷新对象
        db.refresh(sku)

        return sku

    except IntegrityError as exc:
        db.rollback()
        raise ValueError("SKU 编号已经存在") from exc

    except Exception:
        db.rollback()
        raise








# 删除整个商品
def delete_product(
    db: Session,
    product_id: int
) -> bool:

    # 1. 检查商品 ID
    if product_id <= 0:
        raise ValueError("商品 ID 必须大于 0")

    # 2. 查询商品
    product = db.get(Product, product_id)

    # 3. 判断商品是否存在
    if product is None:
        return False

    # 4. 删除商品
    try:
        db.delete(product)

        # 5. 提交事务
        db.commit()

        return True

    except Exception:
        db.rollback()
        raise




# 删除指定 SKU
def delete_product_sku(
    db: Session,
    sku_id: int
) -> bool:

    # 1. 检查 SKU ID
    if sku_id <= 0:
        raise ValueError("SKU ID 必须大于 0")

    # 2. 查询 SKU
    sku = db.get(ProductSKU, sku_id)

    # 3. 判断是否存在
    if sku is None:
        return False

    try:

        # 4. 获取所属商品
        product = sku.product

        # 5. 从商品的 SKU 集合中移除
        product.skus.remove(sku)

        # 6. 提交事务
        # delete-orphan 会自动删除被移除的 SKU
        db.commit()

        return True

    except Exception:
        db.rollback()
        raise





# 查询商品列表，支持分页
def list_products(
    db: Session,
    page: int = 1,
    page_size: int = 20
) -> tuple[list[Product], int]:

    # 1. 检查分页参数
    if page <= 0:
        raise ValueError("页码必须大于 0")

    if page_size <= 0 or page_size > 100:
        raise ValueError("每页数量必须在 1 到 100 之间")

    # 2. 查询商品总数量
    total = db.scalar(
        select(func.count(Product.id))
    ) or 0

    # 3. 计算分页偏移量
    offset = (page - 1) * page_size

    # 4. 查询当前页商品，同时加载 SKU
    stmt = (
        select(Product)
        .options(selectinload(Product.skus))
        .order_by(Product.id.desc())
        .offset(offset)
        .limit(page_size)
    )

    # 5. 执行查询
    products = db.scalars(stmt).all()

    # 6. 返回商品列表和总数量
    return products, total
