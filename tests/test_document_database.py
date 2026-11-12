import pytest
import hashlib
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import IntegrityError
from database import Base
from database import (
    save_document,
    get_document_by_hash,
    get_document_by_filename,
    get_all_documents,
    update_document,
    delete_document,
    get_document_by_id
)

from document_service import upload_document
from document_service import update_document_service
from document_service import delete_document_service

@pytest.fixture
def db():

    # 1. 创建临时 SQLite 数据库
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )

    # 2. 根据模型创建测试表
    Base.metadata.create_all(test_engine)

    # 3. 创建测试数据库 Session
    TestSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False
    )

    session = TestSessionLocal()

    try:
        yield session

    finally:
        # 4. 关闭 Session
        session.close()

        # 5. 删除测试表
        Base.metadata.drop_all(test_engine)

        # 6. 释放数据库连接
        test_engine.dispose()


    #测试保存文档
def test_save_document_and_get_by_hash(db):

    # 1. 保存一份测试文档
    document = save_document(
        db,
        filename="python_test.txt",
        content="这是 Python 测试文档",
        content_hash="a" * 64
    )

    # 2. 检查是否成功生成 ID
    assert document.id is not None

    # 3. 根据 Hash 查询
    found = get_document_by_hash(
        db,
        "a" * 64
    )

    # 4. 验证查询结果
    assert found is not None
    assert found.filename == "python_test.txt"
    assert found.content == "这是 Python 测试文档"


    #根据文件名查询
def test_get_document_by_filename(db):

    # 1. 创建一份测试文档
    document = save_document(
        db,
        filename="rag_test.txt",
        content="这是 RAG 测试文档",
        content_hash="b" * 64
    )

    # 2. 根据文件名查询
    found = get_document_by_filename(
        db,
        "rag_test.txt"
    )

    # 3. 验证查询结果
    assert found is not None
    assert found.id == document.id
    assert found.content == "这是 RAG 测试文档"

    # 4. 测试不存在的文件名
    missing = get_document_by_filename(
        db,
        "unknown.txt"
    )

    assert missing is None


    #测试hash不存在的情况找不到文档
def test_get_document_by_hash_returns_none(db):

    # 1. 使用一个不存在的 Hash 查询
    found = get_document_by_hash(
        db,
        "c" * 64
    )

    # 2. 验证没有查询到文档
    assert found is None


    #测试查询全部文档
def test_get_all_documents(db):

    # 1. 保存第一份文档
    save_document(
        db,
        "python.txt",
        "Python 基础知识",
        "d" * 64
    )

    # 2. 保存第二份文档
    save_document(
        db,
        "rag.txt",
        "RAG 检索知识",
        "e" * 64
    )

    # 3. 查询全部文档
    documents = get_all_documents(db)

    # 4. 验证查询结果
    assert len(documents) == 2

    assert documents[0].filename == "python.txt"
    assert documents[1].filename == "rag.txt"


    #测试文档更新的功能
def test_update_document(db):

    # 1. 先保存一份原始文档
    document = save_document(
        db,
        filename="old_python.txt",
        content="旧文档内容",
        content_hash="f" * 64
    )

    # 2. 获取原始文档的 ID
    document_id = document.id

    # 3. 更新这份文档
    updated = update_document(
        db,
        document_id=document_id,
        filename="new_python.txt",
        content="这是修改后的文档内容",
        content_hash="0" * 64
    )

    # 4. 验证更新是否成功
    assert updated is not None

    # 5. 验证主键没有改变
    assert updated.id == document_id

    # 6. 验证文档信息已经更新
    assert updated.filename == "new_python.txt"
    assert updated.content == "这是修改后的文档内容"
    assert updated.content_hash == "0" * 64



    #测试文档删除功能
