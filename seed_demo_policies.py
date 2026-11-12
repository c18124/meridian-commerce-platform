"""将演示政策导入 MySQL 和 ChromaDB。"""    #知识库数据初始化脚本

from pathlib import Path

from chroma_client import rag_collection
from chroma_service import add_document_chunks
from database import Base, SessionLocal, engine
from document_service import upload_document
from rag import split_text
from redis_bloom_filter import RedisBloomFilter


POLICY_DIR = Path(__file__).resolve().parent / "knowledge_base" / "policies"


def seed_demo_policies() -> None:
    policy_files = sorted(POLICY_DIR.glob("*.txt"))
    if not policy_files:
        raise FileNotFoundError(f"未找到演示政策文件：{POLICY_DIR}")

    Base.metadata.create_all(engine)
    bloom = RedisBloomFilter(
        capacity=1000, error_rate=0.01, key="bloom:demo-policies:v1"
    )

    with SessionLocal() as db:
        for path in policy_files:
            content = path.read_text(encoding="utf-8").strip()
            result = upload_document(db, path.name, content, bloom)
            if result["created"]:
                print(f"已导入 {path.name}")
                continue

            document = result["document"]
            if document.filename != path.name or document.content != content:
                raise ValueError(f"{path.name} 与已有文档冲突，请核对后再导入")

            chunks = split_text(document.content)
            indexed = rag_collection.get(
                where={"document_id": document.id},
                include=["documents"],
            )
            expected = {
                f"{document.id}_{index}": chunk
                for index, chunk in enumerate(chunks)
            }
            actual = dict(zip(indexed["ids"], indexed["documents"], strict=True))
            if any(expected.get(chunk_id) != chunk for chunk_id, chunk in actual.items()):
                raise ValueError(f"{path.name} 的索引与原文不一致，请核对后再导入")
            if actual != expected:
                add_document_chunks(document.id, document.filename, chunks)
                print(f"已补齐索引 {path.name}")
            else:
                print(f"已存在 {path.name}")


if __name__ == "__main__":
    seed_demo_policies()
