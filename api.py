from ai import chat as ai_chat, chat_stream
from typing import Annotated
from pydantic import (
    BaseModel,
    StringConstraints,
    Field,
    ConfigDict
)
from database import (
    get_db,
    clear_messages,
    get_messages,
    save_conversation,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from rag import answer_question
import logging
from fastapi import FastAPI, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from typing import Literal
from functools import lru_cache
from pathlib import Path
from fastapi import File, UploadFile
from redis.exceptions import RedisError
from document_service import upload_document
from redis_bloom_filter import RedisBloomFilter

from decimal import Decimal
from datetime import datetime

from product_service import (
    create_product as create_product_service,
    get_product_by_id as get_product_by_id_service,
    list_products as list_products_service,
    update_product as update_product_service,
    update_product_sku as update_product_sku_service,
    delete_product as delete_product_service,
    delete_product_sku as delete_product_sku_service
)

from product_cache import (
    get_product_cache_version,
    get_product_detail_cache,
    set_product_detail_cache,
    get_product_list_cache,
    set_product_list_cache,
    invalidate_product_cache
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s"
)

logger = logging.getLogger(__name__)



# 文档上传大小限制：1 MB
MAX_DOCUMENT_SIZE = 1024 * 1024


# 获取文档上传使用的 Redis 布隆过滤器
@lru_cache(maxsize=1)
def get_document_bloom() -> RedisBloomFilter:

    try:

        return RedisBloomFilter(
            capacity=1000,
            error_rate=0.01,
            key="bloom:demo-policies:v1"
        )

    except RedisError as exc:

        logger.exception("Redis 布隆过滤器初始化失败")

        raise HTTPException(
            status_code=503,
            detail="Redis 文档去重服务暂不可用"
        ) from exc


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],

)

# 先去除首尾空白，再检查长度；保留问题内部的换行和空格。
UserId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100, strict=True),
]
Question = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000, strict=True),
]

     #定义聊天请求模型
class ChatRequest(BaseModel):
    user_id: UserId
    question: Question
    cache_mode: Literal["context", "question"] = "context"

class ClearRequest(BaseModel):
    user_id: UserId



# 商品模块：请求字段约束


ProductCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=50,
        strict=True
    )
]

ProductName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=200,
        strict=True
    )
]

SKUCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=100,
        strict=True
    )
]

ProductCategory = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        max_length=100,
        strict=True
    )
]

SKUText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        max_length=50,
        strict=True
    )
]



# 商品 SKU 创建请求模型


class ProductSKUCreateRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    sku_code: SKUCode

    color: SKUText | None = None

    size: SKUText | None = None

    price: Decimal = Field(
        ge=0,
        max_digits=10,
        decimal_places=2
    )

    stock: int = Field(
        default=0,
        ge=0,
        strict=True
    )

    is_active: bool = Field(
        default=True,
        strict=True
    )



# 商品创建请求模型


class ProductCreateRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    product_code: ProductCode

    name: ProductName

    category: ProductCategory | None = None

    description: str | None = None

    skus: list[ProductSKUCreateRequest] = Field(
        min_length=1
    )



# 商品更新请求模型


class ProductUpdateRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    name: ProductName | None = None

    category: ProductCategory | None = None

    description: str | None = None

    is_active: bool | None = Field(
        default=None,
        strict=True
    )



# SKU 更新请求模型


class ProductSKUUpdateRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    sku_code: SKUCode | None = None

    color: SKUText | None = None

    size: SKUText | None = None

    price: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=10,
        decimal_places=2
    )

    stock: int | None = Field(
        default=None,
        ge=0,
        strict=True
    )

    is_active: bool | None = Field(
        default=None,
        strict=True
    )



# SKU 响应模型


