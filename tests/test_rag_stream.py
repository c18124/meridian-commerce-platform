    #rag 流式输出回答函数和接口的测试接
from types import SimpleNamespace
import pytest

import rag


# 测试 1：知识库没有检索到内容
def test_rag_stream_returns_fallback_when_no_candidates(monkeypatch):

    monkeypatch.setattr(
        rag,
        "search_similar_chunks",
        lambda question, top_k: []
    )

    result = list(
        rag.stream_answer_question("配送需要多久？")
    )

    assert result == [
        "抱歉，当前知识库中没有找到相关资料。"
    ]


# 测试 2：Reranker 没有返回有效结果
def test_rag_stream_returns_fallback_when_no_ranked_results(monkeypatch):

    monkeypatch.setattr(
        rag,
        "search_similar_chunks",
        lambda question, top_k: [
            {"content": "候选资料"}
        ]
    )

    monkeypatch.setattr(
        rag,
        "rerank_chunks",
        lambda question, candidates: []
    )

    result = list(
        rag.stream_answer_question("配送需要多久？")
    )

    assert result == [
        "抱歉，当前没有找到足够的参考资料。"
    ]


# 测试 3：DeepSeek 是否真正开启了流式输出
def test_generate_answer_stream_uses_stream_mode_and_closes_response(monkeypatch):

    received = {}

    class FakeResponse:

        def __init__(self):
            self.closed = False

        def __iter__(self):

            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="你好，"
                        )
                    )
                ]
            )

            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="这是流式回答。"
                        )
                    )
                ]
            )

        def close(self):
            self.closed = True

    fake_response = FakeResponse()

    def fake_create(**kwargs):

        received.update(kwargs)

        return fake_response

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=fake_create
            )
        )
    )

    monkeypatch.setattr(
        rag,
        "client",
        fake_client
    )

    result = list(
        rag.generate_answer_stream(
            "Python 是什么？",
            [
                ("资料来源：python.txt\nPython 是一种编程语言。", 0.95)
            ]
        )
    )

    assert "".join(result) == "你好，这是流式回答。"

    assert received["stream"] is True

    assert received["model"] == rag.MODEL

    assert "Python 是一种编程语言" in received["messages"][1]["content"]

    assert fake_response.closed is True


# 测试 4：完整 RAG 流式处理流程
def test_stream_answer_question_retrieves_reranks_then_generates(monkeypatch):

    received = {}

    candidates = [
        {"content": "候选资料"}
    ]

    ranked_results = [
        {
            "content": "发货规则",
            "metadata": {
                "filename": "shipping.txt",
                "chunk_index": 0
            },
            "rerank_score": 0.95
        }
    ]

    monkeypatch.setattr(
        rag,
        "search_similar_chunks",
        lambda question, top_k: candidates
    )

    monkeypatch.setattr(
        rag,
        "rerank_chunks",
        lambda question, candidates: ranked_results
    )

    def fake_generate(question, retrieved_chunks):

        received["question"] = question
        received["chunks"] = retrieved_chunks

        yield "根据知识库，"
        yield "商品预计发货。"

    monkeypatch.setattr(
        rag,
        "generate_answer_stream",
        fake_generate
    )

    result = list(
        rag.stream_answer_question("商品什么时候发货？")
    )

    assert result == [
        "根据知识库，",
        "商品预计发货。"
    ]

    assert received["question"] == "商品什么时候发货？"

    assert len(received["chunks"]) == 1

    assert "shipping.txt" in received["chunks"][0][0]



@pytest.fixture
def five_candidates():
    return [
        {
            "id": f"document_{index}_0",
            "content": f"候选资料 {index}",
            "metadata": {
                "filename": f"source_{index}.txt",
                "document_id": 100 + index,
                "chunk_index": index,
            },
            "distance": (index + 1) / 10,
        }
        for index in range(5)
    ]


@pytest.mark.parametrize("winner_index", [3, 4])
def test_stream_reranks_all_five_candidates_and_generates_with_top_three(
    monkeypatch, five_candidates, winner_index
):
    received = {}
    ranked_results = sorted(
        [
            {
                **candidate,
                "rerank_score": 0.99 if index == winner_index else (5 - index) / 10,
            }
            for index, candidate in enumerate(five_candidates)
        ],
        key=lambda item: item["rerank_score"],
        reverse=True,
    )
    original_metadata = [dict(item["metadata"]) for item in five_candidates]

    def fake_search(question, top_k):
        received["search"] = (question, top_k)
        return five_candidates

    def fake_rerank(question, candidates):
        received["rerank_question"] = question
        assert candidates is five_candidates
        assert len(candidates) == 5
        assert [item["metadata"] for item in candidates] == original_metadata
        return ranked_results

    def fake_generate(question, chunks):
        received["generate_question"] = question
        received["chunks"] = chunks
        yield "隔离测试回答"

    monkeypatch.setattr(rag, "search_similar_chunks", fake_search)
    monkeypatch.setattr(rag, "rerank_chunks", fake_rerank)
    monkeypatch.setattr(rag, "generate_answer_stream", fake_generate)

    question = "项目使用什么数据库？"
    assert list(rag.stream_answer_question(question)) == ["隔离测试回答"]

    assert received["search"] == (question, 5)
    assert received["rerank_question"] == question
    assert received["generate_question"] == question
    expected = [
        (
            f"资料来源：{item['metadata']['filename']}\n"
            f"文本块编号：{item['metadata']['chunk_index']}\n"
            f"{item['content']}",
            item["rerank_score"],
        )
        for item in ranked_results[:3]
    ]
    assert received["chunks"] == expected
    assert len(received["chunks"]) == 3
    assert five_candidates[winner_index]["content"] in received["chunks"][0][0]
    assert received["chunks"][0][1] == 0.99
    assert [item["metadata"] for item in five_candidates] == original_metadata


@pytest.mark.parametrize("count", [1, 2])
def test_context_keeps_available_candidates_without_duplicate_padding(
    monkeypatch, five_candidates, count
):
    candidates = five_candidates[:count]
    ranked = [
        {**item, "rerank_score": (count - index) / 10}
        for index, item in enumerate(candidates)
    ]

    def fake_search(question, top_k):
        assert top_k == 5
        return candidates

    monkeypatch.setattr(rag, "search_similar_chunks", fake_search)
    monkeypatch.setattr(rag, "rerank_chunks", lambda question, items: ranked)

    chunks, fallback = rag.retrieve_rag_context("资料不足五条时如何处理？")

    assert fallback is None
    assert len(chunks) == count
    assert len({text for text, score in chunks}) == count
    assert [score for text, score in chunks] == [
        item["rerank_score"] for item in ranked
    ]


@pytest.mark.parametrize("failure_stage", ["search", "rerank"])
def test_retrieval_errors_still_propagate(monkeypatch, five_candidates, failure_stage):
    def fake_search(question, top_k):
        if failure_stage == "search":
            raise RuntimeError("检索测试异常")
        return five_candidates

    def fake_rerank(question, candidates):
        raise RuntimeError("检索测试异常")

    monkeypatch.setattr(rag, "search_similar_chunks", fake_search)
    monkeypatch.setattr(rag, "rerank_chunks", fake_rerank)

    with pytest.raises(RuntimeError, match="检索测试异常"):
        rag.retrieve_rag_context("项目使用什么数据库？")
