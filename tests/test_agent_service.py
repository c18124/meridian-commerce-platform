    #测试 Agent 能否正确的调度业务模块
import pytest

import agent_service


class FakeDB:

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_agent_dispatches_to_chat(monkeypatch):

    db = FakeDB()

    monkeypatch.setattr(
        agent_service,
        "SessionLocal",
        lambda: db
    )

    monkeypatch.setattr(
        agent_service,
        "get_messages",
        lambda db, user_id: []
    )

    monkeypatch.setattr(
        agent_service,
        "classify_intent",
        lambda question, history: "chat"
    )

    calls = {}

    def fake_chat_stream(user_id, question, cache_mode):

        calls["user_id"] = user_id
        calls["question"] = question
        calls["cache_mode"] = cache_mode

        yield "普通"
        yield "聊天"

    monkeypatch.setattr(
        agent_service,
        "agent_tool_chat_stream",
        fake_chat_stream
    )

    def fake_rag(user_id, question):
        raise AssertionError("不应该进入 RAG")

    result = list(
        agent_service.agent_chat_stream(
            "test_user",
            "你好",
            "context",
            fake_rag
        )
    )

    assert result == ["普通", "聊天"]

    assert calls["question"] == "你好"

    assert calls["cache_mode"] == "context"

    assert db.closed is True


def test_agent_dispatches_to_rag(monkeypatch):

    db = FakeDB()

    monkeypatch.setattr(
        agent_service,
        "SessionLocal",
        lambda: db
    )

    history = [
        {
            "role": "user",
            "content": str(i)
        }
        for i in range(10)
    ]

    monkeypatch.setattr(
        agent_service,
        "get_messages",
        lambda db, user_id: history
    )

    captured = {}

    def fake_classifier(question, recent_history):

        captured["history"] = recent_history

        return "rag"

    monkeypatch.setattr(
        agent_service,
        "classify_intent",
        fake_classifier
    )

    def fake_chat_stream(*args, **kwargs):
        raise AssertionError("不应该进入普通聊天")

    monkeypatch.setattr(
        agent_service,
        "agent_tool_chat_stream",
        fake_chat_stream
    )

    def fake_rag(user_id, question):

        assert db.closed is True

        yield "RAG"
        yield "回答"

    result = list(
        agent_service.agent_chat_stream(
            "test_user",
            "那退款需要多久？",
            "context",
            fake_rag
        )
    )

    assert result == ["RAG", "回答"]

    assert len(captured["history"]) == 8

    assert captured["history"][0]["content"] == "2"


def test_invalid_intent_falls_back_to_chat(monkeypatch):

    db = FakeDB()

    monkeypatch.setattr(
        agent_service,
        "SessionLocal",
        lambda: db
    )

    monkeypatch.setattr(
        agent_service,
        "get_messages",
        lambda db, user_id: []
    )

    monkeypatch.setattr(
        agent_service,
        "classify_intent",
        lambda question, history: "unknown"
    )

    monkeypatch.setattr(
        agent_service,
        "agent_tool_chat_stream",
        lambda *args, **kwargs: iter(["fallback"])
    )

    result = list(
        agent_service.agent_chat_stream(
            "test_user",
            "你好",
            "context",
            lambda *args: iter(["RAG"])
        )
    )

    assert result == ["fallback"]


def test_database_session_closes_on_history_error(monkeypatch):

    db = FakeDB()

    monkeypatch.setattr(
        agent_service,
        "SessionLocal",
        lambda: db
    )

    def raise_error(db, user_id):
        raise RuntimeError("数据库读取失败")

    monkeypatch.setattr(
        agent_service,
        "get_messages",
        raise_error
    )

    with pytest.raises(RuntimeError):

        list(
            agent_service.agent_chat_stream(
                "test_user",
                "你好",
                "context",
                lambda *args: iter([])
            )
        )

    assert db.closed is True