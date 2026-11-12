import hashlib
import logging
from rag import split_text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database import (
    get_document_by_id,
    get_document_by_hash,
    get_document_by_filename,
    save_document,
    update_document as update_document_record,
    delete_document as delete_document_record
)

from chroma_service import (
    add_document_chunks,
    delete_document_chunks
)

from redis_bloom_filter import RedisBloomFilter


logger = logging.getLogger(__name__)

    #正常传入文档并拆分为文本块生成向量传入chromDB，并写入redis布隆过滤器的业务函数
def upload_document(
    db: Session,
    filename: str,
    content: str,
    bloom: RedisBloomFilter
):

    # 1. 检查文件名和文档内容
    filename = filename.strip()

    if not filename:
        raise ValueError("文件名不能为空")

    if not content.strip():
        raise ValueError("文档内容不能为空")

    # 2. 计算文档内容的 SHA-256
    content_hash = hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()

    # 3. 使用 Redis 布隆过滤器预检查
    maybe_exists = bloom.contains(content_hash)

    # 4. 如果可能存在，使用 MySQL 精确查询
    if maybe_exists:

        existing = get_document_by_hash(
            db,
            content_hash
        )

        if existing is not None:
            return {
                "created": False,
                "reason": "duplicate_content",
                "document": existing
            }

    # 5. 检查文件名是否重复
    existing = get_document_by_filename(
        db,
        filename
    )

    if existing is not None:
        return {
            "created": False,
            "reason": "duplicate_filename",
            "document": existing
        }

    # 6. 先将原始文档保存到 MySQL
    try:

        document = save_document(
            db,
            filename,
            content,
            content_hash
        )

    except IntegrityError:

        # 处理并发上传导致的唯一约束冲突
        existing = get_document_by_hash(
            db,
            content_hash
        )

        if existing is not None:
            return {
                "created": False,
                "reason": "duplicate_content",
                "document": existing
            }

        existing = get_document_by_filename(
            db,
            filename
        )

        if existing is not None:
            return {
                "created": False,
                "reason": "duplicate_filename",
                "document": existing
            }

        raise

    # 7. MySQL 保存成功，开始处理向量数据
    try:

        # 7.1 将原始文档切分成文本块
        chunks = split_text(content)

        # 7.2 生成 Embedding 并保存到 ChromaDB
        add_document_chunks(
            document_id=document.id,
            filename=filename,
            chunks=chunks
        )

    except Exception:

        logger.exception(
            "文档已保存到 MySQL,但 ChromaDB 入库失败，开始执行补偿"
        )

        # 7.3 尝试清理可能已经写入的向量
        try:

            delete_document_chunks(
                document.id
            )

        except Exception:

            logger.exception(
                "ChromaDB 向量清理失败,document_id=%s",
                document.id
            )

        # 7.4 尝试删除刚刚保存的 MySQL 文档
        try:

            delete_document_record(
                db,
                document.id
            )

        except Exception:

            logger.exception(
                "MySQL 补偿删除失败,document_id=%s",
                document.id
            )

        # 将最初的向量处理异常继续抛出
        raise

    # 8. MySQL 和 ChromaDB 都成功后，再更新布隆过滤器
    try:

        if not bloom.add(content_hash):

            logger.warning(
                "文档已保存，但 Redis 布隆过滤器更新失败：%s",
                content_hash
            )

    except Exception:

        logger.exception(
            "Redis 布隆过滤器更新异常：%s",
            content_hash
        )

    # 9. 返回上传结果
    return {
        "created": True,
        "reason": None,
        "document": document
    }





