    #测试chromaDB的连接和基础功能
import chromadb

    #希尔测试
def test_chroma_add_and_get(tmp_path):

    # 1. 创建一个临时向量数据库
    client = chromadb.PersistentClient(
        path=str(tmp_path / "chroma_test")
    )

    # 2. 创建测试集合
    collection = client.get_or_create_collection(
        name="rag_chunks_test",
        configuration={
            "hnsw": {
                "space": "cosine"
            }
        },
        embedding_function=None
    )

    # 3. 添加一条向量记录
    collection.add(
        ids=["1_0"],
        embeddings=[
            [0.1, 0.2, 0.3]
        ],
        documents=[
            "Python 使用字典保存键值对"
        ],
        metadatas=[
            {
                "document_id": 1,
                "filename": "python_notes.txt",
                "chunk_index": 0
            }
        ]
    )

    # 4. 根据 ID 查询刚刚添加的记录
    result = collection.get(
        ids=["1_0"],
        include=[
            "documents",
            "metadatas",
            "embeddings"
        ]
    )

    # 5. 验证查询结果
    assert result["ids"] == ["1_0"]

    assert result["documents"] == [
        "Python 使用字典保存键值对"
    ]

    assert result["metadatas"][0]["document_id"] == 1

    assert len(result["embeddings"][0]) == 3

    assert collection.count() == 1



    #测试query() 语义检索，文本相似度
def test_chroma_query_returns_nearest_chunk(tmp_path):

    # 1. 创建临时数据库
    client = chromadb.PersistentClient(
        path=str(tmp_path / "chroma_query_test")
    )

    # 2. 创建集合
    collection = client.get_or_create_collection(
        name="rag_query_test",
        configuration={
            "hnsw": {
                "space": "cosine"
            }
        },
        embedding_function=None
    )

    # 3. 添加两条测试数据
    collection.add(
        ids=["1_0", "1_1"],

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

    # 4. 使用一个向量进行相似度检索
    result = collection.query(
        query_embeddings=[
            [0.1, 0.2, 0.3]
        ],
        n_results=2,
        include=[
            "documents",
            "metadatas",
            "distances"
        ]
    )

    # 5. 验证最相似的结果排在第一位
    assert result["ids"][0][0] == "1_0"

    # 6. 验证对应文本
    assert result["documents"][0][0] == (
        "Python 使用字典保存键值对"
    )

    # 7. 验证距离从小到大排列
    assert (
        result["distances"][0][0]
        < result["distances"][0][1]
    )
