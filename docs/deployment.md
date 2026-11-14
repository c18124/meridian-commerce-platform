# MERIDIAN Docker 部署指南

本文对应仓库当前的 [Compose](../docker-compose.yml)、[应用 Dockerfile](../Dockerfile)、[Nginx Dockerfile](../deployment/Dockerfile.nginx) 和 [代理配置](../deployment/nginx.conf)。MERIDIAN 是平台名称，GLOBAL STORE 是演示店铺；部署标识保留 `global-store-*`，不要仅为改名而改动现有项目名或卷名。

[项目主页](../README.md) · [系统架构](architecture.md)

> 命令以 Windows PowerShell、仓库根目录为工作目录。本文是操作指南：文档整理期间没有执行启动、停止、重建、上传或数据恢复。请先选择场景，不能把首次初始化命令用在已有部署上。

## 选择部署场景

- **没有私有业务备份的新使用者**：按“首次部署”创建独立空环境，再显式添加自己的演示文档和商品。
- **当前已验收环境的使用者**：直接使用“现有部署维护”，不要重跑首次导入。
- **需要恢复完整旧数据**：使用“数据备份”和“恢复到新环境”。恢复会创建新项目/卷，不覆盖原环境。

仓库不包含私有 SQL、聊天历史、生产向量数据或真实密钥。克隆后不会自动得到验收环境的 5 份文档、1 件商品和 2 个 SKU。

## 部署架构与实际服务

浏览器通过 `127.0.0.1:8080` 访问 Nginx；Nginx 提供前端并代理 FastAPI。FastAPI 通过 Compose DNS 使用 `mysql:3306`、`redis:6379`，Chroma 由 app 内的 PersistentClient 使用，不另外启动 Chroma 服务容器。

| Compose 服务 | 容器内端口 | 宿主机端口 | 持久化/依赖 |
|---|---|---|---|
| `mysql` | 3306；镜像另有 33060 标记 | 不发布 | `mysql_data:/var/lib/mysql` |
| `redis` | 6379 | 不发布 | `redis_data:/data`；AOF 与 RDB |
| `app` | 8000 | 不发布，仅 expose | `chroma_data:/app/chroma_data`；模型目录只读挂到 `/models` |
| `web` | 80 | `127.0.0.1:${HTTP_PORT:-8080}` | Nginx 静态文件与反向代理 |