class ProductSKUResponse(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: int

    product_id: int

    sku_code: str

    color: str | None

    size: str | None

    price: Decimal

    stock: int

    is_active: bool

    created_at: datetime

    updated_at: datetime


# 商品响应模型


class ProductResponse(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: int

    product_code: str

    name: str

    category: str | None

    description: str | None

    is_active: bool

    created_at: datetime

    updated_at: datetime

    skus: list[ProductSKUResponse]



# 商品列表响应模型


class ProductListResponse(BaseModel):

    items: list[ProductResponse]

    total: int

    page: int

    page_size: int



    # 清空聊天记录接口
@app.post("/clear")
def clear_api(
    request: ClearRequest,
    db: Session = Depends(get_db)
):
    clear_messages(db, request.user_id)

    return {
        "message": "聊天记录已清空"
    }

    # 普通聊天模式接口
@app.post("/chat")
def chat_api(
    request: ChatRequest,
    db: Session = Depends(get_db)
):
    logger.info("普通聊天请求开始处理")

    try:
        answer = ai_chat(
            db,
            request.user_id,
            request.question,
            cache_mode=request.cache_mode
        )

        return {
            "answer": answer
        }

    except Exception as exc:
        logger.exception("普通聊天请求处理失败")

        raise HTTPException(
            status_code=500,
            detail="服务器处理请求失败，请稍后重试"
        ) from exc

    # 获取聊天历史记录接口
@app.get("/history/{user_id}")
def history(
    user_id: UserId,
    db: Session = Depends(get_db)
):
    messages = get_messages(db, user_id)

    return {
        "messages": messages
    }

    # 流式聊天模式接口
@app.post("/chat/stream")
def chat_stream_api(
    request: ChatRequest
):

    logger.info(
        "流式聊天请求开始处理，模式=%s",
        request.cache_mode
    )

    try:

        generator = chat_stream(
            request.user_id,
            request.question,
            cache_mode=request.cache_mode
        )

        return StreamingResponse(
            generator,
            media_type="text/plain; charset=utf-8"
        )

    except Exception as exc:

        logger.exception("流式聊天请求处理失败")

        raise HTTPException(
            status_code=500,
            detail="流式聊天请求处理失败，请稍后重试"
        ) from exc

    # RAG 问答模式接口
@app.post("/rag/chat")
def rag_chat_api(
    request: ChatRequest,
    db: Session = Depends(get_db)
):
    logger.info("RAG 问答请求开始处理")

    try:
        # 先检索知识库并生成回答
        answer = answer_question(request.question)

        # 回答生成成功后，一次性保存完整对话
        save_conversation(
            db,
            request.user_id,
            request.question,
            answer
        )

        # 返回答案给前端
        return {
            "answer": answer
        }

    except Exception as exc:
        logger.exception("RAG 问答请求处理失败")

        raise HTTPException(
            status_code=500,
            detail="知识库问答处理失败，请稍后重试"
        ) from exc



# 文档上传接口
@app.post("/documents/upload")
def document_upload_api(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    bloom: RedisBloomFilter = Depends(get_document_bloom)
):

    # 1. 获取并清理文件名
    try:

        filename = Path(
            file.filename or ""
        ).name.strip()

        if not filename:
            raise HTTPException(
                status_code=400,
                detail="文件名不能为空"
            )

        # 2. 目前只允许上传 TXT 文件
        if Path(filename).suffix.lower() != ".txt":
            raise HTTPException(
                status_code=400,
                detail="目前仅支持 .txt 文件"
            )

        # 3. 读取文件，最多读取 1 MB + 1 字节
        raw_content = file.file.read(
            MAX_DOCUMENT_SIZE + 1
        )

    finally:
        file.file.close()

    # 4. 检查文件大小
    if len(raw_content) > MAX_DOCUMENT_SIZE:
        raise HTTPException(
            status_code=413,
            detail="文件不能超过 1 MB"
        )

    # 5. 将文件字节解码为 UTF-8 文本
    try:

        content = raw_content.decode("utf-8-sig")

    except UnicodeDecodeError as exc:

        raise HTTPException(
            status_code=400,
            detail="文件必须使用 UTF-8 编码"
        ) from exc

    # 6. 检查文件内容
    if not content.strip():

        raise HTTPException(
            status_code=400,
            detail="文件内容不能为空"
        )

    # 7. 调用已有的文档业务函数
    try:

        result = upload_document(
            db,
            filename,
            content,
            bloom
        )

        #业务层抛出的参数 / 业务错误（比如文档重复）包装成 400。
    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc)
        ) from exc

    except Exception as exc:

        logger.exception(
            "文档上传失败，filename=%s",
            filename
        )

        raise HTTPException(
            status_code=500,
            detail="文档上传失败，请稍后重试"
        ) from exc

    # 8. 获取文档对象
    document = result["document"]

    # 9. 处理重复上传
    if not result["created"]:

        return {
            "created": False,
            "reason": result["reason"],
            "message": "文档已存在，未重复导入",
            "document": {
                "id": document.id,
                "filename": document.filename
            }
        }

    # 10. 返回成功结果
    logger.info(
        "文档上传成功，document_id=%s",
        document.id
    )

    return {
        "created": True,
        "reason": None,
        "message": "文档上传成功，已完成 MySQL 保存和 ChromaDB 向量索引",
        "document": {
            "id": document.id,
            "filename": document.filename
        }
    }






