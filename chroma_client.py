    #chromaDB库的连接，管理向量集合
from pathlib import Path
import chromadb


# 1. 获取项目根目录下的向量数据库保存路径
CHROMA_DIR = Path(__file__).resolve().parent / "chroma_data"


# 2. 创建 ChromaDB 持久化客户端
chroma_client = chromadb.PersistentClient(
    path=str(CHROMA_DIR)
)


# 3. 创建或获取 RAG 向量集合
rag_collection = chroma_client.get_or_create_collection(
    name="rag_chunks",
    configuration={
        "hnsw": {
            "space": "cosine"           #选择余弦距离作为向量检索的距离算法
        }
    },
    embedding_function=None
)
