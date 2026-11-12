"""使用真实 ChromaDB 检索链评估跨境电商 RAG。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chroma_client import rag_collection
from chroma_service import search_similar_chunks


# 评估数据集
DATASET_PATH = (
    Path(__file__).parent
    / "tests"
    / "rag_eval_crossborder.json"
)

# 需要测试的 Top-K
K_VALUES = (1, 2, 3, 5)

# 与当前 rag.py 中的拒答阈值保持一致
REJECTION_THRESHOLD = 0.70


def load_dataset(path: Path) -> dict[str, Any]:
    """读取并验证评估数据集。"""

    with path.open("r", encoding="utf-8") as file:
        dataset = json.load(file)

    if not isinstance(dataset, dict):
        raise ValueError("评估数据集必须是 JSON 对象")

    expected_ids = dataset.get("expected_chunk_ids")

    if not isinstance(expected_ids, list) or not expected_ids:
        raise ValueError("expected_chunk_ids 必须是非空列表")

    if any(
        not isinstance(chunk_id, str) or not chunk_id.strip()
        for chunk_id in expected_ids
    ):
        raise ValueError("Chunk ID 必须是非空字符串")

    if len(expected_ids) != len(set(expected_ids)):
        raise ValueError("expected_chunk_ids 存在重复 ID")

    expected_id_set = set(expected_ids)

    questions = dataset.get("questions")

    if not isinstance(questions, list) or not questions:
        raise ValueError("questions 必须是非空列表")

    seen_question_ids = set()

    for position, item in enumerate(questions, start=1):

        if not isinstance(item, dict):
            raise ValueError(f"第 {position} 道题格式错误")

        question_id = item.get("id")
        question = item.get("question")
        relevant_ids = item.get("relevant_chunk_ids")
        answerable = item.get("answerable")

        if not isinstance(question_id, str) or not question_id.strip():
            raise ValueError(f"第 {position} 道题缺少有效 ID")

        if question_id in seen_question_ids:
            raise ValueError(f"题目 ID 重复: {question_id}")

        seen_question_ids.add(question_id)

        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"题目 {question_id} 的问题不能为空")

        if not isinstance(relevant_ids, list):
            raise ValueError(
                f"题目 {question_id} 的相关 Chunk ID 必须是列表"
            )

        if any(not isinstance(cid, str) for cid in relevant_ids):
            raise ValueError(
                f"题目 {question_id} 的 Chunk ID 必须是字符串"
            )

        if len(relevant_ids) != len(set(relevant_ids)):
            raise ValueError(f"题目 {question_id} 存在重复 Chunk ID")

        if not isinstance(answerable, bool):
            raise ValueError(f"题目 {question_id} 的 answerable 必须是布尔值")

        if answerable and not relevant_ids:
            raise ValueError(
                f"可回答题目 {question_id} 必须标注相关 Chunk"
            )

        if not answerable and relevant_ids:
            raise ValueError(
                f"无答案题目 {question_id} 不应标注相关 Chunk"
            )

        invalid_ids = set(relevant_ids) - expected_id_set

        if invalid_ids:
            raise ValueError(
                f"题目 {question_id} 引用了未知 Chunk: {invalid_ids}"
            )

    return dataset


def validate_live_chunks(
    dataset: dict[str, Any]
) -> int:
    """检查评估数据集标注的 Chunk 是否真实存在于 ChromaDB。"""

    result = rag_collection.get(
        include=["metadatas"]
    )

    live_ids = set(result["ids"])
    expected_ids = set(dataset["expected_chunk_ids"])

    missing_ids = expected_ids - live_ids

    if missing_ids:
        raise RuntimeError(
            f"ChromaDB 缺少评估所需的 Chunk: {sorted(missing_ids)}"
        )

    print("ChromaDB 实际记录数量:", len(live_ids))
    print("评估所需 Chunk 全部存在")

    return len(live_ids)


def mean(values: list[float]) -> float:
    """计算平均值。"""

    return sum(values) / len(values) if values else 0.0


def preview_chunk(
    content: str,
    max_length: int = 100
) -> str:
    """生成文本块预览。"""

    text = " ".join(content.split())

    if len(text) <= max_length:
        return text

    return text[:max_length - 1] + "…"


def evaluate() -> None:
    """执行真实 ChromaDB 检索评估。"""

    dataset = load_dataset(DATASET_PATH)

    total_chunks = validate_live_chunks(dataset)

    questions = dataset["questions"]

    answerable_count = sum(
        item["answerable"] for item in questions
    )

    unanswerable_count = len(questions) - answerable_count

    # 保存可回答问题的评估指标
    summaries = {
        k: {
            "hit": [],
            "recall": [],
            "precision": [],
            "rr": []
        }
        for k in K_VALUES
    }

    # 保存无答案问题的检索情况
    unanswerable = {
        k: {
            "returned_any": [],
            "returned_count": [],
            "top_score": [],
            "threshold_pass": []
        }
        for k in K_VALUES
    }

    # 记录有答案问题是否通过相似度阈值
    answerable_threshold_pass = []

    print("\n" + "=" * 70)
    print("跨境电商 RAG 检索评估")
    print("=" * 70)

    print("数据集:", DATASET_PATH)
    print("知识库文本块总数:", total_chunks)
    print("测试问题:", len(questions))
    print("可回答问题:", answerable_count)
    print("无答案问题:", unanswerable_count)

    # 每道题只执行一次检索，避免重复生成问题向量
    for number, item in enumerate(questions, start=1):

        question = item["question"]
        relevant_ids = set(item["relevant_chunk_ids"])

        print("\n" + "-" * 70)
        print(f"[{number}/{len(questions)}] {item['id']}")
        print("问题:", question)
        print("人工标注:", sorted(relevant_ids))

        # 一次取出最多 5 个结果
        retrieved_all = search_similar_chunks(
            question,
            top_k=max(K_VALUES)
        )

        # 获取第一名的相似度
        top_similarity = (
            1.0 - float(retrieved_all[0]["distance"])
        )

        # 统计可回答问题是否通过阈值
        if item["answerable"]:
            answerable_threshold_pass.append(
                top_similarity >= REJECTION_THRESHOLD
            )

        expected_count = min(max(K_VALUES), total_chunks)

        if len(retrieved_all) != expected_count:
            raise RuntimeError(
                f"检索数量错误，期望 {expected_count}，"
                f"实际 {len(retrieved_all)}"
            )

        # 展示真实检索结果
        for rank, result in enumerate(
            retrieved_all,
            start=1
        ):

            similarity = 1.0 - float(result["distance"])

            print(
                f"  Rank {rank} | "
                f"ID={result['id']} | "
                f"文件={result['metadata']['filename']} | "
                f"相似度={similarity:.4f}"
            )

            print(
                "    ",
                preview_chunk(result["content"])
            )

        # 分别计算不同 K 的指标
        for k in K_VALUES:

            retrieved = retrieved_all[:k]

            retrieved_ids = [
                result["id"]
                for result in retrieved
            ]

            if item["answerable"]:

                hit_count = len(
                    relevant_ids.intersection(retrieved_ids)
                )

                hit_rate = 1.0 if hit_count else 0.0

                recall = hit_count / len(relevant_ids)

                precision = (
                    hit_count / len(retrieved_ids)
                    if retrieved_ids else 0.0
                )

                first_relevant_rank = next(
                    (
                        rank
                        for rank, chunk_id in enumerate(
                            retrieved_ids,
                            start=1
                        )
                        if chunk_id in relevant_ids
                    ),
                    None
                )

                reciprocal_rank = (
                    1.0 / first_relevant_rank
                    if first_relevant_rank else 0.0
                )

                summaries[k]["hit"].append(hit_rate)
                summaries[k]["recall"].append(recall)
                summaries[k]["precision"].append(precision)
                summaries[k]["rr"].append(reciprocal_rank)

                print(
                    f"  K={k}: "
                    f"Hit={hit_rate:.4f}, "
                    f"Recall={recall:.4f}, "
                    f"Precision={precision:.4f}, "
                    f"MRR={reciprocal_rank:.4f}"
                )

            else:

                # 无答案问题不计算 Recall 和 Precision
                returned_any = bool(retrieved_ids)

                unanswerable[k]["returned_any"].append(
                    returned_any
                )

                unanswerable[k]["returned_count"].append(
                    len(retrieved_ids)
                )

                if retrieved:

                    top_similarity = (
                        1.0 - float(retrieved[0]["distance"])
                    )

                    unanswerable[k]["top_score"].append(
                        top_similarity
                    )

                    unanswerable[k]["threshold_pass"].append(
                        top_similarity >= REJECTION_THRESHOLD
                    )

    # 输出可回答问题的汇总
    print("\n" + "=" * 70)
    print("可回答问题评估汇总")
    print("=" * 70)

    for k in K_VALUES:

        metrics = summaries[k]

        print(
            f"K={k}: "
            f"Hit Rate={mean(metrics['hit']):.4f} | "
            f"Recall={mean(metrics['recall']):.4f} | "
            f"Precision={mean(metrics['precision']):.4f} | "
            f"MRR={mean(metrics['rr']):.4f}"
        )

    print("\n" + "=" * 70)
    print("可回答问题的阈值评估")
    print("=" * 70)

    passed = sum(answerable_threshold_pass)
    total = len(answerable_threshold_pass)

    print(
        f"通过0.70阈值: {passed}/{total}"
    )

    print(
        f"放行比例: {mean([
            1.0 if value else 0.0
            for value in answerable_threshold_pass
        ]):.4f}"
    )

    # 输出无答案问题的汇总
    print("\n" + "=" * 70)
    print("无答案问题评估汇总")
    print("=" * 70)

    for k in K_VALUES:

        stats = unanswerable[k]

        threshold_pass_count = sum(
            stats["threshold_pass"]
        )

        threshold_pass_rate = mean([
            1.0 if passed else 0.0
            for passed in stats["threshold_pass"]
        ])

        print(
            f"K={k}: "
            f"平均返回块数={mean(stats['returned_count']):.2f} | "
            f"Top1平均相似度={mean(stats['top_score']):.4f} | "
            f"当前0.70阈值放行={threshold_pass_count}/"
            f"{unanswerable_count} | "
            f"放行比例={threshold_pass_rate:.4f}"
        )

    print("\n评估完成。")

    print(
        "注意：本脚本评估真实检索结果，"
        "不调用 DeepSeek，也不等同于端到端拒答测试。"
    )


if __name__ == "__main__":
    evaluate()