# 操作处理商品模块 API


# 1. 创建商品
@app.post(
    "/products",
    response_model=ProductResponse,
    status_code=201
)
def create_product_api(
    request: ProductCreateRequest,
    db: Session = Depends(get_db)
):

    try:

        product = create_product_service(
            db=db,
            product_code=request.product_code,
            name=request.name,
            category=request.category,
            description=request.description,
            skus=[
                sku.model_dump()
                for sku in request.skus
            ]
        )

        invalidate_product_cache()

        logger.info(
            "商品创建成功，product_id=%s",
            product.id
        )

        return product

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc)
        ) from exc

    except Exception as exc:

        logger.exception("商品创建失败")

        raise HTTPException(
            status_code=500,
            detail="商品创建失败，请稍后重试"
        ) from exc




# 查询商品列表，支持 Redis 缓存和分页
@app.get(
    "/products",
    response_model=ProductListResponse
)
def list_products_api(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db)
):

    try:

        # 1. 获取当前缓存版本
        cache_version = get_product_cache_version()

        # 2. 查询 Redis 缓存
        cached_data = get_product_list_cache(
            page,
            page_size,
            cache_version
        )

        # 3. 缓存命中，直接返回
        if cached_data is not None:

            logger.info(
                "商品列表缓存命中 page=%s page_size=%s",
                page,
                page_size
            )

            return cached_data

        # 4. 缓存未命中，查询 MySQL
        products, total = list_products_service(
            db,
            page,
            page_size
        )

        # 5. 转换为 JSON 兼容的数据
        result = {
            "items": [
                ProductResponse.model_validate(
                    product
                ).model_dump(mode="json")
                for product in products
            ],
            "total": total,
            "page": page,
            "page_size": page_size
        }

        # 6. 写入 Redis
        # 使用查询开始时取得的版本号，避免并发更新时写入新版本的旧数据
        set_product_list_cache(
            page,
            page_size,
            result,
            cache_version
        )

        logger.info("商品列表缓存未命中，已查询 MySQL")

        return result

    except Exception as exc:

        logger.exception("商品列表查询失败")

        raise HTTPException(
            status_code=500,
            detail="商品列表查询失败"
        ) from exc




# 查询商品详情，支持 Redis 缓存
@app.get(
    "/products/{product_id}",
    response_model=ProductResponse
)
def get_product_api(
    product_id: int,
    db: Session = Depends(get_db)
):

    try:

        # 1. 获取当前缓存版本
        cache_version = get_product_cache_version()

        # 2. 查询 Redis
        cached_data = get_product_detail_cache(
            product_id,
            cache_version
        )

        # 3. 缓存命中
        if cached_data is not None:

            logger.info(
                "商品详情缓存命中 product_id=%s",
                product_id
            )

            return cached_data

        # 4. 缓存未命中，查询 MySQL
        product = get_product_by_id_service(
            db,
            product_id
        )

        # 5. 商品不存在
        if product is None:

            raise HTTPException(
                status_code=404,
                detail="商品不存在"
            )

        # 6. ORM 对象转换为 JSON 数据
        result = ProductResponse.model_validate(
            product
        ).model_dump(mode="json")

        # 7. 写入 Redis
        set_product_detail_cache(
            product_id,
            result,
            cache_version
        )

        logger.info(
            "商品详情缓存未命中，已查询 MySQL product_id=%s",
            product_id
        )

        return result

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc)
        ) from exc

    except HTTPException:
        raise




