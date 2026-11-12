
import pytest
import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

import api
import database


client = TestClient(api.app)


@pytest.fixture
def test_db(tmp_path):

    # 1. 创建临时 SQLite 数据库
    test_db_path = tmp_path / "test_chat.db"

    test_engine = create_engine(
        f"sqlite:///{test_db_path}",
        connect_args={"check_same_thread": False}
    )

    # 2. 根据 ORM 模型创建数据表
    database.Base.metadata.create_all(test_engine)

    # 3. 创建测试专用 Session 工厂
    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False
    )

    # 4. 覆盖 FastAPI 的数据库依赖
    def override_get_db():
        db = TestingSessionLocal()

        try:
            yield db
        finally:
            db.close()

    api.app.dependency_overrides[database.get_db] = override_get_db

    # 5. 创建测试 Session
    db = TestingSessionLocal()

    try:
        yield db

    finally:
        db.close()
        api.app.dependency_overrides.clear()
        test_engine.dispose()


def test_history_returns_user_messages(test_db):

    database.save_messages(
        test_db, "test_user", "user", "你好"
    )

    database.save_messages(
        test_db, "test_user", "assistant", "你好！"
    )

    response = client.get("/history/test_user")

    assert response.status_code == 200

    assert response.json() == {
        "messages": [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"}
        ]
    }


def test_clear_messages(test_db):

    database.save_messages(
        test_db, "test_user", "user", "你好"
    )

    response = client.post(
        "/clear",
        json={"user_id": "test_user"}
    )

    assert response.status_code == 200

    assert response.json() == {
        "message": "聊天记录已清空"
    }

    assert database.get_messages(
        test_db, "test_user"
    ) == []


def test_chat_returns_ai_answer(monkeypatch, test_db):

    def fake_ai_chat(
        db,
        user_id,
        question,
        cache_mode="context"
    ):
        return "你好！我是测试生成的回答。"

    monkeypatch.setattr(api, "ai_chat", fake_ai_chat)

    response = client.post(
        "/chat",
        json={
            "user_id": "test_user",
            "question": "你好"
        }
    )

    assert response.status_code == 200

    assert response.json() == {
        "answer": "你好！我是测试生成的回答。"
    }

    # 测试默认上下文模式
def test_chat_uses_default_context_mode(
    monkeypatch, test_db
):
    received = {}

    def fake_ai_chat(
        db,
        user_id,
        question,
        cache_mode="context"
    ):
        received["cache_mode"] = cache_mode
        return "测试回答"

    monkeypatch.setattr(
        api, "ai_chat", fake_ai_chat
    )

    response = client.post(
        "/chat",
        json={
            "user_id": "test_user",
            "question": "你好"
        }
    )

    assert response.status_code == 200
    assert received["cache_mode"] == "context"

    # 测试单独问题模式
def test_chat_uses_question_mode(
    monkeypatch, test_db
):
    received = {}

    def fake_ai_chat(
        db,
        user_id,
        question,
        cache_mode="context"
    ):
        received["cache_mode"] = cache_mode
        return "测试回答"

    monkeypatch.setattr(
        api, "ai_chat", fake_ai_chat
    )

    response = client.post(
        "/chat",
        json={
            "user_id": "test_user",
            "question": "Python 是什么？",
            "cache_mode": "question"
        }
    )

    assert response.status_code == 200
    assert received["cache_mode"] == "question"

    # 测试无效的缓存模式
def test_chat_rejects_invalid_cache_mode(test_db):

    response = client.post(
        "/chat",
        json={
            "user_id": "test_user",
            "question": "你好",
            "cache_mode": "random"
        }
    )

    assert response.status_code == 422

    # 测试空问题
def test_chat_rejects_empty_question(test_db):

    response = client.post(
        "/chat",
        json={
            "user_id": "test_user",
            "question": "   "
        }
    )

    assert response.status_code == 422


def test_chat_rejects_too_long_question(test_db):

    response = client.post(
        "/chat",
        json={
            "user_id": "test_user",
            "question": "a" * 4001
        }
    )

    assert response.status_code == 422


def test_chat_rejects_empty_user_id(test_db):

    response = client.post(
        "/chat",
        json={
            "user_id": "   ",
            "question": "你好"
        }
    )

    assert response.status_code == 422


