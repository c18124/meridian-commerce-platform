    #自动化测试Function Calling 同一轮多个工具调用
from types import SimpleNamespace

import agent_tool_service


# 模拟数据库会话
class FakeDB:

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


# 模拟 DeepSeek 流式响应
class FakeResponse:

    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        return iter(self.chunks)

    def close(self):
        self.closed = True


# 模拟模型返回的一个数据块
def make_chunk(content=None, tool_calls=None):

    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=content,
                    tool_calls=tool_calls or []
                )
            )
        ]
    )


# 模拟一个工具调用片段
def make_tool_delta(
    index,
    call_id,
    name,
    arguments
):

    return SimpleNamespace(
        index=index,
        id=call_id,
        type="function",
        function=SimpleNamespace(
            name=name,
            arguments=arguments
        )
    )


# 模拟 DeepSeek 客户端
class FakeCompletions:

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):

        self.calls.append(kwargs)

        return next(self.responses)


# 测试同一轮多个工具调用
def test_agent_executes_multiple_tool_calls(monkeypatch):

    # 1. 准备模拟数据库
    db = FakeDB()

    monkeypatch.setattr(
        agent_tool_service,
        "SessionLocal",
        lambda: db
    )

    # 2. 模拟历史消息
    monkeypatch.setattr(
        agent_tool_service,
        "build_messages",
        lambda db, user_id, question: [
            {
                "role": "user",
                "content": question
            }
        ]
    )

    # 3. 记录保存的消息
    saved_messages = []

    monkeypatch.setattr(
        agent_tool_service,
        "save_messages",
        lambda db, user_id, role, content:
            saved_messages.append(
                (user_id, role, content)
            )
    )

    # 4. 模拟工具执行
    executed_tools = []

    def fake_execute_tool(tool_name, arguments):

        executed_tools.append(
            (tool_name, arguments)
        )

        return {
            "success": True,
            "tool": tool_name
        }

    monkeypatch.setattr(
        agent_tool_service,
        "execute_tool",
        fake_execute_tool
    )

    # 5. 模拟 DeepSeek 同时返回两个工具调用
    first_response = FakeResponse([

        make_chunk(
            tool_calls=[

                make_tool_delta(
                    0,
                    "call_inventory",
                    "get_sku_inventory",
                    '{"sku_code":"DEMO-SKU001"}'
                ),

                make_tool_delta(
                    1,
                    "call_detail",
                    "get_product_detail",
                    '{"product_id":1}'
                )

            ]
        )

    ])

    # 6. 模拟工具执行后的最终回答
    final_response = FakeResponse([

        make_chunk(
            content="商品详情和库存查询完成。"
        )

    ])

    # 7. 组装模拟客户端
    completions = FakeCompletions([
        first_response,
        final_response
    ])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=completions
        )
    )

    monkeypatch.setattr(
        agent_tool_service,
        "client",
        fake_client
    )

    # 8. 执行 Agent
    result = "".join(
        agent_tool_service.agent_tool_chat_stream(
            "test-user",
            "查询商品详情和 SKU 库存"
        )
    )

    # 9. 验证最终答案
    assert result == "商品详情和库存查询完成。"

    # 10. 验证两个工具都被执行
    assert len(executed_tools) == 2

    assert executed_tools[0][0] == "get_sku_inventory"

    assert executed_tools[1][0] == "get_product_detail"

    # 11. 验证模型被调用两次
    assert len(completions.calls) == 2

    # 12. 验证第二次请求包含两个工具结果
    second_messages = completions.calls[1]["messages"]

    tool_messages = [
        message
        for message in second_messages
        if message["role"] == "tool"
    ]

    assert len(tool_messages) == 2

    assert [
        message["tool_call_id"]
        for message in tool_messages
    ] == [
        "call_inventory",
        "call_detail"
    ]

    # 13. 验证响应正确关闭
    assert first_response.closed is True
    assert final_response.closed is True

    # 14. 验证最终回答被保存
    assert saved_messages[-1] == (
        "test-user",
        "assistant",
        "商品详情和库存查询完成。"
    )

    # 15. 验证数据库会话关闭
    assert db.closed is True





    #测试连续多轮工具调用
