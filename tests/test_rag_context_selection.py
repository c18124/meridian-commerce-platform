"""Context-selection regression tests with isolated fixtures, not real-model acceptance."""
from copy import deepcopy

import pytest

import rag


def candidate(identifier, content, filename, document_id, distance, score):
    return {
        "id": identifier,
        "content": content,
        "metadata": {
            "filename": filename,
            "document_id": document_id,
            "chunk_index": len(identifier),
        },
        "distance": distance,
        "rerank_score": score,
    }


@pytest.fixture
def architecture_candidates():
    # Deliberately use different IDs, source names and chunk indexes from production.
    return [
        candidate(
            "deployment-detail",
            "运行与部署：应用使用 Docker；未定义 MySQL、Redis 服务或 Chroma 数据挂载。",
            "platform_notes_v2.txt", 101, 0.5740, 0.01049,
        ),
        candidate(
            "backend-detail",
            "后端架构：Python、FastAPI、Pydantic、Uvicorn，按业务服务分层。",
            "platform_notes_v2.txt", 101, 0.4877, 0.00615,
        ),
        candidate(
            "frontend-detail",
            "前端技术：原生 HTML、CSS、JavaScript，支持 Markdown 渲染。",
            "platform_notes_v2.txt", 101, 0.5931, 0.00521,
        ),
        candidate(
            "project-purpose",
            "项目定位：跨境电商导购与知识库客服。",
            "platform_notes_v2.txt", 101, 0.5047, 0.00353,
        ),
        candidate(
            "technical-summary",
            "示例平台技术总览：FastAPI 后端、MySQL 业务库、Redis 缓存；"
            "Agent 先识别 chat/rag，chat 用 Function Calling 查商品；"
            "RAG 用 Embedding 和 Chroma 检索、Reranker 重排，DeepSeek 回答。",
            "platform_notes_v2.txt", 101, 0.5707, 0.00253,
        ),
    ]


@pytest.mark.parametrize("question", [
    "项目整体技术架构是什么？",
    "请介绍 AI Chat Assistant 项目的整体技术架构。",
    "请概括项目的完整技术栈。",
])
def test_overall_architecture_keeps_multitopic_overview_and_best_details(
    architecture_candidates, question
):
    original = deepcopy(architecture_candidates)
    selected = rag.select_context_candidates(question, architecture_candidates)

    assert len(selected) == 3
    assert selected[0]["id"] == "technical-summary"
    assert [item["id"] for item in selected[1:]] == [
        "deployment-detail", "backend-detail",
    ]
    text = "\n".join(item["content"] for item in selected)
    for fact in [
        "FastAPI", "MySQL", "Redis", "chat/rag", "Function Calling",
        "Embedding", "Chroma", "Reranker", "DeepSeek",
    ]:
        assert fact in text
    assert architecture_candidates == original


@pytest.mark.parametrize("question", [
    "项目使用什么数据库？",
    "项目使用什么 SQL ORM 和驱动？",
    "本项目 Agent 如何实现两级决策？",
    "项目的 Redis 缓存与并发控制如何实现？",
    "项目使用什么 Embedding 和 Chroma？",
    "本项目 Agent 的整体架构是什么？",
    "项目 Redis 缓存的整体架构是什么？",
    "技术总览中的数据库驱动是什么？",
])
def test_specific_questions_keep_original_relevance_order(
    architecture_candidates, question
):
    assert rag.select_context_candidates(
        question, architecture_candidates
    ) == architecture_candidates[:3]


@pytest.mark.parametrize("invalid_overview", [
    "项目技术总览：仅使用 Redis 缓存。",
    "项目技术总览：计划使用 FastAPI、MySQL、Redis、Agent、RAG。",
])
def test_shallow_or_planned_overviews_do_not_displace_details(
    architecture_candidates, invalid_overview
):
    architecture_candidates[-1]["content"] = invalid_overview
    assert rag.select_context_candidates(
        "项目整体技术架构是什么？", architecture_candidates
    ) == architecture_candidates[:3]


def test_unrelated_document_overview_is_not_promoted(architecture_candidates):
    architecture_candidates[-1]["metadata"]["document_id"] = 999
    assert rag.select_context_candidates(
        "项目整体技术架构是什么？", architecture_candidates
    ) == architecture_candidates[:3]


def test_missing_source_or_distance_preserves_existing_order(architecture_candidates):
    for item in architecture_candidates:
        item.pop("distance")
    assert rag.select_context_candidates(
        "项目整体技术架构是什么？", architecture_candidates
    ) == architecture_candidates[:3]


def test_overview_already_in_top_three_is_not_unconditionally_boosted(
    architecture_candidates,
):
    overview = architecture_candidates.pop()
    overview["rerank_score"] = 0.009
    architecture_candidates.insert(1, overview)
    assert rag.select_context_candidates(
        "项目整体技术架构是什么？", architecture_candidates
    ) == architecture_candidates[:3]


