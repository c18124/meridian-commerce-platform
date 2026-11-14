from pathlib import Path
from itertools import combinations
from sentence_transformers import SentenceTransformer
from ai import client, MODEL
from chroma_service import search_similar_chunks
from reranker_service import rerank_chunks
import logging
import math
import re

logger = logging.getLogger(__name__)

RAG_CANDIDATE_K = 5
RAG_CONTEXT_K = 3

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

    # 统一不同操作系统的换行符
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    
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



# 统一构建 RAG 提示词
def _build_rag_messages(question, retrieved_chunks):

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

    compact_question = re.sub(r"\s+", "", question).replace("的", "").rstrip("。？！.!?")
    project_intro = re.search(
        r"(?:项目|系统|aichatassistant)(?:整体(?:技术)?架构|技术架构|(?:完整|整体)?技术栈)"
        r"(?:是什么|是怎样|有哪些|包括|包含|[，,。？?：:]|$)"
        r"|(?:介绍|概述|概括)(?:一下)?(?:本|这个|该)?(?:项目|aichatassistant(?:项目)?)$"
        r"|(?:项目|aichatassistant(?:项目)?)(?:使用|采用|用)了?(?:哪些|什么)技术(?:栈)?(?:[，,。？?：:]|$)"
        r"|^(?:请)?(?:给我(?:一份)?|提供(?:一份)?|写(?:一份)?)?(?:本|这个|该)?项目介绍$",
        compact_question,
        re.IGNORECASE,
    )
    if project_intro:
        messages[0]["content"] += (
            "\n本次是综合性项目介绍，请按以下顺序组织回答：\n"
            "1. 项目定位：必须明确说明参考资料中的项目用途和业务场景，不能只介绍技术栈。\n"
            "2. 后端架构与数据库。\n"
            "3. Agent 两级决策：分别说明两级职责，不能将 chat/rag 意图路由"
            "与 Chat 内的 Function Calling 工具决策混淆。\n"
            "4. RAG 检索流程。\n"
            "5. 核心模型与技术栈。\n"
            "以上各部分只写参考资料明确提供的事实，尽量完整覆盖与问题有关的关键事实。"
            "未提供的功能、实现或模型不得编造；计划中的或尚未实现的功能不得写成已实现。"
            "某部分资料不足时如实说明当前资料未说明，不要根据这些栏目推断功能已实现。"
            "用自然语言概括，避免机械重复原文或重复罗列同一事实。"
        )

    return messages


# 普通 RAG 完整回答（暂时保留，兼容原接口和测试）
def generate_answer(question, retrieved_chunks):

    messages = _build_rag_messages(
        question,
        retrieved_chunks
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=messages
    )

    answer = response.choices[0].message.content

    if not isinstance(answer, str) or not answer.strip():
        return "抱歉，暂时无法生成可靠回答，请稍后重试。"

    return answer.strip()


# RAG 流式生成回答
def generate_answer_stream(question, retrieved_chunks):

    messages = _build_rag_messages(
        question,
        retrieved_chunks
    )

    # 1. 开启 DeepSeek 流式输出
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        stream=True
    )

    answer_parts = []

    try:

        # 2. 逐块接收模型返回的内容
        for chunk in response:

            if not chunk.choices:
                continue

            content = chunk.choices[0].delta.content

            # 3. 只处理真正有内容的部分
            if content:

                answer_parts.append(content)

                # 4. 实时交给 API 层
                yield content

    finally:

        # 5. 确保关闭模型流式连接
        close_response = getattr(
            response,
            "close",
            None
        )

        if callable(close_response):

            try:
                close_response()

            except Exception:
                logger.exception("RAG 流式连接关闭失败")

    # 6. 防止模型没有返回有效内容
    if not "".join(answer_parts).strip():

        yield "抱歉，暂时无法生成可靠回答，请稍后重试。"






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





   
_POLICY_TERMS = {
    "returns": ("退货", "退款"),
    "shipping": ("配送", "发货", "物流"),
    "customs": ("清关", "关税", "进口税", "海关"),
    "exchange": ("换货", "替换商品"),
}
_POLICY_FILENAME_TERMS = {
    "returns": ("return", "returns", "refund", "refunds"),
    "shipping": ("shipping", "delivery", "logistics"),
    "customs": ("customs", "clearance", "tariff", "tariffs"),
    "exchange": ("exchange", "exchanges"),
}
_ARCHITECTURE_FACETS = (
    ("后端", "FastAPI", "Django", "Flask"),
    ("数据库", "业务库", "MySQL", "PostgreSQL", "SQLAlchemy"),
    ("缓存", "Redis"),
    ("Agent", "Function Calling", "工具调用"),
    ("RAG", "Embedding", "向量", "检索", "Reranker"),
    ("前端", "HTML", "JavaScript"),
)