def test_agent_executes_tools_across_multiple_rounds(monkeypatch):

    # 1. 模拟数据库
    db = FakeDB()

    monkeypatch.setattr(
        agent_tool_service,
        "SessionLocal",
        lambda: db
    )

    # 2. 模拟历史消息
    monkeypatch.setattr(
        agent_tool_service,
        "build_messages",
        lambda db, user_id, question: [
            {
                "role": "user",
                "content": question
            }
        ]
    )

    # 3. 记录数据库保存操作
    saved_messages = []

    monkeypatch.setattr(
        agent_tool_service,
        "save_messages",
        lambda db, user_id, role, content:
            saved_messages.append(
                (role, content)
            )
    )

    # 4. 模拟工具执行
    executed_tools = []

    def fake_execute_tool(tool_name, arguments):

        executed_tools.append(tool_name)

        if tool_name == "get_product_detail":
            return {
                "found": True,
                "product": {
                    "id": 1,
                    "name": "夏季纯棉短袖",
                    "skus": [
                        {
                            "sku_code": "DEMO-SKU001"
                        }
                    ]
                }
            }

        if tool_name == "get_sku_inventory":
            return {
                "found": True,
                "sku_code": "DEMO-SKU001",
                "stock": 120
            }

    monkeypatch.setattr(
        agent_tool_service,
        "execute_tool",
        fake_execute_tool
    )

    # 5. 第一轮：模型请求查询商品详情
    first_response = FakeResponse([

        make_chunk(
            tool_calls=[
                make_tool_delta(
                    0,
                    "call_detail",
                    "get_product_detail",
                    '{"product_id":1}'
                )
            ]
        )

    ])

    # 6. 第二轮：模型根据商品详情请求查询库存
    second_response = FakeResponse([

        make_chunk(
            tool_calls=[
                make_tool_delta(
                    0,
                    "call_inventory",
                    "get_sku_inventory",
                    '{"sku_code":"DEMO-SKU001"}'
                )
            ]
        )

    ])

    # 7. 第三轮：模型生成最终回答
    final_response = FakeResponse([

        make_chunk(
            content="夏季纯棉短袖的第一个 SKU "
                    "DEMO-SKU001 当前库存为 120 件。"
        )

    ])

    # 8. 模拟三次模型请求
    completions = FakeCompletions([
        first_response,
        second_response,
        final_response
    ])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=completions
        )
    )

    monkeypatch.setattr(
        agent_tool_service,
        "client",
        fake_client
    )

    # 9. 执行 Agent
    result = "".join(
        agent_tool_service.agent_tool_chat_stream(
            "test-user",
            "查询商品详情，然后查询第一个 SKU 的库存"
        )
    )

    # 10. 验证最终回答
    assert "120 件" in result

    # 11. 验证工具执行顺序
    assert executed_tools == [
        "get_product_detail",
        "get_sku_inventory"
    ]

    # 12. 验证模型调用了三轮
    assert len(completions.calls) == 3

    # 13. 验证第三轮请求包含前两轮工具结果
    third_messages = completions.calls[2]["messages"]

    tool_messages = [
        message
        for message in third_messages
        if message["role"] == "tool"
    ]

    assert len(tool_messages) == 2

    assert [
        message["tool_call_id"]
        for message in tool_messages
    ] == [
        "call_detail",
        "call_inventory"
    ]

    # 14. 验证最终回答被保存
    assert saved_messages[-1] == (
        "assistant",
        result
    )

    # 15. 验证响应关闭
    assert first_response.closed
    assert second_response.closed
    assert final_response.closed

    # 16. 验证数据库关闭
    assert db.closed





    #测试工具执行失败时，Agent 能不能恢复

