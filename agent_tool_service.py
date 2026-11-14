    #向大模型发送三个工具的信息 接收并解析模型返回的 tool_calls 调用 execute_tool() 执行 Python 函数 把执行结果交还模型
import json
import logging

from collections.abc import Iterator

from ai import client, build_messages
from config import MODEL
from database import SessionLocal, save_messages

from agent_tools import (
    AGENT_TOOLS,
    execute_tool
)


logger = logging.getLogger(__name__)


# 工具调用的最大轮数
MAX_TOOL_ROUNDS = 5

# 单次用户请求最多执行多少次工具
MAX_TOOL_CALLS = 10


# Agent 的系统提示词
SYSTEM_PROMPT = """
你是一个跨境电商智能导购助手。

你可以回答普通知识问题，也可以查询商城商品数据。

规则：

1. 用户询问商品列表时，使用 list_products。
2. 用户询问具体商品详情时，使用 get_product_detail。
3. 用户询问 SKU 库存时，使用 get_sku_inventory。
4. 涉及实时商品和库存数据时，必须调用工具，
   不允许猜测或使用历史聊天中的旧数据。
5. 如果工具返回没有找到数据，应如实告知用户。
6. Python 等普通知识问题可以直接回答，不需要调用工具。
7. 不允许编造商品信息或库存数量。
"""


def _close_response(response):

    close_method = getattr(
        response,
        "close",
        None
    )

    if callable(close_method):

        try:
            close_method()

        except Exception:
            logger.exception(
                "DeepSeek 流式连接关闭失败"
            )


def agent_tool_chat_stream(
    user_id: str,
    question: str,
    cache_mode: str = "context"
) -> Iterator[str]:

    # 当前版本不使用普通聊天答案缓存，
    # 避免库存查询返回过期数据。

    db = SessionLocal()

    answer = ""
    completed = False

    total_tool_calls = 0

    try:

        # 1. 构建历史消息
        messages = build_messages(
            db,
            user_id,
            question
        )

        # 2. 添加 Agent 系统提示词
        messages.insert(
            0,
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            }
        )

        # 3. 保存当前用户问题
        save_messages(
            db,
            user_id,
            "user",
            question
        )

        # 4. 开始 Agent 工具调用循环
        for round_index in range(
            MAX_TOOL_ROUNDS + 1
        ):

            logger.info(
                "Agent Function Calling，第 %s 轮",
                round_index + 1
            )

            # 5. 向 DeepSeek 发送请求
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=AGENT_TOOLS,
                tool_choice="auto",
                stream=True
            )

            # 保存当前轮的文本
            round_content = []

            # 保存流式返回的工具调用片段
            tool_call_parts = {}

            try:

                # 6. 接收模型流式响应
                for chunk in response:

                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta

                    # 6.1 获取普通文本
                    content = delta.content

                    if content:

                        round_content.append(content)

                        answer += content

                        yield content

                    # 6.2 获取工具调用片段
                    for tool_delta in (
                        delta.tool_calls or []
                    ):

                        index = tool_delta.index

                        if index is None:
                            index = 0

                        part = tool_call_parts.setdefault(
                            index,
                            {
                                "id": None,
                                "type": "function",
                                "function": {
                                    "name": "",
                                    "arguments": ""
                                }
                            }
                        )

                        # 获取工具调用 ID
                        if tool_delta.id:
                            part["id"] = tool_delta.id

                        # 获取工具类型
                        if tool_delta.type:
                            part["type"] = tool_delta.type

                        function_delta = tool_delta.function

                        if function_delta:

                            # 工具名称
                            if function_delta.name:
                                part["function"]["name"] += (
                                    function_delta.name
                                )

                            # JSON 参数片段
                            if function_delta.arguments:
                                part["function"]["arguments"] += (
                                    function_delta.arguments
                                )

            finally:

                # 7. 关闭当前模型响应
                _close_response(response)

            # 8. 按照 index 整理工具调用
            tool_calls = [
                tool_call_parts[index]
                for index in sorted(tool_call_parts)
            ]

            # 9. 如果没有工具调用，说明模型已经生成最终答案
            if not tool_calls:

                completed = True

                break

            # 10. 检查最大工具调用轮数
            if round_index >= MAX_TOOL_ROUNDS:

                limit_message = (
                    "本次请求已达到工具调用轮数上限，"
                    "请简化问题后重试。"
                )

                answer += limit_message

                yield limit_message

                completed = True

                break

            # 11. 检查工具调用 ID
            for call in tool_calls:

                if not call["id"]:

                    raise RuntimeError(
                        "模型返回的工具调用缺少 ID"
                    )

            # 12. 保存模型发出的 assistant 工具调用消息
            messages.append({

                "role": "assistant",

                "content": "".join(round_content) or None,

                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": call["type"],
                        "function": {
                            "name": call["function"]["name"],
                            "arguments": (
                                call["function"]["arguments"] or "{}"
                            )
                        }
                    }
                    for call in tool_calls
                ]

            })

            # 13. 逐个执行本轮工具
            for call in tool_calls:

                tool_name = call["function"]["name"]

                raw_arguments = (
                    call["function"]["arguments"]
                )

                total_tool_calls += 1

                logger.info(
                    "Agent 执行工具：%s",
                    tool_name
                )

                # 14. 检查工具调用总次数
                if total_tool_calls > MAX_TOOL_CALLS:

                    result = {
                        "error": "工具调用次数已达到上限"
                    }

                else:

                    try:

                        # 15. 解析 JSON 参数
                        arguments = json.loads(
                            raw_arguments or "{}"
                        )

                        # 16. 通过白名单执行工具
                        result = execute_tool(
                            tool_name,
                            arguments
                        )

                    except (json.JSONDecodeError, TypeError):

                        result = {
                            "error": "工具参数不是合法的 JSON 对象"
                        }

                    except ValueError as exc:

                        result = {
                            "error": str(exc)
                        }

                    except Exception:

                        logger.exception(
                            "Agent 工具执行异常：%s",
                            tool_name
                        )

                        result = {
                            "error": "工具执行失败，请稍后重试"
                        }

                # 17. 将工具结果返回消息列表
                messages.append({

                    "role": "tool",

                    "tool_call_id": call["id"],

                    "content": json.dumps(
                        result,
                        ensure_ascii=False,
                        default=str
                    )

                })

                logger.info(
                    "Agent 工具执行完成：%s",
                    tool_name
                )

        # 18. 保存最终助手回答
        if completed and answer:

            save_messages(
                db,
                user_id,
                "assistant",
                answer
            )

    finally:

        # 19. 无论成功还是异常，都关闭数据库会话
        db.close()