def _policy_topics(text):
    return {
        topic for topic, terms in _POLICY_TERMS.items()
        if any(term in text for term in terms)
    }


def _candidate_policy_topic(candidate):
    content = candidate.get("content", "")
    metadata = candidate.get("metadata") or {}
    filename = Path(str(metadata.get("filename", "")).replace("\\", "/")).stem
    filename_words = set(re.findall(r"[a-z]+", filename.lower()))
    file_topics = {
        topic for topic, terms in _POLICY_FILENAME_TERMS.items()
        if filename_words.intersection(terms)
    }
    # 只把独立标题作为主题证据，正文中的交叉引用不是标题。
    first_line = content.strip().split("\n", 1)[0]
    is_heading = (
        any(word in first_line for word in ("政策", "规则", "须知"))
        and not any(mark in first_line for mark in ("。", "；", ";", "！", "？"))
    )
    title_topics = _policy_topics(first_line) if is_heading else set()
    if len(title_topics) == 1:
        if file_topics and file_topics != title_topics:
            return None
        return next(iter(title_topics))
    if not title_topics and len(file_topics) == 1:
        topic = next(iter(file_topics))
        if topic in _policy_topics(content):
            return topic
    return None


def _overview_breadth(candidate):
    content = candidate.get("content", "")
    heading = re.split(r"[:：\n]", content, maxsplit=1)[0]
    if not any(word in heading for word in ("总览", "概览", "总体架构")):
        return 0
    # 不把计划或否定描述中的技术名词计入已实现的主题覆盖。
    clauses = re.split(r"[。；;\n]", content)
    positive = " ".join(
        clause for clause in clauses
        if not any(word in clause for word in (
            "未使用", "未采用", "未实现", "未定义", "没有", "不使用",
            "不支持", "尚未", "计划", "拟采用",
        ))
    )
    return sum(
        any(term.lower() in positive.lower() for term in terms)
        for terms in _ARCHITECTURE_FACETS
    )


def _candidate_source(candidate):
    metadata = candidate.get("metadata") or {}
    if metadata.get("document_id") is not None:
        return ("document_id", metadata["document_id"])
    if metadata.get("filename"):
        return ("filename", metadata["filename"])
    return None


def _architecture_facts(content):
    # 统计明确实现的事实，不把计划、否定描述当作覆盖。
    positive = " ".join(
        clause for clause in re.split(r"[。；;\n]", content)
        if not any(word in clause for word in (
            "未使用", "未采用", "未实现", "未定义", "没有", "不使用",
            "不支持", "尚未", "计划", "拟采用",
        ))
    ).lower()
    facts = {
        term for term in (
            "python", "fastapi", "mysql", "sqlalchemy", "redis",
            "embedding", "chroma", "reranker", "deepseek",
        ) if term in positive
    }
    if "chat" in positive and "rag" in positive and any(
        word in positive for word in ("识别", "路由", "第一级")
    ):
        facts.add("intent_routing")
    if "function calling" in positive and any(
        word in positive for word in ("判断", "决定", "直接回答")
    ) and any(word in positive for word in ("工具", "函数")):
        facts.add("tool_decision")
    return facts


def _select_architecture_coverage(question, ranked_results, overview):
    # 仅对明确询问多个技术主题的整体架构问题补足事实，具体问题不走此处。
    query = question.lower()
    requested = [
        facts for terms, facts in (
            (("后端", "数据库", "orm", "驱动"),
             {"python", "fastapi", "mysql", "sqlalchemy"}),
            (("agent", "决策", "function calling"),
             {"intent_routing", "tool_decision"}),
            (("rag", "检索", "模型", "embedding", "chroma", "reranker"),
             {"embedding", "chroma", "reranker", "deepseek"}),
            (("redis", "缓存", "并发"), {"redis"}),
        ) if any(term in query for term in terms)
    ]
    if len(requested) < 2:
        return None

    wanted = set().union(*requested)
    source = _candidate_source(overview)
    facts = [
        _architecture_facts(item.get("content", "")) & wanted
        if _candidate_source(item) == source else set()
        for item in ranked_results
    ]
    overview_index = next(
        index for index, item in enumerate(ranked_results) if item is overview
    )
    # 五候选最多只有十种三块组合；覆盖相同时保留原精排顺序。
    choices = (
        indexes for indexes in combinations(
            range(len(ranked_results)), min(RAG_CONTEXT_K, len(ranked_results))
        ) if overview_index in indexes
    )
    best = max(choices, key=lambda indexes: (
        len(set().union(*(facts[index] for index in indexes))),
        tuple(-index for index in indexes),
    ))
    baseline = list(range(min(RAG_CONTEXT_K, len(ranked_results))))
    if overview_index not in baseline:
        baseline = [overview_index, *baseline[:RAG_CONTEXT_K - 1]]
    if len(set().union(*(facts[index] for index in best))) <= len(
        set().union(*(facts[index] for index in baseline))
    ):
        return None
    return [overview] + [
        ranked_results[index] for index in best if index != overview_index
    ]


