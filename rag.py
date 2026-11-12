from pathlib import Path
from sentence_transformers import SentenceTransformer
from ai import client, MODEL
from chroma_service import search_similar_chunks
from reranker_service import rerank_chunks

# 获取知识库文件夹的路径
KNOWLEDGE_DIR = Path(__file__).parent / "knowledge_base"  # 获取当前文件的父目录


def load_txt(file_name: str) -> str:
    file_path = KNOWLEDGE_DIR / file_name   # 拼接文件路径

    with open(file_path, "r", encoding="utf-8") as file:
        text = file.read()  # 读取文件内容

    return text


def split_text(
    text: str,
    chunk_size: int = 200,
    overlap: int = 30
) -> list[str]:
    # 1. 检查参数是否合法
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")

    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap 必须大于等于 0 且小于 chunk_size")

    # 2. 按空行拆分段落，并去掉每段首尾的空白
    paragraphs = []

    for paragraph in text.split("\n\n"):  # 按两个换行拆分段落
        paragraph = paragraph.strip()

        if paragraph:
            paragraphs.append(paragraph)

    # 3. 准备保存最终的文本块
    chunks = []    # 最终的文本块列表，已经切分好的文本块
    current_chunk = ""   # 当前缓冲区

    # 4. 逐段处理
    for paragraph in paragraphs:

        # 4.1 如果一个段落本身过长，就单独切分
        if len(paragraph) > chunk_size:

            # 先保存之前积累的文本块
            if current_chunk:
                chunks.append(current_chunk)  # 将当前文本块添加到列表中先
                current_chunk = ""

            # 对超长段落进行固定长度切分
            start = 0

            while start < len(paragraph):
                end = start + chunk_size
                chunk = paragraph[start:end].strip()

                if chunk:
                    chunks.append(chunk)

                start = end - overlap

        else:
            # 4.2 尝试把当前段落合并到正在构建的文本块中
            if not current_chunk:
                current_chunk = paragraph  # 如果当前缓冲区为空，则将其设置为当前文本块

            elif len(current_chunk) + 2 + len(paragraph) <= chunk_size:   #如果当前文本块加缓冲区没有超过chunk_size上限，则将其添加到列表中
                current_chunk += "\n\n" + paragraph   # 将当前文本块和缓冲区合并 中间添加两个换行

            else:
                # 当前段落放不进去，先保存已有文本块
                chunks.append(current_chunk)
                current_chunk = paragraph   #再将当前文本块设置为缓冲区

    # 5. 别忘了保存最后一个尚未写入列表的文本块
    if current_chunk:
        chunks.append(current_chunk)

    return chunks



# if __name__ == "__main__":
#     content = load_txt("project_intro.txt")
#     chunks = split_text(content)

#     print(f"文档总字符数：{len(content)}")
#     print(f"切分后文本块数量：{len(chunks)}")

#     for i, chunk in enumerate(chunks, start=1):
#         print(f"\n--- Chunk {i} ---")
#         print(chunk)

def test_embedding():
    model = SentenceTransformer("BAAI/bge-small-zh-v1.5")

    text = "SQLite 用于保存用户问题和 AI 回答。"

    vector = model.encode(text)

    print("原始文本：", text)
    print("向量类型：", type(vector))
    print("向量维度：", vector.shape)
    print("向量前 10 个数字：", vector[:10])

def retrieve_chunks(question, chunks, vectors, model, top_k=2):  # 检索相关文本
    # 1. 将用户的问题转换成向量
    query_vector = model.encode(   
        question,  
        normalize_embeddings=True
    )

    # 2. 计算问题与所有文本块的相似度
    scores = vectors @ query_vector

    # 3. 按相似度从高到低排列文本块的索引
    ranked_indices = sorted(
        range(len(chunks)),
        key=lambda i: scores[i],
        reverse=True  # 倒序排列
    )

    # 4. 取出最相关的 top_k 个文本块
    results = []

    for i in ranked_indices[:top_k]:
        results.append((chunks[i], float(scores[i])))

    return results


    #讲整理后的文本块等资料 与强约束提示词交给大模型
