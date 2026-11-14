# MERIDIAN 系统架构

**MERIDIAN — Commerce Intelligence Platform** 是平台产品名称；GLOBAL STORE 是演示店铺。本文依据当前源码描述实际调用关系，不代表未来规划。

[返回项目主页](../README.md) · [Docker 部署](deployment.md)

## 图一：系统整体架构

图中实线表示主要调用或数据读写，虚线表示兼容接口的独立使用路径。DeepSeek 是外部服务，Embedding、Reranker 和 Chroma PersistentClient 在 app 内运行；模型文件通过只读缓存提供。

```mermaid
flowchart TB
    Browser["浏览器<br/>GLOBAL STORE 演示前端"]
    DeepSeek["DeepSeek 外部 API<br/>deepseek-chat"]

    subgraph Stack["Docker Compose 独立网络"]
        Nginx["Nginx / web<br/>127.0.0.1:8080 → 80<br/>静态页面与 API 反向代理"]

        subgraph App["FastAPI app 容器 / 内部 8000"]
            API["api.py<br/>请求校验与文本流响应"]
            Agent["agent_service.py<br/>读取历史与分支调度"]
            Router["intent_router.py<br/>chat / rag 分类"]
            ToolAgent["agent_tool_service.py<br/>Function Calling 循环"]
            RAG["rag.py<br/>检索、上下文选择、生成"]
            Embed["Embedding 服务<br/>BAAI/bge-small-zh-v1.5"]
            Rank["Reranker 服务<br/>BAAI/bge-reranker-base"]
            Chroma[("Chroma PersistentClient<br/>rag_chunks / cosine<br/>持久化卷 /app/chroma_data")]
            DataServices["文档与商品 HTTP 服务<br/>原文、管理、缓存与去重"]
            Legacy["兼容聊天接口 ai.py<br/>答案缓存与互斥锁"]
        end

        MySQL[("MySQL<br/>商品 / SKU / 文档 / 历史<br/>独立数据卷")]
        Redis[("Redis<br/>缓存 / 版本 / 锁 / Bitmap 布隆<br/>独立数据卷")]
    end

    Browser --> Nginx
    Nginx --> API
    API --> Agent
    Agent --> Router
    Router -->|"意图分类"| DeepSeek
    Agent -->|"chat"| ToolAgent
    Agent -->|"rag"| RAG
    ToolAgent -->|"模型判断与工具结果"| DeepSeek
    ToolAgent -->|"三个只读商品工具"| MySQL
    RAG --> Embed
    RAG -->|"候选检索"| Chroma
    RAG --> Rank
    RAG -->|"参考资料与问题"| DeepSeek
    API -->|"历史查询与分支内保存"| MySQL
    API --> DataServices
    DataServices -->|"文档原文与商品"| MySQL
    DataServices -->|"商品缓存 / 文档布隆"| Redis
    DataServices -->|"文档向量化入库"| Chroma
    API -.-> Legacy
    Legacy -.-> Redis
```

职责边界：

- `agent_service.py` 只负责一级结果后的调度，Chat 内部的工具判断由 `agent_tool_service.py` 执行。
- 商品工具直接调用业务服务/ORM 查询，不经过商品 HTTP API 的 Redis 缓存。
- Redis 并不参与所有 Agent 请求：文档去重、商品 HTTP 缓存和兼容聊天缓存/锁是不同使用路径。
- Chroma 不是独立 HTTP 服务；模型缓存不是向量索引，二者使用不同挂载位置。
- Nginx 对文本流关闭代理缓冲；响应按原 `text/plain` 协议返回，不封装 SSE 事件。

## 图二：Agent 两级决策工作流

```mermaid
flowchart TB
    Question["POST /agent/chat/stream<br/>用户问题与 user_id"]
    History["从 MySQL 读取该用户历史"]
    Intent["第一级 Intent Router<br/>DeepSeek 分类；最近最多 8 条历史"]
    Choice{"意图结果"}
    ChatUser["Chat：构建聊天历史上下文<br/>生成前保存用户问题"]
    ToolDecision["第二级 Function Calling<br/>DeepSeek 接收工具描述并决策"]
    NeedTool{"本轮返回 tool_calls？"}
    ToolCall["白名单校验与执行<br/>list_products / get_product_detail / get_sku_inventory"]
    ProductDB[("MySQL 商品与 SKU")]
    Observation["把工具结果作为 tool 消息<br/>继续交给 DeepSeek"]
    DirectAnswer["生成普通回答或基于工具结果回答"]
    QueryEmbed["RAG：Query Embedding"]
    Recall["Chroma 最多召回 5 块"]
    Rerank["对全部候选执行 Reranker"]
    Context["主题与事实覆盖选择<br/>最终最多 3 块"]
    Generate["DeepSeek 依据参考资料生成"]
    Stream["统一输出 text/plain 文本流<br/>Nginx → 浏览器 getReader"]
    Finish["正常完成后的分支历史保存<br/>Chat：最终 assistant<br/>RAG：事务保存 user 与 assistant"]
    Messages[("MySQL messages")]

    Question --> History --> Intent --> Choice
    Choice -->|"chat"| ChatUser
    Choice -->|"rag"| QueryEmbed
    Intent -.->|"异常 / 非法结果 / confidence 小于 0.65"| ChatUser
    ChatUser --> ToolDecision --> NeedTool
    NeedTool -->|"是"| ToolCall --> ProductDB
    ProductDB --> Observation --> ToolDecision
    NeedTool -->|"否"| DirectAnswer --> Stream
    QueryEmbed --> Recall --> Rerank --> Context --> Generate --> Stream
    Stream -->|"生成正常结束"| Finish --> Messages
    ChatUser -->|"预先保存 user"| Messages
```