def test_agent_recovers_from_tool_value_error(monkeypatch):

    # 1. 模拟数据库
    db = FakeDB()

    monkeypatch.setattr(
        agent_tool_service,
        "SessionLocal",
        lambda: db
    )

    # 2. 模拟历史消息
    monkeypatch.setattr(
        agent_tool_service,
        "build_messages",
        lambda db, user_id, question: [
            {
                "role": "user",
                "content": question
            }
        ]
    )

    # 3. 记录消息保存
    saved_messages = []

    monkeypatch.setattr(
        agent_tool_service,
        "save_messages",
        lambda db, user_id, role, content:
            saved_messages.append((role, content))
    )

    # 4. 模拟工具执行失败
    def fake_execute_tool(tool_name, arguments):

        raise ValueError("未找到该 SKU")

    monkeypatch.setattr(
        agent_tool_service,
        "execute_tool",
        fake_execute_tool
    )

    # 5. 第一轮：模型请求查询库存
    first_response = FakeResponse([

        make_chunk(
            tool_calls=[
                make_tool_delta(
                    0,
                    "call_inventory_error",
                    "get_sku_inventory",
                    '{"sku_code":"DEMO-SKU999"}'
                )
            ]
        )

    ])

    # 6. 第二轮：模型根据错误信息生成回答
    final_response = FakeResponse([

        make_chunk(
            content="没有找到 SKU DEMO-SKU999，"
                    "请检查商品编号是否正确。"
        )

    ])

    # 7. 模拟 DeepSeek 客户端
    completions = FakeCompletions([
        first_response,
        final_response
    ])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=completions
        )
    )

    monkeypatch.setattr(
        agent_tool_service,
        "client",
        fake_client
    )

    # 8. 执行 Agent
    result = "".join(
        agent_tool_service.agent_tool_chat_stream(
            "test-user",
            "查询 DEMO-SKU999 的库存"
        )
    )

    # 9. 验证最终回答
    assert "没有找到" in result

    # 10. 检查第二轮发送给模型的工具结果
    second_messages = completions.calls[1]["messages"]

    tool_messages = [
        message
        for message in second_messages
        if message["role"] == "tool"
    ]

    assert len(tool_messages) == 1

    assert tool_messages[0]["tool_call_id"] == (
        "call_inventory_error"
    )

    import json

    tool_result = json.loads(
        tool_messages[0]["content"]
    )

    assert tool_result == {
        "error": "未找到该 SKU"
    }

    # 11. 验证模型执行了两次请求
    assert len(completions.calls) == 2

    # 12. 验证最终答案正常保存
    assert saved_messages[-1] == (
        "assistant",
        result
    )

    # 13. 验证资源正常关闭
    assert first_response.closed
    assert final_response.closed
    assert db.closed



    #测试无限循环保护

def test_agent_stops_after_max_tool_rounds(monkeypatch):

    # 1. 模拟数据库
    db = FakeDB()

    monkeypatch.setattr(
        agent_tool_service,
        "SessionLocal",
        lambda: db
    )

    monkeypatch.setattr(
        agent_tool_service,
        "build_messages",
        lambda db, user_id, question: [
            {
                "role": "user",
                "content": question
            }
        ]
    )

    # 2. 记录最终保存的消息
    saved_messages = []

    monkeypatch.setattr(
        agent_tool_service,
        "save_messages",
        lambda db, user_id, role, content:
            saved_messages.append((role, content))
    )

    # 3. 记录工具执行次数
    executed_tools = []

    def fake_execute_tool(tool_name, arguments):

        executed_tools.append(tool_name)

        return {
            "success": True
        }

    monkeypatch.setattr(
        agent_tool_service,
        "execute_tool",
        fake_execute_tool
    )

    # 4. 模拟模型不断要求调用工具
    responses = []

    for index in range(
        agent_tool_service.MAX_TOOL_ROUNDS + 1
    ):

        response = FakeResponse([

            make_chunk(
                tool_calls=[
                    make_tool_delta(
                        0,
                        f"call_{index}",
                        "get_sku_inventory",
                        '{"sku_code":"DEMO-SKU001"}'
                    )
                ]
            )

        ])

        responses.append(response)

    # 5. 模拟 DeepSeek
    completions = FakeCompletions(responses)

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=completions
        )
    )

    monkeypatch.setattr(
        agent_tool_service,
        "client",
        fake_client
    )

    # 6. 执行 Agent
    result = "".join(
        agent_tool_service.agent_tool_chat_stream(
            "test-user",
            "不断查询 DEMO-SKU001 的库存"
        )
    )

    # 7. 验证 Agent 主动停止
    assert "达到工具调用轮数上限" in result

    # 8. 实际执行次数不能超过最大轮数
    assert len(executed_tools) == (
        agent_tool_service.MAX_TOOL_ROUNDS
    )

    # 9. 模型最后一次请求触发了循环保护
    assert len(completions.calls) == (
        agent_tool_service.MAX_TOOL_ROUNDS + 1
    )

    # 10. 所有响应均已关闭
    assert all(
        response.closed
        for response in responses
    )

    # 11. 最终回答已保存
    assert saved_messages[-1] == (
        "assistant",
        result
    )

    # 12. 数据库已关闭
    assert db.closed is True





    #测试单次请求最多执行 10 次工具
