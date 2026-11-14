"""Prompt construction and mocked SDK forwarding, not real-model acceptance."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

import rag


QUESTION = (
    "请介绍 AI Chat Assistant 项目的整体技术架构，包括数据库、"
    "Agent 两级决策、RAG 检索和使用的模型。"
)
SECTIONS = (
    "1. 项目定位", "2. 后端架构与数据库", "3. Agent 两级决策",
    "4. RAG 检索流程", "5. 核心模型与技术栈",
)


@pytest.fixture
def reference_chunks():
    return [
        ("资料来源：guide.txt\n项目定位：跨境电商导购与知识库客服。"
         "后端使用 Python、FastAPI、MySQL、SQLAlchemy 和 Redis。", 0.9),
        ("资料来源：guide.txt\nAgent 先识别 chat/rag；Chat 内通过 Function Calling"
         "判断是否需要工具。RAG 使用 Embedding、Chroma、Reranker，由 DeepSeek 回答。", 0.8),
    ]


@pytest.mark.parametrize("question", [
    QUESTION,
    "项目整体架构是什么？",
    "请介绍本项目的技术架构。",
    "介绍一下这个项目。",
    "项目使用了哪些技术？",
    "AI Chat Assistant 使用什么技术？",
    "项目介绍",
    "请给我一份项目介绍。",
    "请概括项目的完整技术栈。",
    "请介绍 AI Chat Assistant 项目。",
    "请提供本项目介绍。",
    "请介绍项目整体技术架构，包括数据库与核心模型。",
])
def test_comprehensive_intro_requires_position_and_all_sections(reference_chunks, question):
    original = deepcopy(reference_chunks)
    messages = rag._build_rag_messages(question, reference_chunks)
    prompt = messages[0]["content"]

    assert [message["role"] for message in messages] == ["system", "user"]
    assert all(section in prompt for section in SECTIONS)
    assert [prompt.index(section) for section in SECTIONS] == sorted(
        prompt.index(section) for section in SECTIONS
    )
    assert "必须明确说明参考资料中的项目用途和业务场景" in prompt
    assert "不能只介绍技术栈" in prompt
    assert "分别说明两级职责" in prompt
    assert "chat/rag 意图路由" in prompt
    assert "Chat 内的 Function Calling 工具决策混淆" in prompt
    assert "尽量完整覆盖与问题有关的关键事实" in prompt
    assert "避免机械重复原文" in prompt
    context = "\n\n".join(text for text, score in reference_chunks)
    assert messages[1]["content"] == f"参考资料：\n{context}\n\n用户问题：{question}"
    assert reference_chunks == original


@pytest.mark.parametrize("question", [
    "店铺退货政策是什么？",
    "店铺配送政策是什么？",
    "店铺清关政策是什么？",
    "店铺换货政策是什么？",
    "这个项目使用什么数据库？",
    "项目介绍文件中使用了什么 Embedding 模型？",
    "项目介绍中的 Redis 缓存如何实现？",
    "项目技术架构中的数据库驱动是什么？",
    "本项目 Agent 的整体架构是什么？",
    "项目 Redis 缓存的整体架构是什么？",
    "请介绍项目的清关政策接口。",
    "Python 装饰器是什么？",
    "DEMO-SKU001 还有多少库存？",
])
def test_policy_and_specific_questions_keep_unstructured_base_prompt(reference_chunks, question):
    baseline_prompt = rag._build_rag_messages("配送需要多久？", reference_chunks)[0]["content"]
    messages = rag._build_rag_messages(question, reference_chunks)

    assert messages[0]["content"] == baseline_prompt
    assert all(section not in messages[0]["content"] for section in SECTIONS)
    assert messages[1]["content"].endswith(f"用户问题：{question}")


def test_incomplete_reference_cannot_be_filled_from_section_names():
    messages = rag._build_rag_messages("项目介绍", [("项目名称：示例应用。", 0.7)])
    prompt = messages[0]["content"]

    assert "只写参考资料明确提供的事实" in prompt
    assert "未提供的功能、实现或模型不得编造" in prompt
    assert "计划中的或尚未实现的功能不得写成已实现" in prompt
    assert "资料不足时如实说明当前资料未说明" in prompt
    assert "不要根据这些栏目推断功能已实现" in prompt
    assert "mysql" not in prompt.lower()
    assert "baai/" not in prompt.lower()
    assert "跨境电商导购与知识库客服" not in prompt
    assert "项目名称：示例应用。" in messages[1]["content"]


@pytest.mark.parametrize("question", [QUESTION, "店铺配送政策是什么？"])
def test_original_grounding_and_policy_safeguards_remain(reference_chunks, question):
    prompt = rag._build_rag_messages(question, reference_chunks)[0]["content"]

    for rule in (
        "必须严格依据用户提供的参考资料回答问题",
        "不能根据常识、经验或猜测编造答案",
        "资料没有列出国家名单",
        "资料没有提供具体数字",
        "资料没有说明",
        "不能编造资料来源",
    ):
        assert rule in prompt


@pytest.mark.parametrize("streaming", [False, True])
def test_both_generation_paths_forward_scoped_prompt_without_parameter_changes(
    monkeypatch, reference_chunks, streaming
):
    captured = []

    class FakeStream:
        closed = False

        def __iter__(self):
            for content in ("隔离", "回答"):
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])

        def close(self):
            self.closed = True

    stream = FakeStream()

    def create(**kwargs):
        captured.append(kwargs)
        if kwargs.get("stream"):
            return stream
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="隔离回答"))])

    monkeypatch.setattr(rag, "client", SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    ))
    result = "".join(rag.generate_answer_stream(QUESTION, reference_chunks)) if streaming else (
        rag.generate_answer(QUESTION, reference_chunks)
    )

    assert result == "隔离回答"
    assert len(captured) == 1
    call = captured[0]
    assert set(call) == ({"model", "messages", "stream"} if streaming else {"model", "messages"})
    assert call["model"] == rag.MODEL
    assert call["messages"] == rag._build_rag_messages(QUESTION, reference_chunks)
    assert all(section in call["messages"][0]["content"] for section in SECTIONS)
    if streaming:
        assert call["stream"] is True
        assert stream.closed
