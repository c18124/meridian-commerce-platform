import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database


@pytest.fixture
def db_session(tmp_path):
    # 1. 创建临时 SQLite 数据库
    test_db_path = tmp_path / "test_chat.db"

    test_engine = create_engine(
        f"sqlite:///{test_db_path}",
        connect_args={"check_same_thread": False}
    )

    # 2. 根据 ORM 模型创建数据表
    database.Base.metadata.create_all(test_engine)

    # 3. 创建专门用于测试的 Session 工厂
    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False
    )

    # 4. 创建数据库会话
    db = TestingSessionLocal()

    try:
        yield db
    finally:
        # 5. 测试结束，关闭会话和数据库连接
        db.close()
        test_engine.dispose()


def test_save_and_get_messages(db_session):
    database.save_messages(
        db_session, "test_user", "user", "你好"
    )

    messages = database.get_messages(
        db_session, "test_user"
    )

    assert messages == [
        {"role": "user", "content": "你好"}
    ]


def test_clear_messages(db_session):
    database.save_messages(
        db_session, "test_user", "user", "你好"
    )

    database.save_messages(
        db_session, "test_user", "assistant", "你好！"
    )

    database.clear_messages(db_session, "test_user")

    messages = database.get_messages(
        db_session, "test_user"
    )

    assert messages == []


def test_user_messages_are_isolated(db_session):
    database.save_messages(
        db_session, "user_001", "user", "我是用户001"
    )

    database.save_messages(
        db_session, "user_002", "user", "我是用户002"
    )

    messages_001 = database.get_messages(
        db_session, "user_001"
    )

    messages_002 = database.get_messages(
        db_session, "user_002"
    )

    assert messages_001 == [
        {"role": "user", "content": "我是用户001"}
    ]

    assert messages_002 == [
        {"role": "user", "content": "我是用户002"}
    ]


def test_clear_messages_does_not_affect_other_users(db_session):
    database.save_messages(
        db_session, "user_001", "user", "用户001的消息"
    )

    database.save_messages(
        db_session, "user_002", "user", "用户002的消息"
    )

    database.clear_messages(db_session, "user_001")

    assert database.get_messages(
        db_session, "user_001"
    ) == []

    assert database.get_messages(
        db_session, "user_002"
    ) == [
        {"role": "user", "content": "用户002的消息"}
    ]


def test_save_conversation(db_session):
    database.save_conversation(
        db_session,
        "test_user",
        "你好",
        "你好！有什么可以帮你的？"
    )

    messages = database.get_messages(
        db_session, "test_user"
    )

    assert messages == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！有什么可以帮你的？"}
    ]