def test_rag_chat_returns_answer_and_saves_messages(
    monkeypatch, test_db
):

    def fake_answer_question(question):
        return "这是模拟的知识库回答。"

    monkeypatch.setattr(
        api, "answer_question", fake_answer_question
    )

    response = client.post(
        "/rag/chat",
        json={
            "user_id": "rag_test_user",
            "question": "Python 是什么？"
        }
    )

    assert response.status_code == 200

    assert response.json() == {
        "answer": "这是模拟的知识库回答。"
    }

    history_response = client.get(
        "/history/rag_test_user"
    )

    assert history_response.status_code == 200

    assert history_response.json()["messages"] == [
        {
            "role": "user",
            "content": "Python 是什么？"
        },
        {
            "role": "assistant",
            "content": "这是模拟的知识库回答。"
        }
    ]

    # 测试流式聊天模式返回流式文本
def test_chat_stream_returns_streamed_text(monkeypatch):

    received = {}

    def fake_chat_stream(
        user_id,
        question,
        cache_mode="context"
    ):

        received["user_id"] = user_id
        received["question"] = question
        received["cache_mode"] = cache_mode

        yield "你好，"
        yield "这是流式回答。"

    monkeypatch.setattr(
        api,
        "chat_stream",
        fake_chat_stream
    )

    response = client.post(
        "/chat/stream",
        json={
            "user_id": "stream_test_user",
            "question": "你好",
            "cache_mode": "context"
        }
    )

    assert response.status_code == 200

    assert response.text == "你好，这是流式回答。"

    assert received["user_id"] == "stream_test_user"
    assert received["question"] == "你好"
    assert received["cache_mode"] == "context"

    # 测试流式聊天模式中使用单独问题计算缓存key模式
def test_chat_stream_uses_question_mode(monkeypatch):

    received = {}

    def fake_chat_stream(
        user_id,
        question,
        cache_mode="context"
    ):

        received["cache_mode"] = cache_mode

        yield "这是独立问题回答。"

    monkeypatch.setattr(
        api,
        "chat_stream",
        fake_chat_stream
    )

    response = client.post(
        "/chat/stream",
        json={
            "user_id": "stream_test_user",
            "question": "Python 是什么？",
            "cache_mode": "question"
        }
    )

    assert response.status_code == 200

    assert response.text == "这是独立问题回答。"

    assert received["cache_mode"] == "question"

def test_chat_stream_rejects_empty_question():

    response = client.post(
        "/chat/stream",
        json={
            "user_id": "stream_test_user",
            "question": "   "
        }
    )

    assert response.status_code == 422


def test_chat_returns_500_when_ai_chat_fails(
    monkeypatch, caplog, test_db
):

    def fake_ai_chat(
    db,
    user_id,
    question,
    cache_mode="context"
    ):
        raise RuntimeError("模拟模型服务故障")

    monkeypatch.setattr(
        api, "ai_chat", fake_ai_chat
    )

    with caplog.at_level("ERROR", logger="api"):

        response = client.post(
            "/chat",
            json={
                "user_id": "test_user",
                "question": "你好"
            }
        )

    assert response.status_code == 500

    assert response.json() == {
        "detail": "服务器处理请求失败，请稍后重试"
    }

    assert "普通聊天请求处理失败" in caplog.text
    assert "模拟模型服务故障" in caplog.text


def test_rag_chat_returns_500_when_rag_fails(
    monkeypatch, test_db, caplog
):

    def fake_answer_question(question):
        raise RuntimeError("模拟 RAG 检索故障")

    monkeypatch.setattr(
        api, "answer_question", fake_answer_question
    )

    with caplog.at_level("ERROR", logger="api"):

        response = client.post(
            "/rag/chat",
            json={
                "user_id": "rag_error_user",
                "question": "数据库使用什么技术？"
            }
        )

    assert response.status_code == 500

    assert response.json() == {
        "detail": "知识库问答处理失败，请稍后重试"
    }

    assert "RAG 问答请求处理失败" in caplog.text
    assert "模拟 RAG 检索故障" in caplog.text

    assert database.get_messages(
        test_db, "rag_error_user"
    ) == []





