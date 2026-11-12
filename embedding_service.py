    #单独创建的一个模型服务模块，用于调用模型，专门负责把文本变成向量
from sentence_transformers import SentenceTransformer


# 1. 指定 Embedding 模型
MODEL_NAME = "BAAI/bge-small-zh-v1.5"


# 2. 保存模型对象
_model = None


# 3. 获取模型  延迟加载 + 模块级单例设计
def get_embedding_model():

    global _model

    # 如果模型还没有加载，就加载一次
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)

    return _model


# 4. 将多段文本转换成向量
def encode_texts(texts: list[str]) -> list[list[float]]:

    # 获取模型
    model = get_embedding_model()

    # 批量生成向量
    vectors = model.encode(
        texts,
        normalize_embeddings=True
    )

    # 将 NumPy 数组转换成 Python列表给ChromaDB
    return vectors.tolist()


# 5. 将用户问题转换成单个向量
def encode_query(question: str) -> list[float]:

    vectors = encode_texts([question])

    return vectors[0]