def generate_answer(question, retrieved_chunks):

    # 1. 将精排后的文本块整理成参考资料
    context = "\n\n".join(
        chunk for chunk, score in retrieved_chunks
    )

    # 2. 组织发送给 DeepSeek 的消息
    messages = [
        {
            "role": "system",
            "content": (
                "你是一个跨境电商演示店铺的知识库客服。"

                "你必须严格依据用户提供的参考资料回答问题。"

                "回答之前，先判断参考资料是否真正包含"
                "回答用户问题所需要的事实。"

                "注意：语义相关不等于有答案。"

                "如果参考资料没有明确提供相关信息，"
                "必须如实说明当前资料未说明，"
                "不能根据常识、经验或猜测编造答案。"

                "如果用户询问具体配送国家，"
                "但资料没有列出国家名单，"
                "必须说明资料未提供配送国家信息。"

                "如果用户询问具体运费金额，"
                "但资料没有提供具体数字，"
                "必须说明没有具体金额，"
                "可以告知用户以结账页显示为准。"

                "如果用户询问是否提供加急配送，"
                "但资料没有说明，"
                "必须说明资料未说明是否提供，"
                "不能直接回答提供或不提供。"

                "如果资料只能回答问题的一部分，"
                "只回答有依据的部分，"
                "并明确指出缺少的信息。"

                "回答使用中文，表达清晰、简洁。"

                "可以指出参考资料的文件名，"
                "但不能编造资料来源。"
            )
        },
        {
            "role": "user",
            "content": (
                f"参考资料：\n{context}\n\n"
                f"用户问题：{question}"
            )
        }
    ]

    # 3. 调用 DeepSeek API
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages
    )

    # 4. 提取回答
    answer = response.choices[0].message.content

    if not isinstance(answer, str) or not answer.strip():
        return "抱歉，暂时无法生成可靠回答，请稍后重试。"

    return answer.strip()



# 保存已经初始化的 RAG 数据
_rag_model = None
_rag_chunks = None
_rag_vectors = None



def initialize_rag():
    global _rag_model, _rag_chunks, _rag_vectors

    # 1. 如果已经初始化，就不重复加载
    if _rag_model is not None:
        return

    # 2. 找到知识库文件夹中的所有 txt 文件
    txt_files = sorted(KNOWLEDGE_DIR.glob("*.txt"))

    if not txt_files:
        raise FileNotFoundError(
            f"知识库文件夹中没有 txt 文件：{KNOWLEDGE_DIR}"
        )

    # 3. 读取所有文档，并切分成文本块
    chunks = []

    for file_path in txt_files:  # 遍历所有文件
        text = file_path.read_text(encoding="utf-8").strip()   # 读取文件内容并去除换行符

        # 跳过空文档
        if not text:
            continue

        document_chunks = split_text(text)

        # 给每个文本块添加来源文件名
        for chunk in document_chunks:
            chunks.append(
                f"资料来源：{file_path.name}\n{chunk}"
            )

    if not chunks:
        raise ValueError("知识库中的 txt 文件没有有效内容")

    # 4. 加载 Embedding 模型
    model = SentenceTransformer("BAAI/bge-small-zh-v1.5")

    # 5. 将所有文本块转换成向量
    vectors = model.encode(
        chunks,
        normalize_embeddings=True  # 将向量标准化为1的向量
    )

    # 6. 保存初始化结果，供后续问题重复使用
    _rag_model = model
    _rag_chunks = chunks
    _rag_vectors = vectors




    #rag回答问题的完整流程函数
def answer_question(question: str) -> str:

    # 1. 从 ChromaDB 召回候选文本块
    candidates = search_similar_chunks(
        question,
        top_k=3
    )

    # 2. 如果没有检索到资料
    if not candidates:
        return "抱歉，当前知识库中没有找到相关资料。"

    # 3. 使用 Reranker 对候选文本重新排序
    ranked_results = rerank_chunks(
        question,
        candidates
    )

    # 4. 如果精排结果为空
    if not ranked_results:
        return "抱歉，当前没有找到足够的参考资料。"

    # 5. 准备最终交给大模型的参考资料
    retrieved_chunks = []

    for result in ranked_results:

        # 5.1 获取文本内容
        content = result["content"]

        # 5.2 获取文档元数据
        metadata = result.get("metadata") or {}

        filename = metadata.get(
            "filename",
            "未知文件"
        )

        chunk_index = metadata.get(
            "chunk_index",
            "未知"
        )

        # 5.3 整理资料来源
        chunk = (
            f"资料来源：{filename}\n"
            f"文本块编号：{chunk_index}\n"
            f"{content}"
        )

        # 5.4 保存文本和精排分数
        retrieved_chunks.append(
            (chunk, result["rerank_score"])
        )

    # 6. 打印精排结果，方便调试
    print("\n--- RAG 最终检索结果 ---")

    for rank, (chunk, score) in enumerate(
        retrieved_chunks,
        start=1
    ):

        print(f"\n第 {rank} 条结果")
        print(f"Reranker 分数：{score:.4f}")
        print(f"参考资料：\n{chunk}")

    # 7. 将精排后的资料交给 DeepSeek
    answer = generate_answer(
        question,
        retrieved_chunks
    )

    # 8. 返回最终回答
    return answer