def test_delete_document(db):

    # 1. 先创建一份测试文档
    document = save_document(
        db,
        filename="delete_test.txt",
        content="准备删除的测试文档",
        content_hash="1" * 64
    )

    # 2. 获取文档 ID
    document_id = document.id

    # 3. 调用删除函数
    result = delete_document(
        db,
        document_id
    )

    # 4. 验证删除操作成功
    assert result is True

    # 5. 再次根据 Hash 查询
    found = get_document_by_hash(
        db,
        "1" * 64
    )

    # 6. 验证文档已经不存在
    assert found is None


    #尝试更新一份不存在的文档
def test_update_nonexistent_document(db):

    # 1. 尝试更新一份不存在的文档
    updated = update_document(
        db,
        document_id=999,
        filename="unknown.txt",
        content="新的文档内容",
        content_hash="2" * 64
    )

    # 2. 验证返回 None
    assert updated is None


    #测试删除不存在的文档
def test_delete_nonexistent_document(db):

    # 1. 尝试删除不存在的文档
    result = delete_document(
        db,
        document_id=999
    )

    # 2. 验证删除函数返回 False
    assert result is False


    #测试重复hash值的情况

def test_save_document_rejects_duplicate_hash(db):

    # 1. 先保存第一份文档
    save_document(
        db,
        filename="python.txt",
        content="第一份文档",
        content_hash="a" * 64
    )

    # 2. 尝试保存第二份文档
    #    文件名不同，但 Hash 相同
    with pytest.raises(IntegrityError):

        save_document(
            db,
            filename="rag.txt",
            content="第二份文档",
            content_hash="a" * 64
        )


    #测试文档名称重复的情况，IntegrityError会抛出错误
def test_save_document_rejects_duplicate_filename(db):

    # 1. 保存第一份文档
    save_document(
        db,
        filename="python.txt",
        content="第一份文档",
        content_hash="a" * 64
    )

    # 2. 尝试保存第二份文档
    # 文件名相同，但是 Hash 不同
    with pytest.raises(IntegrityError):

        save_document(
            db,
            filename="python.txt",
            content="第二份文档",
            content_hash="b" * 64
        )





class FakeBloomFilter:           #FakeBloomFilter 类   ###########################################################

    def __init__(
        self,
        contains_result=False,
        add_result=True
    ):
        # 控制 contains 固定返回什么
        self.contains_result = contains_result
        self.add_result = add_result
        # 日志容器：记录谁被查过、谁被 add 过
        self.checked_items = []
        self.added_items = []

    def contains(self, item):

        self.checked_items.append(item)

        return self.contains_result

    def add(self, item):

        self.added_items.append(item)

        return self.add_result


@pytest.fixture
def mock_chroma(monkeypatch):               #模拟 ChromaDB 的 Fixture  ###################################

    # 记录各个函数收到的参数
    calls = {
        "split": [],
        "add": [],
        "delete": []
        }

    # 模拟文本切块
    def fake_split_text(content):

        calls["split"].append(content)

        return [content]

    # 模拟向 ChromaDB 保存向量
    def fake_add_document_chunks(
        document_id,
        filename,
        chunks
    ):

        calls["add"].append({
            "document_id": document_id,
            "filename": filename,
            "chunks": chunks
        })

        # 模拟返回生成的 Chunk ID
        return [
            f"{document_id}_{index}"
            for index in range(len(chunks))
        ]

    # 模拟删除 ChromaDB 中的向量
    def fake_delete_document_chunks(document_id):

        calls["delete"].append(document_id)

        return 0

    # 临时替换 document_service 中的函数
    monkeypatch.setattr(
        "document_service.split_text",
        fake_split_text
    )

    monkeypatch.setattr(
        "document_service.add_document_chunks",
        fake_add_document_chunks
    )

    monkeypatch.setattr(
        "document_service.delete_document_chunks",
        fake_delete_document_chunks
    )

    return calls