def test_pipeline_applies_selection_without_changing_scores_or_metadata(
    monkeypatch, architecture_candidates
):
    raw_candidates = sorted(architecture_candidates, key=lambda row: row["distance"])
    original = deepcopy(architecture_candidates)

    def search(question, top_k):
        assert top_k == 5
        return raw_candidates

    def rerank(question, candidates):
        assert candidates is raw_candidates
        assert len(candidates) == 5
        return architecture_candidates

    monkeypatch.setattr(rag, "search_similar_chunks", search)
    monkeypatch.setattr(rag, "rerank_chunks", rerank)
    contexts, fallback = rag.retrieve_rag_context("项目整体技术架构是什么？")

    assert fallback is None
    assert len(contexts) == 3
    for (text, score), item in zip(
        contexts, [architecture_candidates[4], *architecture_candidates[:2]]
    ):
        assert item["content"] in text
        assert item["metadata"]["filename"] in text
        assert f"文本块编号：{item['metadata']['chunk_index']}" in text
        assert score == item["rerank_score"]
    assert architecture_candidates == original


@pytest.fixture
def policy_candidates():
    return [
        candidate(
            "shipping",
            "演示店铺配送政策\n\n发货后预计 7 至 15 个工作日送达，"
            "清关延误可能影响配送，订单总价含进口税费。",
            "shipping_notes.txt", 201, 0.4053, 0.96828,
        ),
        candidate(
            "returns",
            "演示店铺退货政策\n\n签收后 14 天内申请退货，"
            "因个人原因退货由顾客承担运费。",
            "returns_notes.txt", 202, 0.4603, 0.95324,
        ),
        candidate(
            "customs",
            "演示店铺进口税费与清关政策\n\n进口关税由店铺承担，"
            "顾客收货时无需另付进口税费。",
            "customs_notes.txt", 203, 0.3059, 0.93803,
        ),
        candidate(
            "exchange-fragment",
            "质量问题的替换商品由店铺承担运费。缺货时可按退货政策申请退货。",
            "exchange_notes.txt", 204, 0.4879, 0.90831,
        ),
        candidate(
            "exchange-heading",
            "演示店铺换货政策\n\n签收后 14 天内凭订单编号申请换货。",
            "exchange_notes.txt", 204, 0.4430, 0.77711,
        ),
    ]


@pytest.mark.parametrize(
    ("question", "expected_id"),
    [
        ("店铺清关政策是什么？", "customs"),
        ("店铺进口关税政策是什么？", "customs"),
        ("店铺退货政策是什么？", "returns"),
        ("店铺配送政策是什么？", "shipping"),
        ("店铺换货政策是什么？", "exchange-fragment"),
    ],
)
def test_explicit_policy_topic_matches_own_source(
    policy_candidates, question, expected_id
):
    original = deepcopy(policy_candidates)
    selected = rag.select_context_candidates(question, policy_candidates)
    assert selected[0]["id"] == expected_id
    assert len(selected) == 3
    assert policy_candidates == original
    if expected_id == "customs":
        assert "进口关税由店铺承担" in selected[0]["content"]
        assert selected[0]["id"] != "shipping"


def test_policy_selection_does_not_force_original_nearest_first(policy_candidates):
    policy_candidates[0]["distance"] = 0.1
    policy_candidates[2]["distance"] = 0.7
    selected = rag.select_context_candidates("店铺清关政策是什么？", policy_candidates)
    assert selected[0]["id"] == "customs"
    assert min(policy_candidates, key=lambda row: row["distance"])["id"] == "shipping"


def test_policy_title_works_without_fixed_filename(policy_candidates):
    policy_candidates[2]["metadata"]["filename"] = "rules_2026.txt"
    assert rag.select_context_candidates(
        "店铺清关政策是什么？", policy_candidates
    )[0]["id"] == "customs"


@pytest.mark.parametrize("wrong_content", [
    "演示店铺配送政策\n\n请查看结账页的运费。",
    "Python 函数和数据库教程。",
])
def test_filename_alone_or_conflicting_title_cannot_force_match(
    policy_candidates, wrong_content
):
    policy_candidates[2]["content"] = wrong_content
    assert rag.select_context_candidates(
        "店铺清关政策是什么？", policy_candidates
    ) == policy_candidates[:3]


@pytest.mark.parametrize("question", [
    "比较清关和配送政策。",
    "本项目如何实现清关政策接口？",
    "店铺支付政策是什么？",
])
def test_ambiguous_technical_or_unknown_policy_keeps_order(policy_candidates, question):
    assert rag.select_context_candidates(
        question, policy_candidates
    ) == policy_candidates[:3]


@pytest.mark.parametrize("count", [0, 1, 2])
def test_selection_does_not_duplicate_or_pad(architecture_candidates, count):
    selected = rag.select_context_candidates(
        "项目整体技术架构是什么？", architecture_candidates[:count]
    )
    assert len(selected) == count
    assert len({row["id"] for row in selected}) == count