def select_context_candidates(question, ranked_results):
    """在原精排结果内做有条件的选择，不改分数或增加上下文数量。"""
    if not ranked_results:
        return []

    topics = _policy_topics(question)
    policy_query = (
        any(word in question for word in ("政策", "规则", "规定"))
        and not any(word in question for word in ("实现", "接口", "源码", "代码"))
    )
    preferred = None
    if policy_query and len(topics) == 1:
        topic = next(iter(topics))
        preferred = next(
            (item for item in ranked_results
             if _candidate_policy_topic(item) == topic),
            None,
        )

    compact_question = "".join(question.split()).replace("的", "")
    overview_query = any(phrase in compact_question for phrase in (
        "项目整体架构", "项目整体技术架构", "系统整体架构",
        "系统整体技术架构", "完整技术栈", "整体技术栈",
    ))
    if preferred is None and overview_query:
        with_distance = [
            item for item in ranked_results
            if isinstance(item.get("distance"), (int, float))
            and math.isfinite(item["distance"])
        ]
        if with_distance:
            nearest = min(with_distance, key=lambda item: item["distance"])
            source = _candidate_source(nearest)
            overviews = [
                item for item in ranked_results
                if source is not None and _candidate_source(item) == source
                and _overview_breadth(item) >= 3
            ]
            if overviews:
                overview = max(overviews, key=_overview_breadth)
                covered = _select_architecture_coverage(question, ranked_results, overview)
                if covered is not None:
                    return covered
                if not any(item is overview for item in ranked_results[:RAG_CONTEXT_K]):
                    preferred = overview

    if preferred is not None:
        return ([preferred] + [
            item for item in ranked_results if item is not preferred
        ])[:RAG_CONTEXT_K]
    return ranked_results[:RAG_CONTEXT_K]


# RAG 检索与精排的公共流程 reranker
def retrieve_rag_context(question: str):

    # 1. 从 ChromaDB 召回候选文本块
    candidates = search_similar_chunks(
        question,
        top_k=RAG_CANDIDATE_K
    )

    if not candidates:
        return [], "抱歉，当前知识库中没有找到相关资料。"

    # 2. 使用 Reranker 精排
    ranked_results = rerank_chunks(
        question,
        candidates
    )

    if not ranked_results:
        return [], "抱歉，当前没有找到足够的参考资料。"

    # 3. 整理最终参考资料
    retrieved_chunks = []

    for result in select_context_candidates(question, ranked_results):

        content = result["content"]

        metadata = result.get("metadata") or {}

        filename = metadata.get(
            "filename",
            "未知文件"
        )

        chunk_index = metadata.get(
            "chunk_index",
            "未知"
        )

        chunk = (
            f"资料来源：{filename}\n"
            f"文本块编号：{chunk_index}\n"
            f"{content}"
        )

        retrieved_chunks.append(
            (chunk, result["rerank_score"])
        )

    # 4. 输出调试信息
    print("\n--- RAG 最终检索结果 ---")

    for rank, (chunk, score) in enumerate(
        retrieved_chunks,
        start=1
    ):

        print(f"\n第 {rank} 条结果")
        print(f"Reranker 分数：{score:.4f}")
        print(f"参考资料：\n{chunk}")

    return retrieved_chunks, None


# RAG 非流式回答（暂时保留）
def answer_question(question: str) -> str:

    retrieved_chunks, fallback = retrieve_rag_context(question)

    if fallback:
        return fallback

    return generate_answer(
        question,
        retrieved_chunks
    )


# RAG 流式回答的流程
def stream_answer_question(question: str):

    # 1. 检索知识库并进行精排
    retrieved_chunks, fallback = retrieve_rag_context(question)

    # 2. 如果没有足够的资料
    if fallback:

        yield fallback
        return

    # 3. 将精排结果交给大模型流式生成
    yield from generate_answer_stream(
        question,
        retrieved_chunks
    )
