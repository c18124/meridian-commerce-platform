# MERIDIAN — Commerce Intelligence Platform

**Meridian 跨境电商智能服务平台**

*Smarter Commerce. Better Experiences.*

MERIDIAN 是面向跨境电商场景的 AI 智能服务平台：将商品和 SKU 的实时业务查询、店铺政策知识检索与普通自然语言问答，统一接入一个可流式交互的 Agent 入口。

项目使用 Python / FastAPI、DeepSeek、MySQL、Redis 与 Chroma，实现了从意图识别、工具执行、知识检索到回答生成、聊天历史保存和 Docker 部署的完整链路。

**MERIDIAN 是软件系统的正式产品名称；GLOBAL STORE 是系统内的演示店铺。** 当前前端保留 GLOBAL STORE 品牌，展示商品咨询、库存查询及售后政策咨询场景，不代表实际运营中的商城。

[系统架构与三张流程图](docs/architecture.md) · [Docker 部署与数据维护](docs/deployment.md)

正式仓库：[c18124/meridian-commerce-platform](https://github.com/c18124/meridian-commerce-platform)。

## 项目解决的问题

- 商品和库存信息需要来自真实业务数据库，不能让模型根据历史回答猜测。
- 退货、配送、清关等政策需要依据知识库原文回答，资料不足时应明确说明。
- 用户不应手动判断问题属于 Chat 还是 RAG；系统应自动选择能力。
- 生成过程需要持续返回内容，同时保留 Markdown 展示、异常处理和聊天历史。
- 部署需要明确区分数据库、缓存与向量索引，支持独立持久化及迁移校验。

## 核心功能

### 智能客服与 Agent

- 统一入口：`POST /agent/chat/stream`，由后端识别 `chat` / `rag`。
- 第一级由 Intent Router 结合最近历史判断问题意图；低置信度、非法结果或异常回退为 `chat`。
- 第二级仅位于 Chat 分支：DeepSeek 通过 Function Calling 决定直接回答，或调用商品工具后继续生成回答。
- 三个工具均为只读工具，通过白名单调度，校验工具名称与参数，并限制调用轮次和次数。

| 工具 | 参数 | 实际能力 |
|---|---|---|
| `list_products` | `page=1`、`page_size=20` | 分页读取商品列表 |
| `get_product_detail` | `product_id` | 读取商品详情及关联 SKU、价格、规格 |
| `get_sku_inventory` | `sku_code` | 读取该 SKU 的当前库存 |

商品工具直接查询 MySQL，不复用模型先前回答中的库存，也不经过商品 HTTP 接口的 Redis 结果缓存。商品和 SKU 的创建、修改、删除属于独立业务 API，不对大模型开放写入工具。

### RAG 与文档入库

- 通过 `POST /documents/upload` 上传 UTF-8 TXT，支持 BOM，单文件不超过 1 MiB。
- SHA-256 内容指纹、文件名检查、Redis Bitmap 布隆预检查与 MySQL 唯一约束共同处理重复文档；布隆判断不替代数据库精确查询。
- MySQL 保存原文后，进行换行规范化及文本切分，默认 `chunk_size=200`、`overlap=30`，再生成向量并写入 Chroma。
- Embedding：`BAAI/bge-small-zh-v1.5`，512 维；Reranker：`BAAI/bge-reranker-base` CrossEncoder。
- 当前检索链路：**Chroma 最多召回 5 块 → 全部候选重排 → 选择最多 3 块作为上下文 → DeepSeek 回答**。
- 在排序基础上对明确政策主题、综合架构问题做主题匹配与事实覆盖选择；不改变模型原始重排分数，没有固定相关性分数过滤阈值。
- 文档入库失败存在补偿清理逻辑；MySQL、Redis、Chroma 并非一个分布式事务，异常后仍需核对状态。

知识库目录中的 TXT **不会随服务启动自动全部入库**。演示政策可通过现有脚本或上传接口显式导入，项目介绍需显式上传。仅修改本地 TXT 不会更新已有数据库原文或向量索引。

### 数据、缓存与交互

- MySQL / SQLAlchemy ORM：保存商品、SKU、文档原文和聊天历史，包含唯一约束及价格、库存非负约束。
- Redis：商品列表/详情缓存、商品缓存版本失效、随机 TTL、文档布隆过滤器，以及旧聊天流式路径中的缓存互斥锁、令牌校验释放和自动续期。
- 兼容接口 `/chat`、`/chat/stream` 保留上下文/问题缓存模式；**统一 Agent 的 Chat 分支当前不启用普通聊天答案缓存**。分布式锁也不是请求限流或库存扣减机制。
- 聊天使用 HTTP `text/plain` 流，前端以 `fetch`、`ReadableStream.getReader()` 和 `TextDecoder` 拼接；不是 SSE。
- 按 `user_id` 保存、读取和清空历史。RAG 完整生成成功后事务保存问答对；Chat 分支先保存用户问题，再在完成后保存最终回答。
- GLOBAL STORE 前端支持响应式布局、Loading、Enter 发送、控件禁用/恢复、自动滚动、Toast、Markdown 表格与代码高亮。
- Markdown 经 Marked 解析后由 DOMPurify 清理，再使用 highlight.js 高亮；GSAP 提供轻量动画。

## 技术栈

| 类别 | 实际使用 |
|---|---|
| 后端 | Python、FastAPI、Pydantic、Uvicorn、SQLAlchemy 2.x、PyMySQL |
| AI | DeepSeek `deepseek-chat`、OpenAI 兼容 Python SDK、手写 Agent 路由与 Function Calling、RAG |
| 向量检索 | ChromaDB 1.5.9 PersistentClient、cosine / HNSW、Sentence Transformers、BGE Embedding、BGE Reranker |
| 数据库与缓存 | MySQL 8.0、Redis 7.4、SQLAlchemy ORM、Redis Bitmap、布隆过滤器、分布式锁 |
| 前端 | HTML、CSS、原生 JavaScript、Fetch / Streams API、Marked、DOMPurify、highlight.js、GSAP |
| 部署 | Docker、Docker Compose、Nginx |
| 测试 | pytest、FastAPI TestClient、HTTPX、monkeypatch、临时 SQLite / Chroma 和独立 Redis |

运行依赖见 [requirements.txt](requirements.txt)，当前容器核心版本约束见 [deployment/constraints-py312.txt](deployment/constraints-py312.txt)。pytest 是测试依赖，未写入生产依赖文件；仓库没有 `requirements-dev.txt`。SQLite 用于隔离测试及历史文件兼容说明，当前业务数据库是 **MySQL**。

## 系统架构

部署时，浏览器通过 Nginx 获取静态页面，并同源请求 FastAPI。Agent Service 从 MySQL 读取历史，调用 Intent Router，再选择 Chat 或 RAG：

1. **Chat**：DeepSeek 决定是否调用商品工具；工具读取 MySQL，将结构化结果返回模型，模型组织最终回答。
2. **RAG**：问题向量化后从 Chroma 召回候选，Reranker 重排，上下文选择器保留最多三块，DeepSeek 依据资料生成回答。
3. 两条路径均使用普通文本流返回；各分支按自身完成条件保存历史。
4. MySQL 是业务事实和文档原文来源；Redis 承担特定路径的缓存、互斥与去重预检查；Chroma 保存检索用文本块、metadata 和向量。

Chroma 位于 app 容器内，通过 `PersistentClient` 访问持久化卷，**不是额外部署的 Chroma 服务容器**。完整调用关系和保存时序见 [架构文档](docs/architecture.md)。

## 项目目录

下列为当前仓库的核心文件，省略缓存、私有环境文件、运行数据及历史备份：

```text
.
├── api.py                       # FastAPI 路由与请求模型
├── agent_service.py             # 第一级分类后的分支调度
├── intent_router.py             # chat/rag 分类、历史裁剪与回退
├── agent_tool_service.py        # Chat 分支 Function Calling 循环
├── agent_tools.py               # 三个只读工具及白名单
├── ai.py                        # DeepSeek 客户端、历史构建及兼容聊天缓存
├── rag.py                       # 切分、检索、上下文选择与生成
├── document_service.py          # 文档去重、入库、更新/删除服务及补偿
├── embedding_service.py         # Embedding 延迟加载与编码
├── reranker_service.py          # CrossEncoder 延迟加载与重排
├── chroma_client.py             # PersistentClient 与 rag_chunks
├── chroma_service.py            # 文本块向量写入、查询、删除
├── database.py                  # ORM 模型、会话及持久化函数
├── product_service.py           # 商品/SKU 业务操作
├── product_cache.py             # 商品缓存与版本失效
├── redis_client.py              # Redis 客户端与随机 TTL
├── redis_lock.py                # 分布式锁、释放与续期
├── redis_bloom_filter.py        # Redis Bitmap 布隆实现
├── bloom_filter.py              # 位数组参数与哈希位置计算
├── config.py                    # 环境变量与模型配置
├── seed_demo_policies.py         # 显式导入四份演示政策
├── index.html                   # GLOBAL STORE 页面及聊天交互
├── static/
│   ├── css/style.css            # 当前店铺视觉与响应式样式
│   ├── js/animation.js          # 轻量动画
│   ├── js/runtime-config.js     # 本地 API 回退；部署时由 Nginx 覆盖
│   └── videos/                  # 保留的旧素材，当前页面不使用视频背景
├── knowledge_base/
│   ├── project_intro.txt
│   ├── python_notes.txt
│   └── policies/               # 退货、配送、清关、换货四份 TXT
├── tests/                      # API、Agent、商品、缓存、RAG 等测试
├── deployment/
│   ├── Dockerfile.nginx
│   ├── nginx.conf
│   ├── constraints-py312.txt
│   ├── .env.example
│   ├── data_transfer.py         # 向全新目标导入与迁移校验
│   ├── manage.ps1              # 指定 Compose 项目的管理入口
│   └── README.md               # 原部署辅助说明，保留不改
├── docs/
│   ├── architecture.md
│   └── deployment.md
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

`document_service.py` 中存在文档更新、删除服务函数，但当前 FastAPI **只公开文档上传接口**；目录中的函数不能等同于已提供相应 HTTP API。

## 本地开发运行

已验证环境：本地 Python 3.13.12，Docker Python 3.12.16。建议选择 Python 3.12 或已验证的 3.13 环境，并优先使用容器复现验收版本。以下命令在仓库根目录执行。

### 安装依赖

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt -c deployment/constraints-py312.txt "PyMySQL[rsa]==1.2.3"
python -m pip install pytest==9.1.1 httpx
```

### 配置本地环境

先准备可连接的 MySQL 及 Redis，并在 MySQL 创建空的 `ai_chat` 数据库及相应用户。当前应用不会自动创建数据库或 ORM 表，也不会自动迁移结构、灌入演示数据。

在根目录创建仅供本地使用、不可提交的 `.env`，示例均为占位值：

```dotenv
DEEPSEEK_API_KEY=replace_with_your_key
DATABASE_URL=mysql+pymysql://your_user:your_url_encoded_password@127.0.0.1:3306/ai_chat
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=
```

模型名称和 DeepSeek Base URL 目前在源码配置中固定；不要把它们误写为已有的可配置环境变量。首次 RAG 使用需要下载模型或已有 Hugging Face 缓存。

仅在新建的数据库上执行一次显式建表；已有迁移数据不要重复初始化，也不能用它替代结构升级方案：

```powershell
python -c "from database import Base, engine; Base.metadata.create_all(engine)"
```

### 启动本地后端与前端

后端：

```powershell
python -m uvicorn api:app --host 127.0.0.1 --port 8001 --reload
```

另开终端，在仓库根目录提供静态页面：

```powershell
python -m http.server 5500 --bind 127.0.0.1
```

- 本地前端：http://127.0.0.1:5500/
- 本地 API 文档：http://127.0.0.1:8001/docs
- Docker 前端及同源 API：http://127.0.0.1:8080/
- Docker API 文档：http://127.0.0.1:8080/docs

本地静态页面使用 `8001` 回退；部署页面由 Nginx 注入同源配置。不要把容器内 `app:8000` 写成浏览器访问地址。Docker 首次启动、数据初始化和现有迁移环境的操作见 [部署文档](docs/deployment.md)。

## API 接口

以下根据当前 `api.py` 及运行中 OpenAPI 核对；以 Swagger 展开的模型约束为准。示例会调用真实模型并保存独立测试历史，不是只读请求。

聊天请求 `ChatRequest`：

```json
{
  "user_id": "meridian-demo",
  "question": "店铺退货期限是多少？",
  "cache_mode": "context"
}
```

`user_id`、`question` 必填，去除首尾空白；`question` 长度 1–4000。`cache_mode` 可选，为 `context` 或 `question`，默认 `context`；它在统一 Agent 中属于兼容参数，不表示启用了旧聊天答案缓存。当前消息表 user_id 列宽 50，而请求模型上限为 100，调用方应使用不超过 50 字符的短标识。

| 分类 | 方法 | 路径 | 用途与必要参数 |
|---|---|---|---|
| Agent | POST | `/agent/chat/stream` | 统一自动路由，JSON `ChatRequest`；返回文本流 |
| 兼容聊天 | POST | `/chat` | 直接普通聊天，`ChatRequest`；返回 `answer` JSON |
| 兼容聊天 | POST | `/chat/stream` | 直接普通聊天流，`ChatRequest` |
| RAG | POST | `/rag/chat` | 直接 RAG，`ChatRequest`；返回 `answer` JSON |
| RAG | POST | `/rag/chat/stream` | 直接 RAG 文本流，`ChatRequest` |
| 历史 | GET | `/history/{user_id}` | 路径参数 `user_id`，返回 `messages`（role/content） |
| 历史 | POST | `/clear` | JSON 必填 `user_id`；清空指定用户历史 |
| 文档 | POST | `/documents/upload` | multipart 必填 `file`，UTF-8 TXT，≤1 MiB |
| 商品 | GET | `/products` | 分页：`page≥1`，`page_size=1..100`，默认 1/20 |
| 商品 | GET | `/products/{product_id}` | 商品详情及 SKU；路径整数 `product_id` |
| 商品 | POST | `/products` | 创建商品，JSON 必填 `product_code`、`name`、非空 `skus`；成功 201 |
| 商品 | PATCH | `/products/{product_id}` | JSON 至少更新 `name/category/description/is_active` 中一个字段 |
| 商品 | DELETE | `/products/{product_id}` | 删除指定商品及其关联 SKU |
| SKU | PATCH | `/products/skus/{sku_id}` | JSON 至少更新 `sku_code/color/size/price/stock/is_active` 中一个字段 |
| SKU | DELETE | `/products/skus/{sku_id}` | 删除指定 SKU |
| 健康 | GET | `/health` | 返回固定状态信息；不代表已执行数据库连通性检查 |

创建商品时每条 SKU 必填 `sku_code`、非负 `price`；`stock` 默认 0、`is_active` 默认 true，颜色/尺码可选；价格最多两位小数。商品请求模型禁止额外字段。SKU 实时库存查询目前通过 Agent 工具提供，没有单独的 `GET /inventory` 接口。

Swagger：`/docs`；OpenAPI：`/openapi.json`；ReDoc：`/redoc`。Nginx 的 `/healthz` 是单独的静态探针，不是 FastAPI 业务路由。

## 测试与验收

以下为 **2026-11-14 Docker 部署验收记录**，已核对项目外的 `global_store_docker_deployment_report.md` 及其测试/数据校验证据；不是本次文档整理重新执行的测试，也不是测试徽章。

| 项目 | 已记录结果 |
|---|---|
| 自动化 | Python 3.12 容器：331 passed、0 failed、0 skipped；1 条依赖弃用警告 |
| 真实功能 | 普通聊天、商品列表、商品详情、SKU 库存、退货、配送、税费，7/7 PASS |
| 模型链路 | 7 次真实 Agent 请求，17 次 DeepSeek HTTP 请求（含分类/工具多轮），均 200 |
| 容器 | 新 MySQL、Redis、FastAPI、Nginx 四个容器 healthy |
| 数据迁移 | MySQL 全表/结构及新实例身份核对通过；必要 Redis 状态和布隆查询通过 |
| 向量与重启 | Chroma 23 块，项目介绍 18、政策 5；512 维 FLOAT32、ID/文本/metadata/cosine 核对及重启验收通过 |
| 历史与流 | 经 Nginx 持续接收 text/plain；14 条测试历史与回答一致，随后仅清理测试用户 |

上述商品、文档、历史数量是私有演示部署的验收快照，**不是 GitHub 克隆后自动拥有的数据**。原始 SQL、向量及聊天历史备份保存在仓库外，不应公开提交。

测试需使用隔离的数据库、Chroma 和 Redis，模型/接口测试与真实调用分开记录；不要在挂载现有业务卷的 app 中直接跑全套测试。配置好隔离环境后运行：

```powershell
python -m pytest -q
```

隔离容器示例见 [部署文档的测试章节](docs/deployment.md#隔离运行自动化测试)。

## 当前边界

- 未实现 JWT 登录、账户系统或 RBAC；`user_id` 是调用方传入的历史分组标识，不是身份认证。前端当前固定使用 `001`，不代表已实现安全多租户。
- 商品管理、文档上传和历史接口当前没有权限控制；CORS 允许所有来源。公网使用前仍需单独设计访问控制与安全配置。
- 没有支付、订单管理、物流追踪、实际人工客服或真实商城交易闭环。政策、商品及 GLOBAL STORE 均用于演示。
- 文档更新/删除有服务函数，但未公开 HTTP 路由；不支持 PDF 等非 TXT 上传，也没有文件目录自动增量同步。
- RAG 仍受候选召回、资料覆盖及模型生成影响；不保证所有问题都有答案。一次请求只选择一个一级分支，不保证混合任务同时执行 Chat 和 RAG。
- 流式响应是普通文本，不包含 SSE 事件、工具执行事件或可供前端消费的分类 confidence 字段。
- 当前消息表不保存消息创建时间；页面时间标记不等同于服务端历史时间戳。
- 已验证的是本机 Docker 部署；公网 DNS/TLS、外部流量、容量与并发压测未验收。
- 代码、示例知识文档中仍保留历史名称 AI Chat Assistant；本次仅整理 MERIDIAN 产品文档，不修改前端品牌、提示词或知识库索引。

## Docker 部署入口

请阅读 [docs/deployment.md](docs/deployment.md)。文档区分新建空环境、现有数据迁移和当前已验收部署，说明模型缓存、持久化、备份恢复与故障排查。