def test_upload_document_success(db, mock_chroma):

    # 1. 准备文档内容
    content = "这是第一份需要上传的 RAG 文档"

    # 2. 创建模拟布隆过滤器
    bloom = FakeBloomFilter(
        contains_result=False,
        add_result=True
    )

    # 3. 调用文档上传业务函数
    result = upload_document(
        db,
        filename="rag_test.txt",
        content=content,
        bloom=bloom
    )

    # 4. 自己计算预期 Hash
    expected_hash = hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()

    # 5. 验证上传成功
    assert result["created"] is True

    # 6. 验证文件名和内容
    assert result["document"].filename == "rag_test.txt"
    assert result["document"].content == content

    # 7. 验证 SHA-256
    assert result["document"].content_hash == expected_hash

    # 8. 验证布隆过滤器先查询、后更新
    assert bloom.checked_items == [expected_hash]
    assert bloom.added_items == [expected_hash]

    # 9. 验证文本切块函数被调用
    assert mock_chroma["split"] == [content]

    # 10. 验证 ChromaDB 保存函数被调用
    assert len(mock_chroma["add"]) == 1

    # 11. 验证保存的文档 ID 正确
    assert (
        mock_chroma["add"][0]["document_id"]
        == result["document"].id
    )

    # 12. 验证文件名正确
    assert (
        mock_chroma["add"][0]["filename"]
        == "rag_test.txt"
    )

    # 13. 验证传入的文本块正确
    assert mock_chroma["add"][0]["chunks"] == [content]


    #测试布隆过滤器的误判时进一步查询数据库
def test_upload_document_allows_bloom_false_positive(
    db,
    mock_chroma
):

    # 1. 准备一份数据库中不存在的文档
    content = "这是一份布隆过滤器误判测试文档"

    # 2. 计算这份文档的 Hash
    expected_hash = hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()

    # 3. 模拟布隆过滤器误判
    bloom = FakeBloomFilter(
        contains_result=True,
        add_result=True
    )

    # 4. 执行上传
    result = upload_document(
        db,
        filename="false_positive.txt",
        content=content,
        bloom=bloom
    )

    # 5. 验证最终上传成功
    assert result["created"] is True

    # 6. 验证文档确实保存到了数据库
    assert result["document"].content_hash == expected_hash

    # 7. 验证 MySQL 中确实存在这份文档
    assert get_document_by_hash(
        db,
        expected_hash
    ) is not None

    # 8. 验证布隆过滤器执行了查询和更新
    assert bloom.checked_items == [expected_hash]
    assert bloom.added_items == [expected_hash]


    #测试重复存入文档的情况
def test_upload_document_rejects_duplicate_content(db):

    # 1. 准备原始文档内容
    content = "Python 使用字典保存键值对"

    # 2. 计算内容 Hash
    content_hash = hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()

    # 3. 先将原始文档保存到 MySQL
    original = save_document(
        db,
        filename="original.txt",
        content=content,
        content_hash=content_hash
    )

    # 4. 模拟布隆过滤器判断可能存在
    bloom = FakeBloomFilter(
        contains_result=True,
        add_result=True
    )

    # 5. 再次上传相同内容，但使用不同文件名
    result = upload_document(
        db,
        filename="copy.txt",
        content=content,
        bloom=bloom
    )

    # 6. 验证上传被拒绝
    assert result["created"] is False

    # 7. 验证拒绝原因
    assert result["reason"] == "duplicate_content"

    # 8. 验证返回的是原始文档
    assert result["document"].id == original.id

    # 9. 验证没有再次更新布隆过滤器
    assert bloom.added_items == []

    # 10. 验证数据库仍然只有一份文档
    assert len(get_all_documents(db)) == 1


    #测试在文档存入后redis断链，故障降级
