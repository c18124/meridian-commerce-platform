    #供大模型调用的agent 工具
from database import SessionLocal
from product_service import (
    list_products,
    get_product_by_id
)
from sqlalchemy import select

from database import SessionLocal, ProductSKU



    #查询商品列表的工具函数  查询商品列表、分页
def list_products_tool(
    page: int = 1,
    page_size: int = 20
) -> dict:

    # 1. 验证参数类型
    if type(page) is not int or type(page_size) is not int:
        raise ValueError("分页参数必须是整数")

    # 2. 创建数据库会话
    with SessionLocal() as db:

        # 3. 复用现有商品查询业务
        products, total = list_products(
            db,
            page=page,
            page_size=page_size
        )

        # 4. 将 ORM 对象转换为普通字典
        items = []

        for product in products:
            items.append({
                "id": product.id,
                "product_code": product.product_code,
                "name": product.name,
                "category": product.category,
                "is_active": product.is_active
            })

        # 5. 返回结构化结果
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "products": items
        }




    #给模型看的工具名称和信息
LIST_PRODUCTS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_products",        #给模型看的工具名称
        "description": (                #帮助模型判断什么时候应该使用工具
            "查询商城当前的商品列表，支持分页。"
            "当用户询问有哪些商品、商品列表时使用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "page": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1,
                    "description": "查询页码，从1开始"
                },
                "page_size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                    "description": "每页商品数量"
                }
            },
            "required": [],
            "additionalProperties": False
        }
    }
}




    #查询产品细节的工具   根据商品 ID 查询详情及 SKU
def get_product_detail_tool(
    product_id: int
) -> dict:

    # 1. 验证商品 ID
    if type(product_id) is not int or product_id <= 0:
        raise ValueError("商品 ID 必须是正整数")

    # 2. 创建数据库会话
    with SessionLocal() as db:

        # 3. 复用现有商品查询业务
        product = get_product_by_id(
            db,
            product_id
        )

        # 4. 判断商品是否存在
        if product is None:
            return {
                "found": False,
                "product_id": product_id,
                "message": "未找到该商品"
            }

        # 5. 提取 SKU 信息
        sku_items = []

        for sku in product.skus:
            sku_items.append({
                "id": sku.id,
                "sku_code": sku.sku_code,
                "color": sku.color,
                "size": sku.size,
                "price": str(sku.price),
                "is_active": sku.is_active
            })

        # 6. 返回商品详情
        return {
            "found": True,
            "product": {
                "id": product.id,
                "product_code": product.product_code,
                "name": product.name,
                "category": product.category,
                "description": product.description,
                "is_active": product.is_active,
                "skus": sku_items
            }
        }



    #定义第二个工具解释
GET_PRODUCT_DETAIL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_product_detail",
        "description": (
            "根据商品 ID 查询商品详细信息，"
            "包括商品基本信息和关联的 SKU。"
            "当用户询问某件商品的详细信息时使用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "商品数据库 ID"
                }
            },
            "required": ["product_id"],
            "additionalProperties": False
        }
    }
}





    #根据 SKU 编号查询实时库存
def get_sku_inventory_tool(
    sku_code: str
) -> dict:

    # 1. 校验 SKU 编号
    if not isinstance(sku_code, str):
        raise ValueError("SKU 编号必须是字符串")

    sku_code = sku_code.strip()

    if not sku_code:
        raise ValueError("SKU 编号不能为空")

    if len(sku_code) > 100:
        raise ValueError("SKU 编号不能超过 100 个字符")

    # 2. 创建数据库会话
    with SessionLocal() as db:

        # 3. 根据 SKU 编号构建查询
        stmt = select(ProductSKU).where(
            ProductSKU.sku_code == sku_code
        )

        # 4. 查询数据库
        sku = db.scalar(stmt)

        # 5. 判断 SKU 是否存在
        if sku is None:
            return {
                "found": False,
                "sku_code": sku_code,
                "message": "未找到该 SKU"
            }

        # 6. 返回实际库存
        return {
            "found": True,
            "sku_code": sku.sku_code,
            "stock": sku.stock
        }



    #定义第三个工具的信息
GET_SKU_INVENTORY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_sku_inventory",
        "description": (
            "根据 SKU 编号查询商品的实时库存数量。"
            "当用户询问某个 SKU 还有多少库存时使用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sku_code": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                    "description": "商品 SKU 编号"
                }
            },
            "required": ["sku_code"],
            "additionalProperties": False
        }
    }
}







# Agent 工具注册表  ###################################

TOOL_REGISTRY = {

    "list_products": {
        "schema": LIST_PRODUCTS_SCHEMA, #工具注册
        "handler": list_products_tool,
        "allowed_arguments": {
            "page",
            "page_size"
        },
        "required_arguments": set()
    },

    "get_product_detail": {
        "schema": GET_PRODUCT_DETAIL_SCHEMA,
        "handler": get_product_detail_tool,
        "allowed_arguments": {
            "product_id"
        },
        "required_arguments": {
            "product_id"
        }
    },

    "get_sku_inventory": {
        "schema": GET_SKU_INVENTORY_SCHEMA,
        "handler": get_sku_inventory_tool,
        "allowed_arguments": {
            "sku_code"
        },
        "required_arguments": {
            "sku_code"
        }
    }

}


# 提取所有工具 Schema，交给 DeepSeek
AGENT_TOOLS = [
    tool["schema"]
    for tool in TOOL_REGISTRY.values()
]


# 根据模型返回的工具名称执行对应函数
def execute_tool(
    tool_name: str,
    arguments: dict
) -> dict:

    # 1. 检查工具是否存在
    if tool_name not in TOOL_REGISTRY:
        raise ValueError(
            f"不允许调用该工具：{tool_name}"
        )

    # 2. 检查参数是否为字典
    if not isinstance(arguments, dict):
        raise ValueError("工具参数必须是 JSON 对象")

    # 3. 获取工具配置
    tool = TOOL_REGISTRY[tool_name]

    # 4. 检查是否存在非法参数
    unexpected = (
        set(arguments)
        - tool["allowed_arguments"]
    )

    if unexpected:
        raise ValueError(
            f"存在不允许的参数：{unexpected}"
        )

    # 5. 检查必填参数
    missing = (
        tool["required_arguments"]
        - set(arguments)
    )

    if missing:
        raise ValueError(
            f"缺少必要参数：{missing}"
        )

    # 6. 找到对应的 Python 函数
    handler = tool["handler"]

    # 7. 执行工具并返回结果
    return handler(**arguments)