所有服务使用 `${Project}_default` 独立网络。app 等待 MySQL/Redis healthy，web 等待 app healthy。`expose: 8000` 不等于把宿主机 8000 发布出去；新旧容器使用相同内部端口不会导致宿主机冲突。依赖健康条件的含义见 [Docker 官方说明](https://docs.docker.com/compose/how-tos/startup-order/)。

当前已验收实例的精确名称为：

```text
global-store-20261114-215736-mysql-1
global-store-20261114-215736-redis-1
global-store-20261114-215736-app-1
global-store-20261114-215736-web-1
```

其网络为 `global-store-20261114-215736_default`；卷分别是 `global-store-20261114-215736_mysql_data`、`global-store-20261114-215736_redis_data`、`global-store-20261114-215736_chroma_data`。文档整理时只读 inspect 确认四个服务 healthy。原来的 `ai-chat-mysql`、`ai-chat-redis`、`ai-chat-assistant` 是其他运行实例，不是本 Compose 的服务名，不应停止或删除。

## 环境要求

- Docker Desktop 使用 Linux containers；Windows 使用可工作的 WSL2 后端。Linux 主机可使用 Docker Engine 与 Compose 插件，按对应 shell 调整命令。
- Compose 需支持 `service_healthy`、`up --wait`、`run --no-deps`、`exec` 和 `cp`。本次实际验收为 Engine 29.9.2、Compose 5.6.1，不把它们写成唯一可用的最低版本。
- 构建需访问镜像仓库、PyPI 和 PyTorch CPU wheel 源；真实问答需访问 DeepSeek API。
- 模型缓存需要两个完整模型的配置、tokenizer 和权重。验收缓存约 1.23 GB；镜像、构建缓存、MySQL/Redis 数据和备份还需要额外磁盘空间。两个模型在内存中运行，资源不足会导致加载缓慢或容器退出。
- 8080 空闲；若已占用，只为新的部署选择其他 `HTTP_PORT`，不要为避让修改数据库内部端口或抢占旧服务。
- Docker 采用 Python 3.12；本次镜像实测 3.12.16。主机可不安装 Python，下面提供容器内模型预热方式。

检查环境，不输出密钥：

```powershell
docker version
docker compose version
docker ps --format "{{.Names}} | {{.Ports}} | {{.Status}}"
docker system df
Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction SilentlyContinue
```

## 环境变量与私有文件

在仓库外创建私有部署目录，从 [deployment/.env.example](../deployment/.env.example) 复制模板。已有私有环境文件应直接复用，不能覆盖或重新生成密码。

```powershell
$ErrorActionPreference = "Stop"
$DeployRoot = Join-Path $env:USERPROFILE "meridian-deploy"
New-Item -ItemType Directory -Path $DeployRoot -Force | Out-Null
$EnvFile = Join-Path $DeployRoot "deployment.env"
if (Test-Path -LiteralPath $EnvFile) { throw "文件已存在，请复用它或选择新目录" }
Copy-Item -LiteralPath deployment/.env.example -Destination $EnvFile
notepad $EnvFile
```

填写模板中的全部值：

| 变量 | 用途 |
|---|---|
| `COMPOSE_PROJECT_NAME` | 独立部署标识，例如 `global-store-demo`；与后续 `-p` 完全一致 |
| `HTTP_PORT` | 宿主机入口，默认 8080 |
| `MYSQL_DATABASE` | 默认 `ai_chat`；恢复时必须与 SQL 备份的数据库名一致 |
| `MYSQL_USER`、`MYSQL_PASSWORD` | 新库应用用户及密码；使用随机、URL 安全字符，或正确进行 URL 编码 |
| `MYSQL_ROOT_PASSWORD` | 新 MySQL 管理密码，与应用密码分开 |
| `DATABASE_URL_DOCKER` | `mysql+pymysql://应用用户:应用密码@mysql:3306/ai_chat`；必须与上面的用户/密码一致 |
| `DEEPSEEK_API_KEY` | 自己的有效密钥，不是示例占位值 |
| `HF_CACHE_DIR` | 宿主机 Hugging Face 根缓存绝对路径，如 `C:/Users/你的用户名/.cache/huggingface`，其中应有 `hub/` |

Compose 为 app 设置 `REDIS_HOST=redis`、`REDIS_PORT=6379`、db0；新 Redis 不发布宿主机端口，当前没有密码。app 从 `DATABASE_URL_DOCKER` 接收运行时 `DATABASE_URL`。普通本地开发根目录 `.env` 的 `DATABASE_URL=127.0.0.1:3306` 不等于 Docker 连接地址，不能直接混用。

真实密码、SQL/向量备份和聊天历史都应放在仓库外并限制文件权限。不要把私有文件复制进 `deployment/`，也不要把带解析环境变量的完整 `docker compose config` 输出发到公开日志；使用 `config --quiet`。

## 首次部署

本节仅用于**全新项目、全新卷且没有需要保留的数据**。以下参数以模板默认值为例；若你修改模板，必须同步变量和访问端口。

```powershell
$Project = "global-store-demo"
$Base = "http://127.0.0.1:8080"
$CacheDir = Join-Path $env:USERPROFILE ".cache\huggingface"
New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null

docker compose --env-file $EnvFile -p $Project config --quiet
if ($LASTEXITCODE -ne 0) { throw "Compose 配置未通过" }
docker compose --env-file $EnvFile -p $Project ps -a
docker volume ls --filter "label=com.docker.compose.project=$Project"
```

如果该项目已经存在容器或数据卷，先核对它属于哪个环境，不要继续把它当作空环境。当前验收实例应使用后文的既有项目名，不能直接替换成上面的示例名。

### 构建与模型缓存准备

```powershell
docker compose --env-file $EnvFile -p $Project build
if ($LASTEXITCODE -ne 0) { throw "构建失败，保留日志，不启动服务" }
```

[Dockerfile](../Dockerfile) 安装相同版本的 CPU PyTorch，使用核心版本约束和 PyMySQL rsa extra，并执行 pip check；不改写业务代码。大型模型不打入镜像，app 只读挂载模型缓存并以离线模式加载。

如果缓存已有两个完整模型，可跳过在线预热。若是新机器，先确认剩余磁盘空间，再执行以下**只写模型缓存、不连接业务数据库**的临时容器命令。`$CacheDir` 必须与私有文件的 `HF_CACHE_DIR` 指向同一目录：

```powershell
docker run --rm `
  --mount "type=bind,source=$CacheDir,target=/models" `
  -e HF_HOME=/models -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 `
  --entrypoint python "${Project}-app:local" -c "from embedding_service import get_embedding_model; from reranker_service import get_reranker_model; get_embedding_model(); get_reranker_model(); print('models ready')"
if ($LASTEXITCODE -ne 0) { throw "模型缓存未准备完整" }
```

实际模型名是 `BAAI/bge-small-zh-v1.5`、`BAAI/bge-reranker-base`，加载与 tokenizer 文件需求以现有服务实现为准。首次下载量以实际源为准；上述约 1.23 GB 是本次已验收缓存记录，不是所有未来版本的大小承诺。

### 启动新空环境

```powershell
docker compose --env-file $EnvFile -p $Project up -d --wait mysql redis
if ($LASTEXITCODE -ne 0) { throw "数据库服务未健康" }
docker compose --env-file $EnvFile -p $Project run --rm --no-deps -T app python -c "from database import Base, engine; Base.metadata.create_all(engine)"
if ($LASTEXITCODE -ne 0) { throw "新库显式建表失败" }
docker compose --env-file $EnvFile -p $Project up -d --wait app web
if ($LASTEXITCODE -ne 0) { throw "应用未健康，先查看日志" }
docker compose --env-file $EnvFile -p $Project ps
```

MySQL 容器创建指定数据库和用户；上面的显式命令为新库建表，应用启动获取/创建 `rag_chunks`。**服务不会自动建 ORM 表、恢复私有数据或扫描 TXT 入库。** 当前未使用数据库结构迁移工具，已有表的变更不能靠启动自动完成。已有 SQL 恢复环境跳过显式建表，按恢复章节操作。

### 初始化自己的演示数据

仅在自己刚创建的空环境上执行。已经恢复旧备份或已有 23 条向量的环境跳过本节。

通过 Swagger 的 `POST /documents/upload` 上传四份政策及项目介绍，或在仓库根目录执行：

```powershell
$Files = @(
  "knowledge_base/policies/demo_returns.txt",
  "knowledge_base/policies/demo_shipping.txt",
  "knowledge_base/policies/demo_customs.txt",
  "knowledge_base/policies/demo_exchange.txt",
  "knowledge_base/project_intro.txt"
)
foreach ($File in $Files) {
  curl.exe --fail-with-body -F "file=@$File" "$Base/documents/upload"
  if ($LASTEXITCODE -ne 0) { throw "上传失败：$File；先核对现有状态，不循环重试" }
}
```

这些请求会写 MySQL、Chroma 和布隆过滤器，不是只读检查。当前文本切分记录为项目介绍 18 块、四份政策共 5 块；document_id 由新数据库分配，不要求项目介绍一定是 ID 9。`python_notes.txt` 不在上述演示集内，也不会自动上传。

商品数据不随 Git 提交。使用 Swagger 的 `POST /products` 创建你自己的演示商品：提供 `product_code`、`name`、非空 `skus`；每条 SKU 至少提供 `sku_code`、非负 `price`，库存按你的演示数据填写。字段详见 [API 说明](../README.md#api-接口)。记录响应中的真实 product_id 和 sku_code 后再测试工具，不要猜测已有编号或把验收报告中的库存当作新库当前值。

## 连通性与真实问答验证

- 前端：http://127.0.0.1:8080/
- API 文档：http://127.0.0.1:8080/docs
- OpenAPI：http://127.0.0.1:8080/openapi.json
- app 探针：`/health`；Nginx 探针：`/healthz`。

`/health` 是现有代码的固定状态返回，包含固定 `environment=local`；不能仅凭这段文字判断运行环境，也不能把 HTTP 200 等同于数据库/模型已验收。应结合容器网络、数据库实例、实际工具查询、RAG 日志及历史校验。

以下例子会调用真实 DeepSeek、产生费用和测试历史。先确认数据隔离：

```powershell
$DemoUser = "meridian-check-" + [guid]::NewGuid().ToString("N").Substring(0,12)
Invoke-RestMethod "$Base/history/$DemoUser"
$RequestFile = Join-Path $DeployRoot "smoke-request.json"
$Body = @{ user_id=$DemoUser; question="请用简单例子解释 Python 列表"; cache_mode="context" } | ConvertTo-Json
[IO.File]::WriteAllText($RequestFile, $Body, [Text.UTF8Encoding]::new($false))
curl.exe --no-buffer --fail-with-body -H "Content-Type: application/json" --data-binary "@$RequestFile" "$Base/agent/chat/stream"
Invoke-RestMethod "$Base/history/$DemoUser"
```

检查多段文本、正常结束、日志中的 intent，以及历史中完整的一问一答。之后可用同一独立用户询问实际商品 ID、SKU 和已入库政策；不要手工指定 intent 或直接绕过 Agent。若流失败，不要只凭 200 宣称成功，也不要自动重试掩盖证据。

如需清理，仅清理自己刚生成的测试用户，绝不使用现有 `001`：

```powershell
$ClearBody = @{ user_id=$DemoUser } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$Base/clear" -ContentType "application/json" -Body $ClearBody
Invoke-RestMethod "$Base/history/$DemoUser"
```

## 现有部署维护

当前已验收实例的私有文件位于仓库外。下面使用通用路径示例；将 `$EnvFile` 替换为你已保存的私有环境文件路径，不要覆盖或重新生成它：

```powershell
$EnvFile = Join-Path $env:USERPROFILE "meridian-deploy/deployment.env"
$Project = "global-store-20261114-215736"
$DeployRoot = Split-Path -Parent $EnvFile
$Base = "http://127.0.0.1:8080"
docker compose --env-file $EnvFile -p $Project ps
```

不要为了 MERIDIAN 改名而更换现有 `$Project`；项目名前缀变化会引用另一组网络和数据卷。

### 查看健康与日志

```powershell
docker compose --env-file $EnvFile -p $Project ps
docker compose --env-file $EnvFile -p $Project logs --tail 100 app web mysql redis
docker compose --env-file $EnvFile -p $Project logs -f app
```

Ctrl+C 只退出日志跟踪。日志可能含用户问题、资料或回答，公开前需要去除敏感业务内容；不要公开私有环境文件或解析后的完整 Compose 配置。

### 普通停止和重新启动

停止只使用 `stop`，保留容器和所有卷：

```powershell
docker compose --env-file $EnvFile -p $Project stop
```

重新启动已有数据环境：

```powershell
docker compose --env-file $EnvFile -p $Project up -d --wait
```

不要把删除数据卷作为普通停止或故障排查方法；不要执行 volume/system prune 或对旧项目做清理。本项目不需要在每次重启后重新上传知识库。

[manage.ps1](../deployment/manage.ps1) 可提供 `status/start/stop`，但其 start 要求私有文件旁已有项目匹配的 `migration_verified.json`；这是迁移保护机制。新空环境使用前面的直接 Compose 命令，不要伪造迁移 PASS 标记绕过检查。

### 项目更新后重新构建

先备份、核对业务/数据结构变化，再构建应用镜像。没有明确数据库升级方案时，不更新 MySQL/Redis 镜像或结构。

```powershell
docker compose --env-file $EnvFile -p $Project build app web
if ($LASTEXITCODE -ne 0) { throw "构建失败，不替换正在运行的服务" }
docker compose --env-file $EnvFile -p $Project up -d --no-deps --wait app web
```

这会按需更新 app/web，保留 MySQL、Redis 和命名卷。普通 `restart` 不会加载重新构建的镜像。修改 TXT 也不会自动更新已入库文档，不能把重启/重建镜像当作索引更新操作。

## 数据持久化

- MySQL 使用 `mysql_data`，挂载 `/var/lib/mysql`，保存四张业务表及相关索引。
- Redis 使用 `redis_data:/data`，开启 AOF、每秒 fsync 和 `save 60 1`；缓存版本及布隆状态在此，不是只保存在 app 内存。
- Chroma 使用 `chroma_data:/app/chroma_data`，保存 `rag_chunks`、文本、metadata 和向量；它不在 MySQL 中，也不是外部 Chroma 容器。
- 模型目录通过 `HF_CACHE_DIR` 只读挂载到 `/models`；它与 Chroma 卷用途不同，删除模型缓存会影响离线加载。
- Nginx 前端文件来自 web 镜像；app 的源码来自 app 镜像，不通过宿主机业务源码绑定挂载。

命名卷会带 Compose 项目前缀，不能只凭目录名相似就认定连接了同一个数据库。当前部署曾实际核对新 MySQL UUID、Redis run_id、DNS 地址和挂载，确认未连接旧环境。

## 数据备份

下列是未来运维操作，**文档整理时没有执行**。为保证三个存储的一致性，先安排停写窗口；单事务 mysqldump 只能保证 MySQL 自身一致，不能替代跨 MySQL/Redis/Chroma 的协调。

### 创建完整备份目录与 SQL

在确认 `$Project` 是需要备份的这组服务后，暂时停止它的前端和 app，保留 mysql/redis；不涉及其他项目：

```powershell
$BackupDir = Join-Path $DeployRoot ("backup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
if (Test-Path -LiteralPath $BackupDir) { throw "备份目录已存在" }
New-Item -ItemType Directory -Path $BackupDir | Out-Null
$BackupDir = (Resolve-Path -LiteralPath $BackupDir).Path.Replace('\','/')

docker compose --env-file $EnvFile -p $Project stop web app
docker compose --env-file $EnvFile -p $Project exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --skip-lock-tables --routines --events --triggers --hex-blob --no-tablespaces --set-gtid-purged=OFF --column-statistics=0 --default-character-set=utf8mb4 --databases "$MYSQL_DATABASE" > /tmp/meridian-full.sql'
if ($LASTEXITCODE -ne 0) { throw "SQL 导出失败，不使用部分备份" }
docker compose --env-file $EnvFile -p $Project cp mysql:/tmp/meridian-full.sql "${BackupDir}/ai_chat_full.sql"
if ($LASTEXITCODE -ne 0) { throw "SQL 文件复制失败" }
```

使用 `compose cp` 复制二进制文件，避免 Windows PowerShell 旧版 `>` 文本重编码破坏 SQL。SQL 包含聊天与业务数据，不应提交 Git。

### 导出逻辑校验包

下面是当前 Chroma 1.5.9 存储和现有迁移脚本对应的导出示例。临时 app 容器只读业务数据，写入仓库外备份目录，不启动 API。缓存和锁全部记录，但只标记文档布隆及缓存版本为迁移必需状态。

```powershell
$ExportCode = @'
import os, json, base64, sqlite3, datetime
from pathlib import Path
import numpy as np
import chromadb, redis
from sqlalchemy import create_engine, text
from deployment.data_transfer import canonical, sha, serialize, vector_hash

dest = Path('/backup')
engine = create_engine(os.environ['DATABASE_URL'])
snapshot = {'mysql': {}, 'table_DDL': {}}
with engine.connect() as conn:
    conn.exec_driver_sql('SET TRANSACTION READ ONLY')
    names = [r[0] for r in conn.exec_driver_sql('SHOW TABLES')]
    snapshot['table_names'] = names
    for name in names:
        quoted = conn.dialect.identifier_preparer.quote_identifier(name)
        rows = [serialize(dict(r)) for r in conn.execute(text('SELECT * FROM ' + quoted + ' ORDER BY id')).mappings()]
        snapshot['mysql'][name] = {'count': len(rows), 'rows_sha256': sha(canonical(rows))}
        snapshot['table_DDL'][name] = conn.exec_driver_sql('SHOW CREATE TABLE ' + quoted).fetchone()[1]
engine.dispose()

client = chromadb.PersistentClient(path='/app/chroma_data')
collection = client.get_collection('rag_chunks', embedding_function=None)
data = collection.get(include=['documents', 'metadatas', 'embeddings'])
db = sqlite3.connect('file:/app/chroma_data/chroma.sqlite3?mode=ro', uri=True)
cid = db.execute('SELECT id FROM collections WHERE name=?', ('rag_chunks',)).fetchone()[0]
records = []
for i, chunk_id in enumerate(data['ids']):
    seq = db.execute('SELECT e.seq_id FROM embeddings e JOIN segments s ON s.id=e.segment_id WHERE s.collection=? AND e.embedding_id=?', (cid, chunk_id)).fetchone()[0]
    seq = int(seq.decode() if isinstance(seq, bytes) else seq)
    original = db.execute('SELECT vector,encoding FROM embeddings_queue WHERE seq_id=? AND id=? AND topic=?', (seq, chunk_id, 'persistent://default/default/' + cid)).fetchone()
    if original is None or original[1] != 'FLOAT32':
        raise RuntimeError('Original FLOAT32 input unavailable; do not fabricate an exact migration payload')
    stored = np.asarray(data['embeddings'][i], dtype='<f4')
    incoming = np.frombuffer(original[0], dtype='<f4')
    records.append({'id': chunk_id, 'document': data['documents'][i], 'metadata': data['metadatas'][i], 'embedding': stored.tolist(), 'embedding_sha256': vector_hash(stored), 'original_input_embedding': incoming.tolist(), 'original_input_embedding_sha256': vector_hash(incoming)})
db.close()
assert len(records) == len({r['id'] for r in records})
payload = {'collection': 'rag_chunks', 'configuration': collection.configuration, 'count': len(records), 'dimension': 512, 'records': sorted(records, key=lambda r: r['id'])}

r = redis.Redis(host=os.environ['REDIS_HOST'], port=int(os.environ['REDIS_PORT']), db=int(os.environ.get('REDIS_DB', '0')), password=os.environ.get('REDIS_PASSWORD') or None)
required = {'bloom:demo-policies:v1', 'bloom:demo-policies:v1:meta', 'bloom:documents:v1', 'bloom:documents:v1:meta', 'cache:products:version'}
keys = []
for key in sorted(r.scan_iter()):
    value = r.dump(key)
    if value is None:
        continue
    name = key.decode('utf-8')
    keys.append({'key': name, 'type': r.type(key).decode(), 'pttl': r.pttl(key), 'dump_base64': base64.b64encode(value).decode(), 'dump_sha256': sha(value), 'migrate': name in required and not name.startswith('lock:')})
redis_export = {'exported_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'records': keys}
for name, value in [('source_snapshot.json', snapshot), ('chroma_export.json', payload), ('chroma_import_payload.json', payload), ('redis_export.json', redis_export)]:
    with (dest / name).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
print('logical export complete')
'@
$ExportCode | docker compose --env-file $EnvFile -p $Project run --rm --no-deps -T -v "${BackupDir}:/backup" app python -B -
if ($LASTEXITCODE -ne 0) { throw "逻辑备份失败，保留现场，不宣布备份成功" }
Get-ChildItem -LiteralPath $BackupDir -File | Get-FileHash -Algorithm SHA256 | Export-Csv -NoTypeInformation -Encoding UTF8 -LiteralPath "${BackupDir}/checksums.csv"
```

必须核对 SQL 和 JSON 均存在、非空、数量正确，并重新读取验证哈希。源 SDK 读取可能引起 Chroma 内部物理文件同步；不要把修改时间变化直接认定为逻辑损坏。不要直接复制正在运行的 HNSW 文件，也不要仅将 SDK 读出的已归一化向量再次 add 后宣称逐位一致。

如果原始输入队列已经被 Chroma 清理，上例会停止，不能伪造原始向量或降低校验标准。需要另行制定一致性快照/恢复方案。本例与内部表结构有关，不是跨所有 Chroma 版本的通用导出工具。

备份完整后再恢复这组服务：

```powershell
docker compose --env-file $EnvFile -p $Project up -d --wait app web
```

## 恢复到新环境

当前 [data_transfer.py](../deployment/data_transfer.py) 是**本项目验收数据集的一次性迁移工具**，约束为 rag_chunks 23 块、512 维、cosine，并校验五份文档的布隆状态。它不自动导出备份，不支持任意规模语料的一键恢复，也不负责读取 SQL 文件导入 MySQL。

先检查备份与这一合同匹配。若文档/向量数量已变化或缺少原始 FLOAT32 输入，不可绕过断言；应先制定新的恢复方案。没有私有备份的新用户走“首次部署”，不要把不完整文件拼成迁移包。

1. 按环境配置章节创建**另一份**私有环境文件，选择全新的 `global-store-restore-demo` 项目名、独立凭据，必要时使用 8081。数据库名应与 SQL 中一致。
2. 在下面代码中设置新的文件路径；始终保留原 `$EnvFile` 和原项目，不改旧文件、不覆盖旧卷。

```powershell
$ErrorActionPreference = "Stop"
$RestoreEnv = Join-Path $env:USERPROFILE "meridian-restore/deployment.env"
$RestoreProject = "global-store-restore-demo"
# 选择已核验的完整备份目录；检查 SQL、source_snapshot.json、
# chroma_import_payload.json、redis_export.json 和校验和，不包含环境文件。
$BackupDir = (Resolve-Path -LiteralPath (Read-Host "备份目录绝对路径")).Path.Replace('\','/')
$Manifest = Import-Csv -LiteralPath "${BackupDir}/checksums.csv"
if (-not $Manifest) { throw "缺少有效校验清单" }
foreach ($Item in $Manifest) {
  $Candidate = Join-Path $BackupDir (Split-Path -Leaf $Item.Path)
  if ((Get-FileHash -LiteralPath $Candidate -Algorithm SHA256).Hash -ne $Item.Hash) { throw "备份校验失败：$Candidate" }
}
docker compose --env-file $RestoreEnv -p $RestoreProject config --quiet
if ($LASTEXITCODE -ne 0) { throw "恢复目标配置未通过" }
docker compose --env-file $RestoreEnv -p $RestoreProject build
if ($LASTEXITCODE -ne 0) { throw "恢复目标构建失败" }
docker compose --env-file $RestoreEnv -p $RestoreProject up -d --wait mysql redis
if ($LASTEXITCODE -ne 0) { throw "恢复目标数据库未健康" }

$ExistingTables = docker compose --env-file $RestoreEnv -p $RestoreProject exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --skip-column-names "$MYSQL_DATABASE" -e "SHOW TABLES"'
if ($LASTEXITCODE -ne 0 -or $ExistingTables) { throw "目标数据库不为空或检查失败，禁止导入覆盖" }
docker compose --env-file $RestoreEnv -p $RestoreProject cp "${BackupDir}/ai_chat_full.sql" mysql:/tmp/meridian-restore.sql
if ($LASTEXITCODE -ne 0) { throw "SQL 恢复文件复制失败" }
docker compose --env-file $RestoreEnv -p $RestoreProject exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --binary-mode=1 --default-character-set=utf8mb4 < /tmp/meridian-restore.sql'
if ($LASTEXITCODE -ne 0) { throw "SQL 恢复失败，不重试覆盖" }

docker compose --env-file $RestoreEnv -p $RestoreProject run --rm --no-deps -T -v "${BackupDir}:/migration:ro" app python -m deployment.data_transfer import-redis /migration
if ($LASTEXITCODE -ne 0) { throw "Redis 恢复失败，暂停" }
docker compose --env-file $RestoreEnv -p $RestoreProject run --rm --no-deps -T -v "${BackupDir}:/migration:ro" app python -m deployment.data_transfer import-chroma /migration
if ($LASTEXITCODE -ne 0) { throw "Chroma 恢复失败，暂停" }
$VerifyJson = docker compose --env-file $RestoreEnv -p $RestoreProject run --rm --no-deps -T -v "${BackupDir}:/migration:ro" app python -m deployment.data_transfer verify /migration
if ($LASTEXITCODE -ne 0) { throw "数据校验失败，不启动对外页面" }
$Verified = ($VerifyJson -join "`n") | ConvertFrom-Json
if ($Verified.mysql.status -ne "PASS" -or $Verified.redis.status -ne "PASS" -or $Verified.chroma.status -ne "PASS") { throw "未获得三项 PASS" }
@{ project=$RestoreProject; status="PASS" } | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath (Join-Path (Split-Path -Parent $RestoreEnv) "migration_verified.json")
docker compose --env-file $RestoreEnv -p $RestoreProject up -d --wait app web
```

**必须使用 `python -m deployment.data_transfer`**；直接执行脚本路径可能找不到项目根模块。工具拒绝覆盖已有 Collection/Redis key，因此不要对同一目标重复运行导入。恢复失败只保留日志和新目标现场，不自动清空或覆盖任何源数据。

恢复后还需验证实例身份、新旧网络、全表指纹、SKU 库存、Chroma ID/文本/metadata/向量逐位校验、必要 Redis key/TTL/Bloom，再做独立用户真实流式问答、历史保存与重启持久化验收。只有全部通过才考虑人工切换使用。

## 隔离运行自动化测试

不要在挂载业务数据卷的 app 上直接运行 pytest。下面使用同一 app 镜像、临时容器层内 SQLite/Chroma 和全新专用 Redis；不挂载业务卷，也不带真实模型密钥。

```powershell
$TestId = [guid]::NewGuid().ToString("N").Substring(0,8)
$TestNet = "meridian-tests-$TestId"
$TestRedis = "meridian-test-redis-$TestId"
docker network create $TestNet
docker run -d --name $TestRedis --network $TestNet --network-alias test-redis redis:7.4
docker run --rm --network $TestNet `
  -e DATABASE_URL=sqlite:////tmp/meridian-tests.sqlite3 `
  -e DEEPSEEK_API_KEY=isolated-test-placeholder `
  -e REDIS_HOST=test-redis -e REDIS_PORT=6379 -e REDIS_DB=0 -e REDIS_PASSWORD= `
  -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 `
  --entrypoint sh "${Project}-app:local" `
  -c 'pip install --no-cache-dir pytest==9.1.1 && python -m pytest -q'
$TestExit = $LASTEXITCODE
docker stop $TestRedis
Write-Output "pytest exit code: $TestExit"
```

这类测试包含 Mock/隔离数据，不等于真实 DeepSeek 或真实业务验收；正式部署验收还使用了网络 guard 和 JUnit 证据。示例停止的只有刚创建的专用测试 Redis，不涉及服务栈或旧容器。测试工具没有加入生产依赖。

## 已有验收记录

2026-11-14 的私有部署报告及证据位于当前维护者的项目外备份目录，未放入公共仓库。本次文档整理核对的是该记录，不重跑真实模型请求或重启容器。

- Python 3.12.16 容器：331 passed、0 failed、0 skipped；1 条 Starlette/AnyIO 弃用警告。
- 普通聊天、商品列表、详情、SKU 库存、退货、配送、税费：7/7 真实 Agent 请求通过；包含分类/工具多轮的 17 次 DeepSeek HTTP 请求均 200。
- 新四服务 healthy；app 实际连接新 MySQL UUID 和新 Redis run_id，未连接旧环境。
- 迁移时 MySQL documents=5、products=1、product_skus=2、messages=58，行/结构指纹一致；测试用户 14 条消息核对后单独清理。
- Chroma rag_chunks=23，项目介绍 18、政策 5；ID、文本、metadata、512 维 FLOAT32 和 cosine 一致。
- 必要 Redis 业务 key、五份文档 Bloom 查询及临时探针读写通过；本次验收快照缓存版本为 285，不是应写死的配置常量。
- 四个新容器重启后 ID/挂载未变，MySQL/Redis/Chroma 数据再次通过校验，模型从只读缓存成功重载。

这些结果不承诺任意新数据集、未来依赖解析或新的部署环境自动通过。

## 常见故障排查

| 现象 | 先检查 | 不应采取的做法 |
|---|---|---|
| 8080 无法绑定 | 宿主机监听、HTTP_PORT、是否已存在同名项目 | 停掉不属于本项目的旧服务来抢端口 |
| MySQL 拒绝连接 | app 的 DATABASE_URL 主机必须是 mysql，凭据与初始化用户一致，mysql healthy | 在容器里使用 127.0.0.1:3306 指向数据库，或靠删卷重置密码 |
| 修改 MYSQL_PASSWORD 后仍失败 | 现有卷的账号不会因环境变量变更自动改密码 | 反复改 env 或删除卷；应制定账号变更/恢复方案 |
| Redis 连接或去重异常 | redis:6379/db0、必要 Bitmap/meta、缓存版本；不迁移临时锁 | FLUSHDB、复制有效锁、用 Bloom 代替精确查重 |
| 离线模型找不到 | HF_CACHE_DIR 根路径、hub 结构、tokenizer/权重完整、挂载只读 | 向生产索引写随机向量或用 Mock 冒充模型加载 |
| 页面能开但 API 失败 | runtime-config.js 同源覆盖、web→app:8000、实际 URL/日志 | 把浏览器 API 地址改成容器 DNS 或照抄宿主机 8000 |
| 回答一次性出现 | curl --no-buffer、Nginx proxy_buffering、Content-Type 和分块记录 | 擅自把 text/plain 改为 SSE |
| RAG 没资料 | 是否显式上传、MySQL 文档和 Chroma 实际来源/数量 | 以为把 TXT 放目录或重启就会入库，或清空旧索引重建 |
| 迁移模块导入失败 | 从 /app 使用 python -m deployment.data_transfer | 为了通过而改业务模块或再次导入数据 |
| healthy 但模型调用失败 | 密钥是否有效、DeepSeek 连通性、真实响应与历史是否完整 | 仅凭 /health 200 或固定 environment 字段宣布验收成功 |

当前仅验收本机访问。JWT/权限控制、公开写接口保护、CORS 收敛、公网 DNS/TLS 和压测不属于已经完成的公网生产能力；不要未经单独安全评审就公开暴露本演示服务。
