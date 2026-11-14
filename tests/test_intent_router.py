    #测试意图识别本身的测试集
import json
import pytest

from types import SimpleNamespace

import intent_router


def mock_client(monkeypatch, content=None, error=None, captured=None):

    def create(**kwargs):

        if captured is not None:
            captured.update(kwargs)

        if error is not None:
            raise error

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=content
                    )
                )
            ]
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=create
            )
        )
    )

    monkeypatch.setattr(
        intent_router,
        "client",
        fake_client
    )


def test_classify_rag_intent(monkeypatch):

    mock_client(
        monkeypatch,
        json.dumps({
            "intent": "rag",
            "confidence": 0.95,
            "reason": "询问退货政策"
        })
    )

    result = intent_router.classify_intent(
        "商品退货政策是什么？"
    )

    assert result == "rag"


def test_classify_chat_intent(monkeypatch):

    mock_client(
        monkeypatch,
        json.dumps({
            "intent": "chat",
            "confidence": 0.95,
            "reason": "Python 技术问题"
        })
    )

    result = intent_router.classify_intent(
        "Python 装饰器是什么？"
    )

    assert result == "chat"


def test_low_confidence_falls_back_to_chat(monkeypatch):

    mock_client(
        monkeypatch,
        json.dumps({
            "intent": "rag",
            "confidence": 0.3,
            "reason": "判断不明确"
        })
    )

    result = intent_router.classify_intent(
        "这个问题怎么处理？"
    )

    assert result == "chat"


def test_invalid_json_falls_back_to_chat(monkeypatch):

    mock_client(
        monkeypatch,
        "这不是 JSON"
    )

    result = intent_router.classify_intent(
        "你好"
    )

    assert result == "chat"


def test_model_error_falls_back_to_chat(monkeypatch):

    mock_client(
        monkeypatch,
        error=RuntimeError("模拟模型调用失败")
    )

    result = intent_router.classify_intent(
        "商品退货政策是什么？"
    )

    assert result == "chat"


def test_history_is_sent_to_classifier(monkeypatch):

    captured = {}

    mock_client(
        monkeypatch,
        json.dumps({
            "intent": "rag",
            "confidence": 0.95
        }),
        captured=captured
    )

    history = [
        {
            "role": "user",
            "content": "商品退货政策是什么？"
        },
        {
            "role": "assistant",
            "content": "请参考知识库中的退货政策。"
        }
    ]

    result = intent_router.classify_intent(
        "那退款需要多久？",
        history
    )

    request_content = captured["messages"][1]["content"]

    assert result == "rag"

    assert "那退款需要多久？" in request_content

    assert "商品退货政策是什么？" in request_content

# These cases test request/response handling with Mock, not DeepSeek semantics.
@pytest.mark.parametrize(
    ("question", "expected_intent"),
    [
        ("这个项目使用什么数据库？", "rag"),
        ("本项目 Agent 如何实现两级决策？", "rag"),
        ("项目使用什么 Embedding 模型？", "rag"),
        ("本项目 Redis 缓存和并发锁如何实现？", "rag"),
        ("Python 装饰器是什么？", "chat"),
        ("MySQL 的事务隔离级别是什么？", "chat"),
        ("商城目前有哪些商品？", "chat"),
        ("DEMO-SKU001 还有多少库存？", "chat"),
    ],
)
def test_classifier_sends_prompt_and_parses_mocked_result(
    monkeypatch, question, expected_intent
):
    captured = {}
    mock_client(
        monkeypatch,
        json.dumps({
            "intent": expected_intent,
            "confidence": 0.95,
            "reason": "隔离的模拟分类结果",
        }),
        captured=captured,
    )

    assert intent_router.classify_intent(question, []) == expected_intent

    assert captured["messages"][0] == {
        "role": "system",
        "content": intent_router.SYSTEM_PROMPT,
    }
    assert json.loads(captured["messages"][1]["content"]) == {
        "recent_history": [],
        "current_question": question,
    }
    assert captured["model"] == intent_router.MODEL
    assert captured["temperature"] == 0
    assert captured["max_tokens"] == 120
    assert captured["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize(
    ("previous_question", "question", "expected_intent"),
    [
        ("本项目使用什么数据库？", "那 ORM 和驱动呢？", "rag"),
        ("商品退货政策是什么？", "那个人原因的运费呢？", "rag"),
        ("本项目 Agent 如何工作？", "Python 装饰器是什么？", "chat"),
        ("请介绍项目架构。", "DEMO-SKU001 还有多少库存？", "chat"),
    ],
)
def test_classifier_preserves_followup_and_topic_switch_payload(
    monkeypatch, previous_question, question, expected_intent
):
    captured = {}
    history = [{"role": "user", "content": previous_question}]
    mock_client(
        monkeypatch,
        json.dumps({"intent": expected_intent, "confidence": 0.95}),
        captured=captured,
    )

    assert intent_router.classify_intent(question, history) == expected_intent
    assert json.loads(captured["messages"][1]["content"]) == {
        "recent_history": history,
        "current_question": question,
    }


def test_classifier_limits_and_filters_history_without_mutating_input(monkeypatch):
    captured = {}
    history = [
        {"role": "user", "content": f"历史消息 {index}"}
        for index in range(12)
    ]
    history[7] = {"role": "system", "content": "不应发送"}
    history[8] = {"role": "tool", "content": "不应发送"}
    history[10] = {"role": "assistant", "content": "长" * 1600}
    original = [dict(message) for message in history]
    mock_client(
        monkeypatch,
        json.dumps({"intent": "rag", "confidence": 0.95}),
        captured=captured,
    )

    assert intent_router.classify_intent("那它呢？", history) == "rag"

    payload = json.loads(captured["messages"][1]["content"])
    assert payload["recent_history"] == [
        {"role": message["role"], "content": message["content"][:1500]}
        for message in history[-8:]
        if message["role"] in ("user", "assistant")
    ]
    assert len(payload["recent_history"][-2]["content"]) == 1500
    assert history == original


@pytest.mark.parametrize(
    "content",
    [
        None,
        "",
        json.dumps({"intent": "tool", "confidence": 0.95}),
        json.dumps({"intent": "rag", "confidence": -0.1}),
        json.dumps({"intent": "rag", "confidence": 1.1}),
        json.dumps({"intent": "rag", "confidence": "invalid"}),
        json.dumps({"intent": "rag"}),
        "[]",
    ],
)
def test_invalid_model_response_falls_back_to_chat(monkeypatch, content):
    mock_client(monkeypatch, content)
    assert intent_router.classify_intent("项目使用什么数据库？") == "chat"


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [(0.65, "rag"), (0.649, "chat")],
)
def test_confidence_threshold_boundary_is_preserved(monkeypatch, confidence, expected):
    mock_client(
        monkeypatch,
        json.dumps({"intent": "rag", "confidence": confidence}),
    )
    assert intent_router.classify_intent("项目使用什么数据库？") == expected
