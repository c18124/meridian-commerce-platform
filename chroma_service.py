    #将拆分完成的文本块接受，生成向量然后保存到 ChromaDB库，根据用户问题检索相关文本块，删除指定文档的全部向量
    # 操作文本块向量在ChormaDB的功能管理，专门负责向量数据库操作
from chroma_client import rag_collection
from embedding_service import encode_texts, encode_query



# 将文档拆分好的文本块生成向量并一同保存到 ChromaDB
def add_document_chunks(
    document_id: int,
    filename: str,
    chunks: list[str]
) -> list[str]:

    # 1. 检查是否有有效文本块
    if not chunks:
        raise ValueError("文本块不能为空")

    if any(not chunk.strip() for chunk in chunks):
        raise ValueError("文本块不能包含空内容")

    # 2. 为每个文本块生成唯一 ID
    ids = [
        f"{document_id}_{index}"
        for index in range(len(chunks))
    ]

    # 3. 使用 Embedding 模型生成向量
    embeddings = encode_texts(chunks)

    # 4. 为每个文本块准备元数据
    metadatas = [
        {
            "document_id": document_id,
            "filename": filename,
            "chunk_index": index
        }
        for index in range(len(chunks))
    ]

    # 5. 将文本、向量、元数据写入 ChromaDB
    rag_collection.add(
        ids=ids,
        embeddings=embeddings,  #保存的时候带上文本块对应的向量
        documents=chunks,
        metadatas=metadatas
    )

    # 6. 返回生成的 ID
    return ids



# 根据用户问题检索相关文本块
def search_similar_chunks(
    question: str,
    top_k: int = 3
) -> list[dict]:

    # 1. 检查用户问题
    if not question.strip():
        raise ValueError("用户问题不能为空")

    # 2. 检查检索数量
    if top_k <= 0:
        raise ValueError("top_k 必须大于 0")

    # 3. 获取当前向量数据库中的记录数量
    total = rag_collection.count()

    # 4. 如果没有数据，直接返回空列表
    if total == 0:
        return []

    # 5. 将用户问题转换成向量
    query_vector = encode_query(question)

    # 6. 执行向量相似度检索
    result = rag_collection.query(
        query_embeddings=[query_vector],
        n_results=min(top_k, total),
        include=[
            "documents",
            "metadatas",
            "distances"
        ]
    )

    # 7. 准备最终返回的数据
    matches = []

    # 8. 遍历检索结果
    for index, chunk_id in enumerate(result["ids"][0]):

        matches.append({
            "id": chunk_id,
            "content": result["documents"][0][index],
            "metadata": result["metadatas"][0][index],
            "distance": result["distances"][0][index]
        })

    # 9. 返回检索结果
    return matches



# 删除指定文档的全部向量
def delete_document_chunks(document_id: int) -> int:

    # 1. 检查文档 ID
    if document_id <= 0:
        raise ValueError("document_id 必须大于 0")

    # 2. 根据 document_id 查询对应的全部文本块 ID
    result = rag_collection.get(
        where={
            "document_id": document_id
        },
        include=["metadatas"]
    )

    # 3. 提取所有匹配的 Chunk ID
    chunk_ids = result["ids"]

    # 4. 如果没有找到对应的文本块
    if not chunk_ids:
        return 0

    # 5. 删除这些向量记录
    rag_collection.delete(
        ids=chunk_ids
    )

    # 6. 返回实际删除数量
    return len(chunk_ids)
