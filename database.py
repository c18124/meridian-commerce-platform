from sqlalchemy import (
    create_engine,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    Numeric,
    CheckConstraint,
    func,
    delete,
    select
)

from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    sessionmaker,
    Session,
    relationship
)

from datetime import datetime
from decimal import Decimal

from config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True
)

class Base(DeclarativeBase):
    pass

    #用户数据表
class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    user_id: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )

    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    #rag文档数据表
class Document(Base):
    __tablename__ = "documents"

    # 文档主键
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    # 原始文件名
    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True
    )

    # 文档内容的 SHA-256
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True
    )

    # 原始文档内容
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )

    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )



# 商品主表
class Product(Base):
    __tablename__ = "products"

    # 商品主键 数据库主键id
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    # 商品唯一编号
    product_code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        unique=True
    )

    # 商品名称
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False
    )

    # 商品分类
    category: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    # 商品描述
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    # 是否上架
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True
    )

    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )

    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )



    # 一个商品拥有多个 SKU
    skus: Mapped[list["ProductSKU"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan"
    )



# 商品规格表
class ProductSKU(Base):
    __tablename__ = "product_skus"

    # SKU 主键 这个表内的id
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    # 所属商品 ID（外键）
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # SKU 编号
    sku_code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True
    )

    # 颜色
    color: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True
    )

    # 尺码
    size: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True
    )

    # 商品价格
    price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False
    )

    # 库存数量
    stock: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )

    # 是否上架
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True
    )

    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )

    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # 与商品主表建立反向关联
    product: Mapped["Product"] = relationship(
        back_populates="skus"
    )

    # 数据库约束 价格和库存
    __table_args__ = (
        CheckConstraint(
            "price >= 0",
            name="ck_product_skus_price_nonnegative"
        ),
        CheckConstraint(
            "stock >= 0",
            name="ck_product_skus_stock_nonnegative"
        )
    )


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False
)

def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()

def save_messages(
    db: Session,
    user_id: str,
    role: str,
    content: str
):
    message = Message(
        user_id=user_id,
        role=role,
        content=content
    )

    try:
        db.add(message)
        db.commit()
        db.refresh(message)

        return message

    except Exception:
        db.rollback()
        raise

def save_conversation(
    db: Session,
    user_id: str,
    question: str,
    answer: str
):
    user_message = Message(
        user_id=user_id,
        role="user",
        content=question
    )

    assistant_message = Message(
        user_id=user_id,
        role="assistant",
        content=answer
    )

    try:
        db.add_all([user_message, assistant_message])
        db.commit()

        db.refresh(user_message)
        db.refresh(assistant_message)

        return user_message, assistant_message

    except Exception:
        db.rollback()
        raise

def get_messages(db: Session, user_id: str):

    stmt = (
        select(Message.role, Message.content)
        .where(Message.user_id == user_id)
        .order_by(Message.id.asc())
    )

    rows = db.execute(stmt).all()

    messages = []

    for row in rows:
        messages.append({
            "role": row.role,
            "content": row.content
        })

    return messages

def clear_messages(db: Session, user_id: str):

    stmt = delete(Message).where(
        Message.user_id == user_id
    )

    try:
        result = db.execute(stmt)
        db.commit()

        return result.rowcount

    except Exception:
        db.rollback()
        raise



        #下面的是操作mysql数据库中保存文档的函数，document操作函数
        #查询文档是否存在的函数
def get_document_by_hash(
    db: Session,
    content_hash: str
):
    # 1. 创建 SQL 查询语句
    stmt = select(Document).where(
        Document.content_hash == content_hash
    )

    # 2. 执行查询，获取第一条记录
    document = db.scalar(stmt)

    # 3. 返回查询结果，是否有这个文档
    return document


    #同名文档查询函数
def get_document_by_filename(
    db: Session,
    filename: str
):
    stmt = select(Document).where(
        Document.filename == filename
    )

    document = db.scalar(stmt)

    return document


# 根据文档 ID 查询文档
def get_document_by_id(
    db: Session,
    document_id: int
):
    # 根据主键查询 Document 对象
    document = db.get(Document, document_id)

    # 返回文档，找不到就返回 None
    return document


    #将新文档保存
def save_document(
    db: Session,
    filename: str,
    content: str,
    content_hash: str
):
    # 1. 创建 Document 对象
    document = Document(
        filename=filename,
        content=content,
        content_hash=content_hash
    )

    try:
        # 2. 添加到数据库 Session
        db.add(document)

        # 3. 提交事务
        db.commit()

        # 4. 刷新对象，获取数据库生成的信息
        db.refresh(document)

        return document

    except Exception:
        # 5. 保存失败，回滚事务
        db.rollback()
        raise


        #启动后重新查询全部已保存的文档
def get_all_documents(db: Session):

    stmt = (
        select(Document)
        .order_by(Document.id.asc())
    )

    documents = db.scalars(stmt).all()

    return documents


    #更新文档内容
def update_document(
    db: Session,
    document_id: int,
    filename: str,
    content: str,
    content_hash: str
):
    # 1. 根据主键找到原来的文档
    document = db.get(Document, document_id)

    # 2. 判断文档是否存在
    if document is None:
        return None

    try:
        # 3. 检查新的 Hash 是否已经被其他文档使用
        hash_document = get_document_by_hash(
            db,
            content_hash
        )

        if (
            hash_document is not None
            and hash_document.id != document_id
        ):
            raise ValueError("其他文档已经使用了这个内容")

        # 4. 检查新的文件名是否已经被其他文档使用
        filename_document = get_document_by_filename(
            db,
            filename
        )

        if (
            filename_document is not None
            and filename_document.id != document_id
        ):
            raise ValueError("其他文档已经使用了这个文件名")

        # 5. 修改原来的文档对象
        document.filename = filename
        document.content = content
        document.content_hash = content_hash

        # 6. 提交更新
        db.commit()

        # 7. 刷新对象
        db.refresh(document)

        return document

    except Exception:
        db.rollback()
        raise


        #删除文档的函数
def delete_document(
    db: Session,
    document_id: int
):
    # 1. 根据主键查找文档
    document = db.get(Document, document_id)

    # 2. 判断文档是否存在
    if document is None:
        return False

    try:
        # 3. 将文档标记为删除
        db.delete(document)

        # 4. 提交事务，真正执行删除
        db.commit()

        return True

    except Exception:
        # 5. 删除失败，回滚事务
        db.rollback()
        raise