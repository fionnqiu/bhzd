"""确定性本地哈希嵌入器（512 维词袋，L2 归一化，struct 打包浮点数组）。

为什么存在：蓝图 §1 规定"嵌入走 provider，未配置时用确定性本地哈希嵌入"，
保证离线/演示/测试全链路可跑（PRD-06 §11 降级）。Wave2 的
`rag/embeddings.py` 会把本模块作为 fallback 复用，因此接口（模型名常量、
embed_text → bytes、bytes_to_vector）在此定型，不要改动签名。

为什么用"单字 + 单字 bigram"：中文没有空格分词，纯单字区分度差，纯 bigram
对英文/数字不友好；混合两类特征在零依赖下取得尚可的召回区分度。
"""

from __future__ import annotations

import hashlib
import math
import re
import struct

import numpy as np

EMBEDDING_MODEL = "local-hash-bow-512"
EMBEDDING_DIM = 512

# 英文/数字词 或 单个 CJK 字符
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[一-鿿]")


def _tokens(text: str) -> list[str]:
    """抽取特征 token：词/单字之外，再给相邻 CJK 单字补 bigram 特征。"""
    tokens = _TOKEN_RE.findall(text.lower())
    features: list[str] = []
    prev_cjk: str | None = None
    for tok in tokens:
        features.append(tok)
        if len(tok) == 1 and "一" <= tok <= "鿿":
            if prev_cjk is not None:
                features.append(prev_cjk + tok)  # CJK bigram
            prev_cjk = tok
        else:
            prev_cjk = None
    return features


def embed_text(text: str) -> bytes:
    """把文本嵌入为 512 维 L2 归一化向量，按小端 float32 打包为 bytes。

    每个特征 token 的 sha256 前 4 字节决定落桶下标（确定性，跨进程一致）。
    """
    vector = [0.0] * EMBEDDING_DIM
    for feature in _tokens(text):
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "little") % EMBEDDING_DIM
        vector[bucket] += 1.0
    norm = math.sqrt(sum(v * v for v in vector))
    if norm > 0:
        vector = [v / norm for v in vector]
    return struct.pack(f"<{EMBEDDING_DIM}f", *vector)


def bytes_to_vector(blob: bytes) -> list[float]:
    """把 `embed_text` 的 BLOB 还原为浮点列表（余弦检索用）。"""
    return list(struct.unpack(f"<{EMBEDDING_DIM}f", blob))


def bytes_to_array(blob: bytes) -> np.ndarray:
    """Expose an embedding BLOB as a zero-copy float32 view for batch-style scoring.

    The storage format has always been little-endian float32.  Keeping this
    conversion next to the serializer prevents callers from accidentally
    decoding provider vectors as Python floats before NumPy can process them.
    """
    return np.frombuffer(blob, dtype="<f4")


def cosine_similarity(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    """Return a defensive NumPy cosine score for local and provider embeddings."""
    vector_a = np.asarray(a, dtype=np.float32)
    vector_b = np.asarray(b, dtype=np.float32)
    # Provider changes and fallback indexing can leave different vector shapes
    # in durable storage.  They are incomparable, not a request-path error.
    if vector_a.ndim != 1 or vector_b.ndim != 1 or vector_a.shape != vector_b.shape:
        return 0.0
    na = float(np.linalg.norm(vector_a))
    nb = float(np.linalg.norm(vector_b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(vector_a, vector_b) / (na * nb))