# 更新已存入文档的总业务函数
def update_document_service(
    db: Session,
    document_id: int,
    filename: str,
    content: str,
    bloom: RedisBloomFilter
):

    filename = filename.strip()

    if not filename:
        raise ValueError("文件名不能为空")

    if not content.strip():
        raise ValueError("文档内容不能为空")

    # 3. 查询原来的文档
    old_document = get_document_by_id(
        db,
        document_id
    )

    if old_document is None:
        return {
            "updated": False,
            "reason": "not_found",
            "document": None
        }

    # 4. 保存旧文档快照
    old_filename = old_document.filename
    old_content = old_document.content
    old_content_hash = old_document.content_hash

    # 5. 计算新文档的 SHA-256
    content_hash = hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()

    # 6. 提前准备新旧文本块
    old_chunks = split_text(old_content)
    new_chunks = split_text(content)

    if not old_chunks or not new_chunks:
        raise ValueError("文档切分后没有有效文本块")

    # 7. 先更新 MySQL
    document = update_document_record(
        db,
        document_id,
        filename,
        content,
        content_hash
    )
    #出错
    if document is None:
        return {
            "updated": False,
            "reason": "not_found",
            "document": None
        }

    # 8. 更新 ChromaDB
    try:

        # 8.1 删除旧文档的全部向量
        delete_document_chunks(document_id)

        # 8.2 添加新文档的全部向量
        add_document_chunks(
            document_id=document_id,
            filename=filename,
            chunks=new_chunks
        )

    except Exception:

        logger.exception(
            "文档向量更新失败,开始执行补偿,document_id=%s",
            document_id
        )

        # 9.1 清理可能已经写入的新向量
        try:

            delete_document_chunks(document_id)

        except Exception:

            logger.exception(
                "新向量清理失败,document_id=%s",
                document_id
            )

        # 9.2 恢复 MySQL 中的旧文档
        try:

            restored_document = update_document_record(
                db,
                document_id,
                old_filename,
                old_content,
                old_content_hash
            )

            if restored_document is None:
                raise RuntimeError("MySQL 旧文档恢复失败：文档不存在")

        except Exception:

            logger.exception(
                "MySQL 旧文档恢复失败,document_id=%s",
                document_id
            )

        # 9.3 重新生成并恢复旧向量
        try:

            add_document_chunks(
                document_id=document_id,
                filename=old_filename,
                chunks=old_chunks
            )

        except Exception:

            logger.exception(
                "ChromaDB 旧向量恢复失败,document_id=%s",
                document_id
            )

        # 重新抛出最初的向量更新异常
        raise

    # 10. MySQL 和 ChromaDB 成功后更新布隆过滤器
    try:

        if not bloom.add(content_hash):

            logger.warning(
                "文档已更新，但 Redis 布隆过滤器更新失败：%s",
                content_hash
            )

    except Exception:

        logger.exception(
            "Redis 布隆过滤器更新异常：%s",
            content_hash
        )

    # 11. 返回更新结果
    return {
        "updated": True,
        "reason": None,
        "document": document
    }






# 删除文档的总业务层函数
def delete_document_service(
    db: Session,
    document_id: int
):

    # 1. 根据文档 ID 查询原始文档
    old_document = get_document_by_id(
        db,
        document_id
    )

    # 2. 判断文档是否存在
    if old_document is None:
        return {
            "deleted": False,
            "reason": "not_found",
            "document_id": document_id
        }

    # 3. 保存旧文档信息，作为恢复备份
    old_filename = old_document.filename
    old_content = old_document.content

    # 4. 提前切分旧文档，准备恢复时使用
    old_chunks = split_text(old_content)

    # 5. 先删除 ChromaDB 中的全部向量
    try:

        delete_document_chunks(document_id)

    except Exception:

        logger.exception(
            "ChromaDB 向量删除失败，暂不删除 MySQL 文档，document_id=%s",
            document_id
        )

        raise

    # 6. ChromaDB 删除成功后，再删除 MySQL 文档
    try:

        deleted = delete_document_record(
            db,
            document_id
        )

        # 如果数据库中已经找不到文档
        if not deleted:
            return {
                "deleted": False,
                "reason": "not_found",
                "document_id": document_id
            }

    except Exception:

        logger.exception(
            "MySQL 文档删除失败，开始恢复 ChromaDB 向量，document_id=%s",
            document_id
        )

        # 7. 尝试恢复原来的向量
        try:

            if old_chunks:

                add_document_chunks(
                    document_id=document_id,
                    filename=old_filename,
                    chunks=old_chunks
                )

        except Exception:

            logger.exception(
                "ChromaDB 旧向量恢复失败，document_id=%s",
                document_id
            )

        # 继续抛出最初的数据库删除异常
        raise

    # 8. 返回删除成功
    return {
        "deleted": True,
        "reason": None,
        "document_id": document_id
    }
