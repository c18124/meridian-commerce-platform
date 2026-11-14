    #负责在意图识别之后 实现真正的实现   负责真正调度接口和工具
import logging

from collections.abc import Callable, Iterator
from agent_tool_service import agent_tool_chat_stream
from database import SessionLocal, get_messages
from intent_router import classify_intent


logger = logging.getLogger(__name__)


# RAG 流式生成器的类型
RagStreamFactory = Callable[
    [str, str],
    Iterator[str]
]


def agent_chat_stream(
    user_id: str,
    question: str,
    cache_mode: str = "context",
    rag_stream_factory: RagStreamFactory = None
):

    # 1. 创建数据库会话
    db = SessionLocal()

    try:

        # 2. 获取当前用户历史消息
        history = get_messages(
            db,
            user_id
        )

    finally:

        # 3. 关闭数据库会话
        db.close()

    # 4. 调用意图识别模块
    intent = classify_intent(
        question,
        history[-8:]
    )

    # 5. 防止返回非法意图
    if intent not in ("chat", "rag"):
        intent = "chat"

    logger.info(
        "Agent 开始调度:user=%s intent=%s",
        user_id,
        intent
    )

    # 6. 根据意图选择 RAG
    if intent == "rag":

        logger.info("Agent 选择 RAG 知识库问答")

        if rag_stream_factory is None:
            raise RuntimeError(
                "RAG 流式生成器尚未配置"
            )

        # 直接复用现有 RAG 流式生成器
        yield from rag_stream_factory(
            user_id,
            question
        )

        return

    
    # 7. 普通聊天分支：进入 Function Calling Agent
    logger.info("Agent 选择 Function Calling 聊天")

    yield from agent_tool_chat_stream(
        user_id,
        question,
        cache_mode=cache_mode
    )

    return


