"""Local document/split regression tests; no upload or vector-index update."""
import hashlib
from pathlib import Path

import pytest

from rag import split_text


PROJECT_INTRO = Path(__file__).resolve().parents[1] / "knowledge_base" / "project_intro.txt"
OVERVIEW = 'AI Chat Assistant技术总览：跨境电商导购与知识库客服。FastAPI后端，MySQL业务库，Redis缓存与并发锁。Agent先识别chat/rag，chat通过Function Calling查商品；RAG使用BAAI/bge-small-zh-v1.5 Embedding、Chroma向量检索、BAAI/bge-reranker-base重排，由DeepSeek流式回答。'
RAG_DESCRIPTION = 'RAG 检索与回答：问题使用相同 Embedding 服务向量化，Chroma HNSW 先召回最多 5 个候选，BAAI/bge-reranker-base CrossEncoder 重排后保留最多 3 块。当前没有相关性分数阈值。DeepSeek 根据参考资料生成回答，资料不足时如实说明，不编造答案。'
# Golden hashes from the 16 unchanged blocks before this optimization.
UNCHANGED_CHUNK_SHA256 = {0: '2ae9837a4fd0c2e400b4d184ec8e8ef43b41b7ea486a6e85b8730fc43c634aca',
 1: '4852d8ff018138f8570fc6096dd1b7ddeb3dcf66b53ce50fc796ea30986ab06e',
 2: '890c301bd07b281c78afe52bf93e9055f36cde6a2ea89e700cc0f02cee6fc480',
 3: '80730d660437fd7b8d8da070a377abd709b4f2622925afb5764e521e63b0023b',
 4: 'ff33b5594fd47b32271ef17cb31c2a84257821234cf7bc866556b389d90a7627',
 5: '9c083f1bd586e5ff59fb2157ef241e26d1825a0148c7024e65a663043fe6c999',
 6: '0a850ab3efd1fed997f7f9a777548e96b4f5dca6b9fe15e7bb5c368593510c6c',
 7: '24453b0a0e9c1e2ca3d45d86f693cdd57b7f8ed603e3f6a507ed6f9c9c1d0961',
 8: 'cb93d668fe691bfede35b5d950ebcfeb12ace01f97e735283a63f5c7b0d4d585',
 9: '3c41ffb3f2d68f35f292702e1a0de2107869278bd52de7759874791ba2234f4a',
 10: '316956d33fcbe6da9d9eb7e13e39d885c6d421abfe5d1590e4f402775a65c3e6',
 11: 'b395c0336cee759ac96537c634057501f2f71301c7a2c5528cb5ec9a72dc118c',
 13: '5b7a21e641af10c2841db18567c6abb2bf432700e3b02cc7eae34e1609f3f6a3',
 14: 'd96e2ec877a57be58ad58413196fe634d8aee3a22f124f4944e38179d70fbd4d',
 15: '01f7f45fa48c58df3061ea6ba736476e96ebd3826ea95dd3e848765dd65dcff5',
 16: 'bcb75d3e53cae67fcfbac51d057ec548e896f62df4c252ce1b27930bfc1d4fcc'}


@pytest.fixture
def project_chunks():
    raw_text = PROJECT_INTRO.read_bytes().decode("utf-8")
    chunks = split_text(raw_text)
    assert len(chunks) == 18
    return chunks


def test_project_intro_lf_and_crlf_split_identically():
    raw_text = PROJECT_INTRO.read_bytes().decode("utf-8")
    lf_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")

    lf_chunks = split_text(lf_text)
    crlf_chunks = split_text(lf_text.replace("\n", "\r\n"))

    assert len(lf_chunks) == 18
    assert crlf_chunks == lf_chunks


def test_project_overview_is_one_independent_final_chunk(project_chunks):
    assert len(OVERVIEW) == 197
    assert split_text(OVERVIEW) == [OVERVIEW]
    assert project_chunks[17] == OVERVIEW
    assert project_chunks.count(OVERVIEW) == 1


def test_rag_description_matches_five_candidates_and_three_contexts(project_chunks):
    assert project_chunks[12] == RAG_DESCRIPTION


@pytest.mark.parametrize(
    ("index", "expected_hash"), list(UNCHANGED_CHUNK_SHA256.items())
)
def test_original_unmodified_chunks_keep_their_content(
    project_chunks, index, expected_hash
):
    assert hashlib.sha256(project_chunks[index].encode("utf-8")).hexdigest() == expected_hash
