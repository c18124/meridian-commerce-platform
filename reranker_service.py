    # reranker 模块 接收用户问题和 ChromaDB 检索出的候选文本，重新计算相关性并排序
from sentence_transformers import CrossEncoder
from typing import Any


# 1. 指定 Reranker 模型
MODEL_NAME = "BAAI/bge-reranker-base"


# 2. 保存模型对象
_model = None


# 3. 获取模型：延迟加载 + 单例
def get_reranker_model():

    global _model

    if _model is None:
        _model = CrossEncoder(
            MODEL_NAME,
            max_length=512
        )

    return _model


# 4. 对 ChromaDB 检索结果重新排序
def rerank_chunks(
    question: str,
    candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:

    # 4.1 检查用户问题
    if not question.strip():
        raise ValueError("用户问题不能为空")

    # 4.2 没有候选资料，直接返回
    if not candidates:
        return []

    # 4.3 准备问题和文本块配对
    pairs = []

    for candidate in candidates:

        content = candidate.get("content")

        if not isinstance(content, str) or not content.strip():
            raise ValueError("候选文本不能为空")

        pairs.append([
            question.strip(),
            content
        ])

    # 4.4 使用 CrossEncoder 计算相关性分数
    model = get_reranker_model()

    scores = model.predict(
        pairs,
        batch_size=8,
        show_progress_bar=False,
        convert_to_numpy=True
    )

    scores = scores.reshape(-1)

    if len(scores) != len(candidates):
        raise RuntimeError("Reranker 返回的分数数量不正确")

    # 4.5 将分数添加到原始检索结果
    ranked_results = []

    for candidate, score in zip(candidates, scores, strict=True):

        item = dict(candidate)

        item["rerank_score"] = float(score)

        ranked_results.append(item)

    # 4.6 按 Reranker 分数从高到低排序
    ranked_results.sort(
        key=lambda item: item["rerank_score"],
        reverse=True
    )

    return ranked_results