def test_agent_limits_total_tool_calls(monkeypatch):

    # 1. 模拟数据库
    db = FakeDB()

    monkeypatch.setattr(
        agent_tool_service,
        "SessionLocal",
        lambda: db
    )

    monkeypatch.setattr(
        agent_tool_service,
        "build_messages",
        lambda db, user_id, question: [
            {
                "role": "user",
                "content": question
            }
        ]
    )

    # 2. 记录数据库保存
    saved_messages = []

    monkeypatch.setattr(
        agent_tool_service,
        "save_messages",
        lambda db, user_id, role, content:
            saved_messages.append((role, content))
    )

    # 3. 记录实际执行的工具数量
    executed_tools = []

    def fake_execute_tool(tool_name, arguments):

        executed_tools.append(tool_name)

        return {
            "success": True,
            "sku_code": arguments["sku_code"]
        }

    monkeypatch.setattr(
        agent_tool_service,
        "execute_tool",
        fake_execute_tool
    )

    # 4. 模拟模型一次性请求 11 个工具
    tool_deltas = []

    for index in range(
        agent_tool_service.MAX_TOOL_CALLS + 1
    ):

        tool_deltas.append(
            make_tool_delta(
                index,
                f"call_{index}",
                "get_sku_inventory",
                f'{{"sku_code":"SKU-{index}"}}'
            )
        )

    # 5. 第一轮：模型提出 11 个工具调用
    first_response = FakeResponse([

        make_chunk(
            tool_calls=tool_deltas
        )

    ])

    # 6. 第二轮：模型生成最终回答
    final_response = FakeResponse([

        make_chunk(
            content="已完成允许范围内的库存查询。"
        )

    ])

    # 7. 模拟 DeepSeek
    completions = FakeCompletions([
        first_response,
        final_response
    ])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=completions
        )
    )

    monkeypatch.setattr(
        agent_tool_service,
        "client",
        fake_client
    )

    # 8. 执行 Agent
    result = "".join(
        agent_tool_service.agent_tool_chat_stream(
            "test-user",
            "查询多个 SKU 的库存"
        )
    )

    # 9. 验证实际执行数量没有超过 10
    assert len(executed_tools) == (
        agent_tool_service.MAX_TOOL_CALLS
    )

    # 10. 验证模型收到 11 个工具结果
    second_messages = completions.calls[1]["messages"]

    tool_messages = [
        message
        for message in second_messages
        if message["role"] == "tool"
    ]

    assert len(tool_messages) == (
        agent_tool_service.MAX_TOOL_CALLS + 1
    )

    # 11. 验证第 11 个工具被拦截
    import json

    last_result = json.loads(
        tool_messages[-1]["content"]
    )

    assert last_result == {
        "error": "工具调用次数已达到上限"
    }

    # 12. 验证模型调用次数
    assert len(completions.calls) == 2

    # 13. 验证最终答案
    assert result == "已完成允许范围内的库存查询。"

    # 14. 验证响应关闭
    assert first_response.closed
    assert final_response.closed

    # 15. 验证最终答案保存
    assert saved_messages[-1] == (
        "assistant",
        result
    )

    # 16. 验证数据库关闭
    assert db.closed is True





    #测试摸你DeepSeek API 请求直接失败

