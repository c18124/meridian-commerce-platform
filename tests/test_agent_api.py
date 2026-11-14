    #测试fastapi 中的统一暴露接口
from fastapi.testclient import TestClient

import api


def test_agent_stream_api(monkeypatch):

    captured = {}

    def fake_agent_stream(
        user_id,
        question,
        cache_mode,
        rag_stream_factory
    ):

        captured["user_id"] = user_id
        captured["question"] = question
        captured["cache_mode"] = cache_mode

        captured["rag_stream_factory"] = rag_stream_factory

        yield "Agent "
        yield "回答"

    monkeypatch.setattr(
        api,
        "dispatch_agent_stream",
        fake_agent_stream
    )

    client = TestClient(api.app)

    response = client.post(
        "/agent/chat/stream",
        json={
            "user_id": "test_user",
            "question": "你好",
            "cache_mode": "context"
        }
    )

    assert response.status_code == 200

    assert response.text == "Agent 回答"

    assert captured["user_id"] == "test_user"

    assert captured["question"] == "你好"

    assert captured["cache_mode"] == "context"

    assert (
        captured["rag_stream_factory"]
        is api.rag_chat_stream_generator
    )

    assert response.headers["content-type"].startswith(
        "text/plain"
    )