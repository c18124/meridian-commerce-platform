"""Isolated context-coverage regressions; mocked retrieval is not model acceptance."""
from copy import deepcopy

import pytest

import rag


QUESTION = (
    "请介绍 AI Chat Assistant 项目的整体技术架构，包括数据库、"
    "Agent 两级决策、RAG 检索和使用的模型。"
)


@pytest.fixture
def coverage_candidates():
    # Reproduce the real semantic failure with unrelated IDs and source metadata.
    contents = [
        "平台技术总览：FastAPI 后端，MySQL 业务库，Redis 缓存与并发锁。"
        "Agent 先识别 chat/rag，chat 通过 Function Calling 查商品；"
        "RAG 使用 Embedding、Chroma 向量检索、Reranker 重排，DeepSeek 回答。",
        "项目定位：基于 DeepSeek 的跨境电商导购、商品库存查询和知识库客服。",
        "Agent 第一级决策：根据当前问题识别 chat 或 rag，再将 chat 交给"
        "Function Calling Agent，rag 进入知识库。",
        "Agent 第二级决策：Chat 分支由 DeepSeek 通过 Function Calling 自动判断"
        "是否需要商品工具；普通问题直接回答，工具结果交回模型生成回答。",
        "后端架构：使用 Python、FastAPI、Pydantic 和 Uvicorn，"
        "通过 SQLAlchemy 会话访问数据库。",
    ]
    return [
        {
            "id": f"fixture-{index}",
            "content": content,
            "metadata": {
                "filename": "system_handbook.txt",
                "document_id": 703,
                "chunk_index": 30 + index,
            },
            "distance": [0.26, 0.24, 0.38, 0.37, 0.36][index],
            "rerank_score": [0.9942, 0.9678, 0.8053, 0.7976, 0.1903][index],
        }
        for index, content in enumerate(contents)
    ]


def assert_complete_facts(selected):
    text = "\n".join(item["content"] for item in selected)
    for fact in (
        "Python", "FastAPI", "MySQL", "SQLAlchemy", "Redis", "chat/rag",
        "Embedding", "Chroma", "Reranker", "DeepSeek",
    ):
        assert fact in text
    assert "先识别 chat/rag" in text
    assert "第二级决策" in text
    assert "Function Calling 自动判断是否需要商品工具" in text
    assert len(selected) <= 3


def test_real_failed_compound_question_complements_overview(coverage_candidates):
    original = deepcopy(coverage_candidates)
    selected = rag.select_context_candidates(QUESTION, coverage_candidates)

    assert_complete_facts(selected)
    assert [item["id"] for item in selected] == ["fixture-0", "fixture-3", "fixture-4"]
    assert all(item is coverage_candidates[int(item["id"].split("-")[1])] for item in selected)
    assert coverage_candidates == original


def test_pipeline_keeps_top_five_original_scores_and_metadata(
    monkeypatch, coverage_candidates
):
    original = deepcopy(coverage_candidates)

    def search(question, top_k):
        assert question == QUESTION
        assert top_k == 5
        return coverage_candidates

    def rerank(question, candidates):
        assert candidates is coverage_candidates
        assert len(candidates) == 5
        return candidates

    monkeypatch.setattr(rag, "search_similar_chunks", search)
    monkeypatch.setattr(rag, "rerank_chunks", rerank)
    contexts, fallback = rag.retrieve_rag_context(QUESTION)

    assert fallback is None
    assert len(contexts) == 3
    for (text, score), index in zip(contexts, (0, 3, 4), strict=True):
        candidate = coverage_candidates[index]
        assert candidate["content"] in text
        assert candidate["metadata"]["filename"] in text
        assert f"文本块编号：{candidate['metadata']['chunk_index']}" in text
        assert score == candidate["rerank_score"]
    assert coverage_candidates == original


@pytest.mark.parametrize("question", [
    "项目使用什么数据库？",
    "本项目 Agent 如何实现两级决策？",
    "本项目 Redis 缓存和并发锁如何实现？",
    "项目使用什么 Embedding 模型、向量数据库和 Reranker？",
    "本项目 Agent 的整体架构是什么？",
    "项目 Redis 缓存的整体架构是什么？",
])
def test_specific_question_keeps_model_order(coverage_candidates, question):
    # A high-scoring relevant detail must not be displaced by a low-scoring summary.
    ranked = [coverage_candidates[4], *coverage_candidates[1:4], coverage_candidates[0]]
    assert rag.select_context_candidates(question, ranked) == ranked[:3]


@pytest.mark.parametrize("question", [
    "请介绍项目的整体技术架构，包括数据库和 Agent 两级决策。",
    "请概括项目的完整技术栈，包括后端、Agent 和 RAG 模型。",
])
def test_multiple_topic_wordings_cover_complementary_details(coverage_candidates, question):
    selected = rag.select_context_candidates(question, coverage_candidates)
    assert_complete_facts(selected)


def test_foreign_source_cannot_supply_coverage(coverage_candidates):
    coverage_candidates[4]["metadata"]["document_id"] = 999
    selected = rag.select_context_candidates(QUESTION, coverage_candidates)
    assert coverage_candidates[4] not in selected
    assert len(selected) == 3


def test_planned_backend_is_not_counted_as_implemented(coverage_candidates):
    coverage_candidates[4]["content"] = "后端架构：计划使用 Python、SQLAlchemy。"
    selected = rag.select_context_candidates(QUESTION, coverage_candidates)
    assert coverage_candidates[4] not in selected
    assert coverage_candidates[3] in selected


def test_equal_coverage_keeps_existing_relevance_order(coverage_candidates):
    coverage_candidates[3]["content"] = coverage_candidates[2]["content"]
    coverage_candidates[4]["content"] = coverage_candidates[1]["content"]
    ranked = [coverage_candidates[1], coverage_candidates[0], *coverage_candidates[2:]]
    assert rag.select_context_candidates(QUESTION, ranked) == ranked[:3]


@pytest.mark.parametrize("count", [0, 1, 2, 3, 4, 5])
def test_compound_selection_never_pads_or_exceeds_limit(coverage_candidates, count):
    selected = rag.select_context_candidates(QUESTION, coverage_candidates[:count])
    assert len(selected) == min(count, 3)
    assert len({item["id"] for item in selected}) == len(selected)


@pytest.mark.parametrize("question", [
    "店铺退货政策是什么？", "店铺配送政策是什么？",
    "店铺清关政策是什么？", "店铺换货政策是什么？",
])
def test_policy_queries_do_not_enable_architecture_coverage(coverage_candidates, question):
    assert rag.select_context_candidates(question, coverage_candidates) == coverage_candidates[:3]