实现细节：

- Router 只允许 `chat`、`rag`；历史每条最多保留 1500 字符，置信度阈值为 0.65。当前问题明确切换话题时优先使用当前问题。
- Chat 的生成上下文由 `ai.build_messages()` 构建：最近最多 20 条、总计最多 20000 个历史字符，并保留当前问题。Function Calling 有最大轮数/调用次数保护，图中省略了错误和上限分支。
- RAG 生成使用“当前问题 + 检索资料”；此路径并没有把完整聊天历史直接拼入 RAG 生成消息。历史在一级意图判断中仍然发挥作用。
- 图中的“统一”指响应协议一致，不是新增一个公共保存事务。Chat 先提交用户消息，失败时可能只留下用户问题；RAG 只有完整回答生成后才用 `save_conversation()` 一次提交问答对。
- 工具轮次中的模型文本片段也会累积到同一响应；图展示主要决策过程，省略逐个 delta 的输出细节。
- 没有候选或没有有效重排结果时，RAG 返回资料不足说明；并不强行调用 DeepSeek 编造回答。

对应源码：[调度](../agent_service.py)、[分类](../intent_router.py)、[工具循环](../agent_tool_service.py)、[工具注册](../agent_tools.py)、[RAG](../rag.py)、[历史保存](../database.py)。

## 图三：RAG 文档入库与检索流程

```mermaid
flowchart TB
    subgraph Ingest["显式文档上传链路"]
        Upload["POST /documents/upload<br/>multipart file"]
        Validate["文件名 / TXT 后缀 / ≤1 MiB<br/>UTF-8 解码 / 非空校验"]
        Hash["SHA-256 内容指纹"]
        Duplicate["Bloom 可能命中时查内容哈希<br/>文件名与 MySQL 唯一约束兜底"]
        Existing["已存在则返回 created=false<br/>不重复入库"]
        SaveText["MySQL 保存文档原文<br/>获得 document_id"]
        Split["split_text<br/>CRLF/LF 规范化<br/>chunk_size=200 / overlap=30"]
        DocEmbed["Embedding 文本块<br/>512 维归一化向量"]
        IndexWrite["写入 ID、文本、metadata、向量<br/>ID 由 document_id 与 chunk_index 组成"]
        Bloom["成功后维护 Redis Bitmap"]
        Compensation["向量处理异常：尽力补偿<br/>清理新向量并删除新 MySQL 文档"]
    end

    Store[("Chroma rag_chunks<br/>cosine / HNSW<br/>PersistentClient + 持久化卷")]

    subgraph Retrieval["问题检索与回答链路"]
        Query["进入 RAG 的当前问题"]
        QueryVector["相同 Embedding 服务<br/>生成查询向量"]
        Search["Chroma 查询<br/>最多 5 个候选及 distance、metadata"]
        Rank["BAAI/bge-reranker-base<br/>对全部候选计算 rerank_score"]
        Select["上下文选择<br/>最多 3 块；保留来源与块编号"]
        Prompt["组织参考资料与问题<br/>资料不足不得编造"]
        Answer["DeepSeek 生成 text/plain 流<br/>API 成功完成后保存问答"]
    end

    Upload --> Validate --> Hash --> Duplicate
    Duplicate -->|"文档已存在"| Existing
    Duplicate -->|"不是重复文档"| SaveText --> Split --> DocEmbed --> IndexWrite
    IndexWrite --> Store
    IndexWrite -->|"成功"| Bloom
    DocEmbed -.->|"失败"| Compensation
    IndexWrite -.->|"失败"| Compensation
    Query --> QueryVector --> Search
    Search -->|"只读查询"| Store
    Store -->|"候选文本 / distance / metadata"| Rank
    Rank --> Select --> Prompt --> Answer
```

检索与一致性说明：

图中的共享 Chroma 节点表示数据读写关系，不表示上传会自动触发用户问答。

1. **5 与 3 是不同阶段的上限。** Chroma 用 `min(5, collection.count())` 召回；Reranker 处理全部候选，上下文选择后最多保留 3 块，候选不足不会复制补齐。
2. 一般问题优先保持重排相关性；明确政策问题结合标题/filename 主题匹配，综合架构问题结合总览和缺失事实覆盖。选择规则不硬编码文档 ID 或 chunk ID，也不修改原始 Reranker 分数。
3. 当前没有 RAG 相关性分数阈值。Router 的 confidence 阈值与 Reranker 分数不是同一概念。
4. 文本 metadata 包含 `document_id`、`filename`、`chunk_index`；当前 Embedding、Reranker 模型分别为 `BAAI/bge-small-zh-v1.5` 和 `BAAI/bge-reranker-base`。
5. 入库顺序是先保存 MySQL，再切分、向量化和写 Chroma，最后维护布隆。补偿是尽力执行，不是跨三个存储的原子事务；失败后需核对并保留现场。
6. 本地 TXT 修改、目录中新加文件以及服务重启都不等于索引更新。`initialize_rag()` 保留在源码中，但不属于当前统一 Agent 的 Chroma 检索主链路。

对应源码：[上传接口](../api.py)、[文档服务](../document_service.py)、[切分与选择](../rag.py)、[向量操作](../chroma_service.py)、[Embedding](../embedding_service.py)、[Reranker](../reranker_service.py)、[Chroma 初始化](../chroma_client.py)。

三张图采用 GitHub 支持的基础 flowchart 语法，不依赖插件、外部图片或自定义主题。语法参考：[Mermaid Flowchart 官方说明](https://mermaid.js.org/syntax/flowchart.html)。
