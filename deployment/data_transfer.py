"""One-time imports into NEW Docker volumes only; never opens the source database.

The host backup contains full SQL, Chroma logical records/original input vectors,
and Redis DUMP payloads. Existing target collections/keys are never overwritten.
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import re

import numpy as np
import redis
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def target_guard():
    assert os.getenv("GLOBAL_STORE_DOCKER_TARGET") == "1", "Docker target marker required"
    assert Path.cwd() == Path("/app"), "Must run in the new Docker app container"
    assert make_url(os.environ["DATABASE_URL"]).host == "mysql", "Refusing a host/source MySQL URL"
    assert os.environ.get("REDIS_HOST") == "redis", "Refusing a host/source Redis URL"


def chroma_collection(create=False):
    import chromadb
    client = chromadb.PersistentClient(path="/app/chroma_data")
    if create:
        assert "rag_chunks" not in {c.name for c in client.list_collections()}, "Target collection already exists; never overwrite"
        return client.create_collection("rag_chunks", configuration={"hnsw": {"space": "cosine"}}, embedding_function=None)
    return client.get_collection("rag_chunks", embedding_function=None)


def vector_hash(vector):
    array = np.asarray(vector, dtype="<f4")
    assert array.shape == (512,) and np.isfinite(array).all()
    return sha(array.tobytes())


def verify_chroma(payload):
    collection = chroma_collection()
    assert collection.configuration["hnsw"]["space"] == "cosine"
    got = collection.get(include=["documents", "metadatas", "embeddings"])
    ids = got["ids"]
    assert len(ids) == len(set(ids)) == payload["count"] == 23
    actual = {
        chunk_id: {"document": got["documents"][i], "metadata": got["metadatas"][i],
                   "embedding_sha256": vector_hash(got["embeddings"][i])}
        for i, chunk_id in enumerate(ids)
    }
    expected = {
        r["id"]: {key: r[key] for key in ("document", "metadata", "embedding_sha256")}
        for r in payload["records"]
    }
    differences = [key for key in actual.keys() | expected.keys() if actual.get(key) != expected.get(key)]
    assert not differences, f"Chroma mismatch; stop cutover, preserve target: {differences}"
    counts = {}
    for row in actual.values():
        name = row["metadata"]["filename"]
        counts[name] = counts.get(name, 0) + 1
    return {"status": "PASS", "collection": "rag_chunks", "count": len(ids),
            "dimension": 512, "distance": "cosine", "source_counts": counts,
            "all_ID_document_metadata_stored_float32_hashes_identical": True,
            "stored_fingerprint": sha(canonical(actual))}


def import_chroma(path):
    payload = load(path)
    assert payload["collection"] == "rag_chunks" and payload["count"] == 23
    rows = payload["records"]
    assert len(rows) == len({r["id"] for r in rows}) == 23
    for row in rows:
        assert vector_hash(row["embedding"]) == row["embedding_sha256"]
        assert vector_hash(row["original_input_embedding"]) == row["original_input_embedding_sha256"]
    collection = chroma_collection(create=True)
    # Chroma cosine storage normalizes input. Reuse the original input, so the
    # stored vector is not normalized a second time from SDK-returned values.
    collection.add(ids=[r["id"] for r in rows], documents=[r["document"] for r in rows],
                   metadatas=[r["metadata"] for r in rows],
                   embeddings=[r["original_input_embedding"] for r in rows])
    return verify_chroma(payload)


def redis_client():
    return redis.Redis(host="redis", port=6379, db=0, decode_responses=False)


def import_redis(path):
    payload = load(path)
    client = redis_client()
    assert client.ping() and client.dbsize() == 0, "Target Redis must be empty; never replace keys"
    elapsed_ms = int((datetime.datetime.now(datetime.timezone.utc) -
                      datetime.datetime.fromisoformat(payload["exported_at"])).total_seconds() * 1000)
    migrated, skipped = [], []
    for row in payload["records"]:
        if not row["migrate"] or row["key"].startswith("lock:"):
            skipped.append(row["key"])
            continue
        ttl = max(0, row["pttl"] - elapsed_ms) if row["pttl"] > 0 else 0
        if row["pttl"] > 0 and ttl == 0:
            skipped.append(row["key"])
            continue
        value = base64.b64decode(row["dump_base64"])
        assert sha(value) == row["dump_sha256"]
        client.restore(row["key"], ttl, value)  # no REPLACE, no FLUSHDB
        migrated.append(row["key"])
    return {"status": "PASS", "migrated": migrated, "skipped": skipped}


def serialize(row):
    return {key: value.isoformat() if isinstance(value, (datetime.datetime, datetime.date))
            else str(value) if type(value).__name__ == "Decimal" else value
            for key, value in row.items()}


def verify_mysql(source):
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    counts, document_hashes = {}, []
    with engine.connect() as conn:
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")
        names = [row[0] for row in conn.exec_driver_sql("SHOW TABLES")]
        assert sorted(names) == sorted(source["table_names"])
        for name in names:
            assert re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name)
            rows = [serialize(dict(r)) for r in conn.execute(text(f"SELECT * FROM `{name}` ORDER BY id")).mappings()]
            expected = source["mysql"][name]
            assert len(rows) == expected["count"] and sha(canonical(rows)) == expected["rows_sha256"], f"MySQL rows differ: {name}"
            ddl = conn.exec_driver_sql(f"SHOW CREATE TABLE `{name}`").fetchone()[1]
            normalized = lambda sql: re.sub(r" AUTO_INCREMENT=\d+", "", sql)
            assert normalized(ddl) == normalized(source["table_DDL"][name]), f"Schema differs: {name}"
            counts[name] = len(rows)
            if name == "documents":
                document_hashes = [r["content_hash"] for r in rows]
    engine.dispose()
    return {"status": "PASS", "counts": counts, "all_rows_and_schema_identical": True}, document_hashes


def verify_redis(payload, document_hashes):
    client = redis_client()
    checked = []
    for row in payload["records"]:
        if not row["migrate"]:
            continue
        assert sha(client.dump(row["key"])) == row["dump_sha256"], f"Redis differs: {row['key']}"
        assert client.type(row["key"]).decode() == row["type"]
        if row["pttl"] == -1:
            assert client.pttl(row["key"]) == -1
        checked.append(row["key"])
    from bloom_filter import BloomFilter
    meta = json.loads(client.get("bloom:demo-policies:v1:meta"))
    calculator = BloomFilter(meta["capacity"], meta["error_rate"])
    assert len(document_hashes) == 5
    for content_hash in document_hashes:
        assert all(client.getbit("bloom:demo-policies:v1", p) for p in calculator._get_positions(content_hash)), "Document Bloom false negative"
    return {"status": "PASS", "necessary_keys_identical": checked, "five_document_hashes_present_in_bloom": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["import-chroma", "import-redis", "verify"])
    parser.add_argument("backup_path", help="Read-only /migration mount containing the backups")
    args = parser.parse_args()
    target_guard()
    path = Path(args.backup_path)
    if args.action == "import-chroma":
        result = import_chroma(path / "chroma_import_payload.json")
    elif args.action == "import-redis":
        result = import_redis(path / "redis_export.json")
    else:
        sql, hashes = verify_mysql(load(path / "source_snapshot.json"))
        result = {"mysql": sql, "chroma": verify_chroma(load(path / "chroma_import_payload.json")),
                  "redis": verify_redis(load(path / "redis_export.json"), hashes)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