def test_upload_succeeds_when_bloom_update_fails(
    db,
    mock_chroma
):

    # 1. 准备文档
    content = "Redis 更新失败测试文档"

    # 2. 模拟布隆过滤器
    # 查询正常，但更新失败
    bloom = FakeBloomFilter(
        contains_result=False,
        add_result=False
    )

    # 3. 执行上传
    result = upload_document(
        db,
        filename="redis_failure.txt",
        content=content,
        bloom=bloom
    )

    # 4. 验证上传仍然成功
    assert result["created"] is True

    # 5. 验证 MySQL 确实保存了文档
    assert result["document"].filename == "redis_failure.txt"

    # 6. 计算预期 Hash
    expected_hash = hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()

    # 7. 再次查询 MySQL
    saved = get_document_by_hash(
        db,
        expected_hash
    )

    assert saved is not None

    # 8. 验证 Redis 更新确实尝试过
    assert bloom.added_items == [expected_hash]
#测试边界： 这里的 add_result=False 模拟的是 Redis 更新失败后的返回结果。
# 真实的 Redis 连接异常已经由 RedisBloomFilter.add() 捕获并转换为 False，后续还会单独做真实 Redis 故障测试。


    #测试正常更新已存入文档操作
def test_update_document_service_success(
    db,
    mock_chroma
):

    # 1. 准备原始文档
    old_content = "Python 使用列表保存数据"

    old_hash = hashlib.sha256(
        old_content.encode("utf-8")
    ).hexdigest()

    # 2. 先将原始文档保存到 MySQL
    original = save_document(
        db,
        filename="python.txt",
        content=old_content,
        content_hash=old_hash
    )

    # 3. 准备修改后的内容
    new_content = "Python 使用字典保存键值对"

    new_hash = hashlib.sha256(
        new_content.encode("utf-8")
    ).hexdigest()

    # 4. 创建模拟布隆过滤器
    bloom = FakeBloomFilter(
        contains_result=False,
        add_result=True
    )

    # 5. 调用文档更新业务函数
    result = update_document_service(
        db,
        document_id=original.id,
        filename="python.txt",
        content=new_content,
        bloom=bloom
    )

    # 6. 验证更新成功
    assert result["updated"] is True

    # 7. 验证文档 ID 没有改变
    assert result["document"].id == original.id

    # 8. 验证文档内容已经更新
    assert result["document"].content == new_content

    # 9. 验证 Hash 已经更新
    assert result["document"].content_hash == new_hash

    # 10. 验证 MySQL 中的新 Hash 可以查到
    assert get_document_by_hash(
        db,
        new_hash
    ) is not None

    # 11. 验证 MySQL 中旧 Hash 已经不存在
    assert get_document_by_hash(
        db,
        old_hash
    ) is None

    # 12. 验证 Redis 已经添加新 Hash
    assert bloom.added_items == [new_hash]



    #测试当更新不存在的文档时
def test_update_document_service_not_found(db):

    # 1. 创建模拟布隆过滤器
    bloom = FakeBloomFilter(
        add_result=True
    )

    # 2. 尝试更新一份不存在的文档
    result = update_document_service(
        db,
        document_id=999999,
        filename="unknown.txt",
        content="这是一份不存在的文档",
        bloom=bloom
    )

    # 3. 验证更新失败
    assert result["updated"] is False

    # 4. 验证失败原因
    assert result["reason"] == "not_found"

    # 5. 验证没有返回文档对象
    assert result["document"] is None

    # 6. 验证没有更新布隆过滤器
    assert bloom.added_items == []



    #测试更新后的文档与其他文档重复