def test_agent_does_not_save_answer_when_api_request_fails(monkeypatch):

    import pytest

    # 1. 模拟数据库
    db = FakeDB()

    monkeypatch.setattr(
        agent_tool_service,
        "SessionLocal",
        lambda: db
    )

    # 2. 模拟历史消息
    monkeypatch.setattr(
        agent_tool_service,
        "build_messages",
        lambda db, user_id, question: [
            {
                "role": "user",
                "content": question
            }
        ]
    )

    # 3. 记录数据库保存操作
    saved_messages = []

    monkeypatch.setattr(
        agent_tool_service,
        "save_messages",
        lambda db, user_id, role, content:
            saved_messages.append(
                (user_id, role, content)
            )
    )

    # 4. 模拟 DeepSeek API 请求失败
    class FailingCompletions:

        def create(self, **kwargs):

            raise RuntimeError(
                "模拟 DeepSeek API 请求失败"
            )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=FailingCompletions()
        )
    )

    monkeypatch.setattr(
        agent_tool_service,
        "client",
        fake_client
    )

    # 5. 执行 Agent，验证异常能够向上抛出
    with pytest.raises(
        RuntimeError,
        match="模拟 DeepSeek API 请求失败"
    ):

        list(
            agent_tool_service.agent_tool_chat_stream(
                "test-user",
                "查询商城商品"
            )
        )

    # 6. 用户问题可以保存
    assert any(
        role == "user"
        for _, role, _ in saved_messages
    )

    # 7. 不能保存 AI 的不完整回答
    assert not any(
        role == "assistant"
        for _, role, _ in saved_messages
    )

    # 8. 数据库必须关闭
    assert db.closed is True




    #测试摸你模型生成到一半突然断开

def test_agent_does_not_save_partial_answer_when_stream_interrupted(
    monkeypatch
):

    import pytest

    # 1. 模拟数据库
    db = FakeDB()

    monkeypatch.setattr(
        agent_tool_service,
        "SessionLocal",
        lambda: db
    )

    monkeypatch.setattr(
        agent_tool_service,
        "build_messages",
        lambda db, user_id, question: [
            {
                "role": "user",
                "content": question
            }
        ]
    )

    # 2. 记录数据库保存
    saved_messages = []

    monkeypatch.setattr(
        agent_tool_service,
        "save_messages",
        lambda db, user_id, role, content:
            saved_messages.append(
                (user_id, role, content)
            )
    )

    # 3. 模拟流式连接中断
    class InterruptedResponse:

        def __init__(self):
            self.closed = False

        def __iter__(self):

            # 先正常返回一段文字
            yield make_chunk(
                content="这是一段尚未完成的回答"
            )

            # 随后模拟连接中断
            raise RuntimeError(
                "模拟 DeepSeek 流式连接中断"
            )

        def close(self):
            self.closed = True

    response = InterruptedResponse()

    # 4. 模拟 DeepSeek 客户端
    completions = FakeCompletions([
        response
    ])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=completions
        )
    )

    monkeypatch.setattr(
        agent_tool_service,
        "client",
        fake_client
    )

    # 5. 接收已经生成的部分内容
    partial_chunks = []

    with pytest.raises(
        RuntimeError,
        match="模拟 DeepSeek 流式连接中断"
    ):

        for chunk in (
            agent_tool_service.agent_tool_chat_stream(
                "test-user",
                "请介绍商城商品"
            )
        ):

            partial_chunks.append(chunk)

    # 6. 确认确实收到过部分内容
    assert partial_chunks == [
        "这是一段尚未完成的回答"
    ]

    # 7. 不允许保存不完整的 AI 回答
    assert not any(
        role == "assistant"
        for _, role, _ in saved_messages
    )

    # 8. 模型响应必须关闭
    assert response.closed is True

    # 9. 数据库必须关闭
    assert db.closed is True



