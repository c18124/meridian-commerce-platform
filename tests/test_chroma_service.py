    #测试chromaDB_service相关操作和服务的测试集
import chromadb
import chroma_service

    #测试chromaDB能够保存文档的业务功能
def test_add_document_chunks(tmp_path, monkeypatch):

    # 1. 创建独立测试数据库
    client = chromadb.PersistentClient(
        path=str(tmp_path / "chroma_service_test")
    )

    collection = client.get_or_create_collection(
        name="test_chunks",
        configuration={
            "hnsw": {
                "space": "cosine"
            }
        },
        embedding_function=None
    )

    # 2. 将业务模块使用的正式集合替换为测试集合
    monkeypatch.setattr(
        chroma_service,
        "rag_collection",
        collection
    )

    # 3. 模拟 Embedding 模型的输出
    monkeypatch.setattr(
        chroma_service,
        "encode_texts",
        lambda texts: [
            [0.1, 0.2, 0.3]
            for _ in texts
        ]
    )

    # 4. 准备两段文本
    chunks = [
        "Python 使用字典保存键值对",
        "Redis 是一个内存数据库"
    ]

    # 5. 调用业务函数保存进cheomaDB
    ids = chroma_service.add_document_chunks(
        document_id=1,
        filename="python_notes.txt",
        chunks=chunks
    )

    # 6. 根据 ID 查询保存结果
    result = collection.get(
        ids=ids,
        include=[
            "documents",
            "metadatas",
            "embeddings"
        ]
    )

    # 7. 验证
    assert ids == ["1_0", "1_1"]

    assert result["documents"] == chunks

    assert result["metadatas"][0]["document_id"] == 1

    assert result["metadatas"][1]["chunk_index"] == 1

    assert len(result["embeddings"]) == 2

    assert collection.count() == 2



    #测试模拟根据用户问题向量来查询相关的文本块
def test_search_similar_chunks_returns_nearest(
    tmp_path,
    monkeypatch
):

    # 1. 创建独立测试数据库
    client = chromadb.PersistentClient(
        path=str(tmp_path / "chroma_search_test")
    )

    collection = client.get_or_create_collection(
        name="test_search",
        configuration={
            "hnsw": {
                "space": "cosine"
            }
        },
        embedding_function=None
    )

    # 2. 替换正式集合
    monkeypatch.setattr(
        chroma_service,
        "rag_collection",
        collection
    )

    # 3. 模拟用户问题向量
    monkeypatch.setattr(
        chroma_service,
        "encode_query",
        lambda question: [0.1, 0.2, 0.3]
    )

    # 4. 添加两条测试数据
    collection.add(
        ids=["1_0", "2_0"],
        embeddings=[
            [0.1, 0.2, 0.3],
            [0.3, 0.2, 0.1]
        ],
        documents=[
            "Python 使用字典保存键值对",
            "Redis 是一个内存数据库"
        ],
        metadatas=[
            {"document_id": 1},
            {"document_id": 2}
        ]
    )

    # 5. 调用语义检索函数
    results = chroma_service.search_similar_chunks(
        question="Python 字典如何保存数据？",
        top_k=2
    )

    # 6. 验证检索结果
    assert len(results) == 2

    assert results[0]["id"] == "1_0"

    assert results[0]["content"] == (
        "Python 使用字典保存键值对"
    )

    assert results[0]["metadata"]["document_id"] == 1

    assert results[0]["distance"] <= results[1]["distance"]


    #测试chromaDB服务中的根据指定文档id删除文本块的功能
def test_delete_document_chunks(tmp_path, monkeypatch):

    # 1. 创建独立测试数据库
    client = chromadb.PersistentClient(
        path=str(tmp_path / "chroma_delete_test")
    )

    collection = client.get_or_create_collection(
        name="test_delete",
        configuration={
            "hnsw": {
                "space": "cosine"
            }
        },
        embedding_function=None
    )

    # 2. 替换正式集合
    monkeypatch.setattr(
        chroma_service,
        "rag_collection",
        collection
    )

    # 3. 添加两份文档的向量数据
    collection.add(
        ids=["1_0", "1_1", "2_0"],
        embeddings=[
            [0.1, 0.2, 0.3],
            [0.2, 0.3, 0.4],
            [0.3, 0.2, 0.1]
        ],
        documents=[
            "Python 字典",
            "Python 列表",
            "Redis 缓存"
        ],
        metadatas=[
            {"document_id": 1},
            {"document_id": 1},
            {"document_id": 2}
        ]
    )

    # 4. 删除 document_id 为 1 的全部向量
    deleted_count = chroma_service.delete_document_chunks(1)

    # 5. 验证删除数量
    assert deleted_count == 2

    # 6. 验证数据库还剩一条记录
    assert collection.count() == 1

    # 7. 验证 document_id 为 2 的数据没有被误删，验证操作的边界
    remaining = collection.get(
        include=["metadatas"]
    )

    assert remaining["ids"] == ["2_0"]
    assert remaining["metadatas"][0]["document_id"] == 2