def test_update_document_service_rejects_duplicate_content(db):

    # 1. 准备第一份文档
    old_content = "Python 使用列表保存数据"

    old_hash = hashlib.sha256(
        old_content.encode("utf-8")
    ).hexdigest()

    first = save_document(
        db,
        filename="python.txt",
        content=old_content,
        content_hash=old_hash
    )

    # 2. 准备第二份文档
    other_content = "Java 使用集合保存数据"

    other_hash = hashlib.sha256(
        other_content.encode("utf-8")
    ).hexdigest()
    #保存进数据库
    second = save_document(
        db,
        filename="java.txt",
        content=other_content,
        content_hash=other_hash
    )

    # 3. 创建模拟布隆过滤器
    bloom = FakeBloomFilter(
        add_result=True
    )

    # 4. 尝试将第一份文档修改成第二份文档的内容
    with pytest.raises(ValueError, match="其他文档已经使用了这个内容"):

        update_document_service(
            db,
            document_id=first.id,
            filename="python.txt",
            content=other_content,
            bloom=bloom
        )

    # 5. 重新查询第一份文档
    first_after = get_document_by_hash(
        db,
        old_hash
    )

    # 6. 验证第一份文档仍然存在
    assert first_after is not None

    # 7. 验证第一份文档没有被修改
    assert first_after.filename == "python.txt"
    assert first_after.content == old_content
    assert first_after.content_hash == old_hash

    # 8. 验证第二份文档仍然存在
    second_after = get_document_by_hash(
        db,
        other_hash
    )
    #断言没有修改成功，还是原来的那个id
    assert second_after.id == second.id

    # 9. 验证 Redis 没有添加新 Hash
    assert bloom.added_items == []


    #测试数据库更新成功了但是redis没有成功
def test_update_document_succeeds_when_bloom_update_fails(
    db,
    mock_chroma
):

    # 1. 准备原始文档
    old_content = "Python 使用列表保存数据"

    old_hash = hashlib.sha256(
        old_content.encode("utf-8")
    ).hexdigest()

    original = save_document(
        db,
        filename="python.txt",
        content=old_content,
        content_hash=old_hash
    )

    # 2. 准备新的文档内容
    new_content = "Python 使用字典保存键值对"

    new_hash = hashlib.sha256(
        new_content.encode("utf-8")
    ).hexdigest()

    # 3. 模拟 Redis 更新失败
    bloom = FakeBloomFilter(
        add_result=False
    )

    # 4. 执行文档更新
    result = update_document_service(
        db,
        document_id=original.id,
        filename="python.txt",
        content=new_content,
        bloom=bloom
    )

    # 5. 验证业务更新仍然成功
    assert result["updated"] is True

    # 6. 验证文档 ID 没有改变
    assert result["document"].id == original.id

    # 7. 验证新内容已经保存
    assert result["document"].content == new_content

    # 8. 验证 MySQL 中的新 Hash 存在
    updated = get_document_by_hash(
        db,
        new_hash
    )

    assert updated is not None

    # 9. 验证旧 Hash 已经不存在
    assert get_document_by_hash(
        db,
        old_hash
    ) is None

    # 10. 验证 Redis 确实尝试添加了新 Hash
    assert bloom.added_items == [new_hash]


    #测试删除文档的业务函数功能
def test_delete_document_service_success(
    db,
    mock_chroma
):
    # 1. 准备文档内容
    content = "这是需要删除的 RAG 文档"

    # 2. 计算 Hash
    content_hash = hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()

    # 3. 先保存文档到 MySQL
    document = save_document(
        db,
        filename="delete_test.txt",
        content=content,
        content_hash=content_hash
    )

    # 4. 调用删除业务函数
    result = delete_document_service(
        db,
        document.id
    )

    # 5. 验证删除成功
    assert result["deleted"] is True

    # 6. 验证返回的文档 ID
    assert result["document_id"] == document.id

    # 7. 再次通过 Hash 查询
    deleted_document = get_document_by_hash(
        db,
        content_hash
    )

    # 8. 验证 MySQL 中已经不存在
    assert deleted_document is None

    # 9. 验证数据库没有剩余文档
    assert get_all_documents(db) == []

    # 验证旧文档经过了切块
    assert len(mock_chroma["split"]) == 1

    # 验证 ChromaDB 删除函数被调用
    assert len(mock_chroma["delete"]) == 1

    # 验证删除的是正确的文档 ID
    assert mock_chroma["delete"][0] == document.id

    # 正常删除不需要恢复向量
    assert mock_chroma["add"] == []




    #测试删除数据库中维持在的文档