# 4. 更新商品基本信息
@app.patch(
    "/products/{product_id}",
    response_model=ProductResponse
)
def update_product_api(
    product_id: int,
    request: ProductUpdateRequest,
    db: Session = Depends(get_db)
):

    try:

        updates = request.model_dump(
            exclude_unset=True
        )

        product = update_product_service(
            db,
            product_id,
            updates
        )

        if product is None:

            raise HTTPException(
                status_code=404,
                detail="商品不存在"
            )

        invalidate_product_cache()

        logger.info(
            "商品更新成功.product_id=%s",
            product_id
        )

        return product

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc)
        ) from exc

    except Exception as exc:

        if isinstance(exc, HTTPException):
            raise

        logger.exception("商品更新失败")

        raise HTTPException(
            status_code=500,
            detail="商品更新失败"
        ) from exc



# 5. 删除整个商品
@app.delete("/products/{product_id}")
def delete_product_api(
    product_id: int,
    db: Session = Depends(get_db)
):

    try:

        deleted = delete_product_service(
            db,
            product_id
        )

        if not deleted:

            raise HTTPException(
                status_code=404,
                detail="商品不存在"
            )

        invalidate_product_cache()

        logger.info(
            "商品删除成功,product_id=%s",
            product_id
        )

        return {
            "message": "商品删除成功"
        }

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc)
        ) from exc

    except HTTPException:
        raise

    except Exception as exc:

        logger.exception("商品删除失败")

        raise HTTPException(
            status_code=500,
            detail="商品删除失败"
        ) from exc



# 6. 更新指定 SKU
@app.patch(
    "/products/skus/{sku_id}",
    response_model=ProductSKUResponse
)
def update_product_sku_api(
    sku_id: int,
    request: ProductSKUUpdateRequest,
    db: Session = Depends(get_db)
):

    try:

        updates = request.model_dump(
            exclude_unset=True
        )

        sku = update_product_sku_service(
            db,
            sku_id,
            updates
        )

        if sku is None:

            raise HTTPException(
                status_code=404,
                detail="SKU 不存在"
            )

        invalidate_product_cache()

        logger.info(
            "SKU 更新成功,sku_id=%s",
            sku_id
        )

        return sku

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc)
        ) from exc

    except HTTPException:
        raise

    except Exception as exc:

        logger.exception("SKU 更新失败")

        raise HTTPException(
            status_code=500,
            detail="SKU 更新失败"
        ) from exc



# 7. 删除指定 SKU
@app.delete("/products/skus/{sku_id}")
def delete_product_sku_api(
    sku_id: int,
    db: Session = Depends(get_db)
):

    try:

        deleted = delete_product_sku_service(
            db,
            sku_id
        )

        if not deleted:

            raise HTTPException(
                status_code=404,
                detail="SKU 不存在"
            )
            #缓存失效
        invalidate_product_cache()

        logger.info(
            "SKU 删除成功,sku_id=%s",
            sku_id
        )

        return {
            "message": "SKU 删除成功"
        }

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc)
        ) from exc

    except HTTPException:
        raise

    except Exception as exc:

        logger.exception("SKU 删除失败")

        raise HTTPException(
            status_code=500,
            detail="SKU 删除失败"
        ) from exc




    #健康情况检查接口
@app.get("/health")
def health():
    return {
        "status": "ok",
        "environment": "local",
        "database": "mysql",
        "cache": "redis"
    }