def test_chat_stream_api_disconnect_closes_generator(monkeypatch):

    lifecycle = []

    # 1. 模拟流式生成器
    def fake_chat_stream(
        user_id,
        question,
        cache_mode="context"
    ):

        try:
            yield "第一段回答"
            yield "第二段回答"

        finally:
            lifecycle.append("generator_closed")

    # 2. 替换 API 中的聊天生成器
    monkeypatch.setattr(
        api,
        "chat_stream",
        fake_chat_stream
    )

    # 3. 模拟 HTTP 请求
    request_body = (
        '{"user_id":"disconnect_test_user",'
        '"question":"测试断开连接",'
        '"cache_mode":"context"}'
    ).encode("utf-8")

    async def run_disconnect_test():

        first_body_sent = asyncio.Event()
        request_received = False

        # 4. 模拟客户端发送请求和断开连接
        async def receive():

            nonlocal request_received

            if not request_received:

                request_received = True

                return {
                    "type": "http.request",
                    "body": request_body,
                    "more_body": False
                }

            # 等待服务器发送第一段回答
            await first_body_sent.wait()

            # 模拟客户端断开连接
            return {
                "type": "http.disconnect"
            }

        # 5. 模拟服务器发送响应
        async def send(message):

            if (
                message["type"] == "http.response.body"
                and message.get("body")
            ):

                # 第一段回答已经发送
                first_body_sent.set()

                # 等待客户端断开，期间保持发送任务
                await asyncio.Event().wait()

        # 6. 构造 ASGI HTTP 请求环境
        scope = {
            "type": "http",
            "asgi": {
                "version": "3.0",
                "spec_version": "2.3"
            },
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/chat/stream",
            "raw_path": b"/chat/stream",
            "query_string": b"",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json")
            ],
            "server": ("testserver", 80),
            "client": ("testclient", 123),
            "root_path": ""
        }

        # 7. 真正运行 FastAPI 应用
        await asyncio.wait_for(
            api.app(scope, receive, send),
            timeout=5
        )

        await asyncio.sleep(0)

    # 8. 执行异步测试
    asyncio.run(run_disconnect_test())

    # 9. 验证生成器是否执行了 finally
    assert lifecycle == ["generator_closed"]




    #正常上传文档时
def test_document_upload_success(
    monkeypatch,
    test_db
):

    received = {}

    # 模拟文档业务函数
    def fake_upload_document(
        db,
        filename,
        content,
        bloom
    ):

        received["db"] = db
        received["filename"] = filename
        received["content"] = content
        received["bloom"] = bloom

        class FakeDocument:

            def __init__(self):
                self.id = 123
                self.filename = filename

        return {
            "created": True,
            "reason": None,
            "document": FakeDocument()
        }

    monkeypatch.setattr(
        api,
        "upload_document",
        fake_upload_document
    )

    # 测试中不连接真实 Redis
    api.app.dependency_overrides[
        api.get_document_bloom
    ] = lambda: object()

    response = client.post(
        "/documents/upload",
        files={
            "file": (
                "demo_policy.txt",
                "退换货政策：商品签收后七天内可以申请退货。",
                "text/plain"
            )
        }
    )

    assert response.status_code == 200

    data = response.json()

    assert data["created"] is True

    assert data["document"]["id"] == 123

    assert received["filename"] == "demo_policy.txt"

    assert received["content"] == (
        "退换货政策：商品签收后七天内可以申请退货。"
    )

    assert received["db"] is not None

    assert received["bloom"] is not None


    #上传文件时 拒绝非 TXT 文件
def test_document_upload_rejects_non_txt(
    monkeypatch,
    test_db
):

    api.app.dependency_overrides[
        api.get_document_bloom
    ] = lambda: object()

    # 不应该调用文档业务函数
    monkeypatch.setattr(
        api,
        "upload_document",
        lambda *args, **kwargs: pytest.fail(
            "不支持的文件不应该进入文档业务层"
        )
    )

    response = client.post(
        "/documents/upload",
        files={
            "file": (
                "policy.pdf",
                b"test content",
                "application/pdf"
            )
        }
    )

    assert response.status_code == 400

    assert response.json()["detail"] == (
        "目前仅支持 .txt 文件"
    )