def test_delete_document_service_not_found(
    db,
    mock_chroma
):

    # 1. 尝试删除不存在的文档
    result = delete_document_service(
        db,
        document_id=999999
    )

    # 2. 验证删除失败
    assert result["deleted"] is False

    # 3. 验证失败原因
    assert result["reason"] == "not_found"

    # 4. 验证返回的 ID
    assert result["document_id"] == 999999

    # 5. 验证数据库没有数据
    assert get_all_documents(db) == []

    # 不存在的文档不应该触发向量删除
    assert mock_chroma["delete"] == []

    # 不应该触发文本切块
    assert mock_chroma["split"] == []



    #MySQL 删除文档失败时恢复向量的测试
def test_delete_document_restores_chunks_when_mysql_fails(
    db,
    mock_chroma,
    monkeypatch
):

    content = "MySQL 删除失败恢复测试"

    content_hash = "d" * 64

    # 1. 先在 MySQL 创建一份文档
    document = save_document(
        db,
        "delete_failure.txt",
        content,
        content_hash
    )

    # 2. 模拟 MySQL 删除失败
    def fake_delete_document_record(
        db,
        document_id
    ):

        raise RuntimeError("MySQL 删除失败")

    monkeypatch.setattr(
        "document_service.delete_document_record",
        fake_delete_document_record
    )

    # 3. 执行删除，预期出现异常
    with pytest.raises(
        RuntimeError,
        match="MySQL 删除失败"
    ):

        delete_document_service(
            db,
            document.id
        )

    # 4. 验证 ChromaDB 删除函数被调用
    assert mock_chroma["delete"] == [
        document.id
    ]

    # 5. 验证 MySQL 原始文档仍然存在
    restored_document = get_document_by_id(
        db,
        document.id
    )

    assert restored_document is not None

    assert restored_document.content == content

    # 6. 验证原来的向量恢复操作被调用
    assert len(mock_chroma["add"]) == 1

    assert mock_chroma["add"][0]["document_id"] == document.id

    assert mock_chroma["add"][0]["filename"] == "delete_failure.txt"

    assert mock_chroma["add"][0]["chunks"] == [content]



    #测试 MySQL 保存成功，但是 ChromaDB 写入失败
def test_upload_compensates_when_chroma_fails(
    db,
    monkeypatch
):

    content = "ChromaDB 写入失败补偿测试"

    bloom = FakeBloomFilter(
        contains_result=False,
        add_result=True
    )

    added_document_ids = []
    deleted_document_ids = []

    # 模拟正常切块
    def fake_split_text(content):
        return [content]

    # 模拟 ChromaDB 写入失败
    def fake_add_document_chunks(
        document_id,
        filename,
        chunks
    ):

        added_document_ids.append(document_id)

        raise RuntimeError("ChromaDB 写入失败")

    # 模拟删除向量
    def fake_delete_document_chunks(document_id):

        deleted_document_ids.append(document_id)

        return 0

    monkeypatch.setattr(
        "document_service.split_text",
        fake_split_text
    )

    monkeypatch.setattr(
        "document_service.add_document_chunks",
        fake_add_document_chunks
    )

    monkeypatch.setattr(
        "document_service.delete_document_chunks",
        fake_delete_document_chunks
    )

    # 执行上传，预期抛出异常
    with pytest.raises(
        RuntimeError,
        match="ChromaDB 写入失败"
    ):

        upload_document(
            db,
            filename="failure_test.txt",
            content=content,
            bloom=bloom
        )

    # 验证确实尝试写入了 ChromaDB
    assert len(added_document_ids) == 1

    # 验证确实尝试清理向量
    assert deleted_document_ids == added_document_ids

    # 验证 MySQL 文档已经被补偿删除
    assert get_all_documents(db) == []

    # 验证没有更新布隆过滤器
    assert bloom.added_items == []
