"""RAG 召回与问答（蓝图 §6.4/§9，PRD-06 §4.4/§4.5）——agent 域对接的公开契约。

本模块的 `retrieve` / `answer_question` 签名是跨域契约（agent 域的 rag.search /
rag.answer 工具直接编码调用），改动必须与蓝图同步。

召回规则落实（PRD-06 §4.4 与蓝图 §6.4"召回规则"）：
- 学生端硬过滤（vectorstore SQL 层）：已发布 + visibility=student + 授权 +
  未过期 + 关联台账未过期/未禁用；未发布资料永不进入学生召回（AC4）。
- 混合召回：settings.hybrid_search 开启时 score = 0.7*余弦 + 0.3*关键词
  （关键词 = CJK 字 bigram 重合率，纯 Python，离线可跑）。
- 结果只按证据相关性排序；已移除的上下文维度不再参与筛选、降权或提示。
- 多版本：同标题资料只保留最新已发布版本，引用中展示版本号。
- 低于阈值：best score < settings.score_threshold → below_threshold=True，
  由 answer_question 拒答，绝不编造（AC6）。
- 重排：仅当 settings.rerank_enabled=1 且存在启用的 'rerank' provider 时执行；
  通过 providers.complete() 让模型输出按相关性排序的候选编号 JSON 数组，
  解析失败/调用失败一律静默保持向量序（PRD-06 §11.1"重排模型失败用原始排序"）。
"""

from __future__ import annotations

import inspect
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field

from ..config import AppConfig
from .embeddings import embed_chunks, run_coro_sync
from .vectorstore import search as vector_search
from .vectorstore import search_keyword as keyword_search

# 拒答话术（PRD-06 §4.4"无召回结果/低于阈值"）
REFUSAL_MESSAGE = "知识库暂无可靠依据，无法给出专业结论"
GENERIC_ADVICE = "。建议先从预设学习路径入门对应模块，或把问题描述得更具体后再试"

# 证据压缩上限（近似 token）：喂给 LLM 合成器的证据总量，防止 prompt 膨胀
_EVIDENCE_BUDGET = 200
# 模板答案截取上限（PRD 未给数值，取一屏可读长度）
_ANSWER_SNIPPET = 300

_DEFAULT_SYSTEM_PROMPT = (
    "你是标航智导的知识问答助手。只允许依据给定证据回答；证据不足就明确说不知道，"
    "禁止编造规范条文。回答使用中文，条理清晰，必要时分步骤。"
)


def estimate_tokens(text: str) -> int:
    """Estimate mixed Chinese/ASCII token density for bounded prompts."""

    cjk = sum(1 for char in text if "一" <= char <= "鿿")
    rest = len(text) - cjk
    return cjk + max(0, rest // 4)


# ---------------------------------------------------------------- 设置加载

@dataclass
class RagSettings:
    """rag_settings 单行表的内存镜像；缺行时取 schema 默认值（迁移即默认）。"""

    chunk_size: int = 500
    chunk_overlap: int = 80
    title_inherit: bool = True
    # Keep the retired database value readable for already queued chunk jobs.
    # It is intentionally excluded from the admin DTO and no longer emitted in
    # new pipeline parameters, so removing the UI cannot break old work.
    table_strategy: str = "keep"
    top_k: int = 5
    score_threshold: float = 0.35
    # RAG answer sampling is kept alongside recall controls so deployments can
    # tune deterministic educational output without exposing provider internals.
    temperature: float = 0.3
    top_p: float = 0.9
    hybrid_search: bool = True
    rerank_enabled: bool = False
    citation_format: str = "【{title} {section} {page} v{version}】"
    refusal_policy: str = "refuse"  # refuse / generic_advice
    max_citations: int = 5
    prompt_template: str = ""
    prompt_template_version: str = "v1"
    query_rewrite_enabled: bool = False


def load_settings(db: sqlite3.Connection) -> RagSettings:
    """读取 rag_settings 单行；未 seed 时回退默认值，保证任何环境可召回。"""
    row = db.execute("SELECT * FROM rag_settings WHERE id = 1").fetchone()
    if row is None:
        return RagSettings()
    columns = set(row.keys())
    return RagSettings(
        chunk_size=row["chunk_size"],
        chunk_overlap=row["chunk_overlap"],
        title_inherit=bool(row["title_inherit"]),
        table_strategy=(str(row["table_strategy"]) if "table_strategy" in columns else "keep"),
        top_k=row["top_k"],
        score_threshold=row["score_threshold"],
        temperature=float(row["temperature"]) if "temperature" in columns else 0.3,
        top_p=float(row["top_p"]) if "top_p" in columns else 0.9,
        hybrid_search=bool(row["hybrid_search"]),
        rerank_enabled=bool(row["rerank_enabled"]),
        citation_format=row["citation_format"],
        refusal_policy=row["refusal_policy"],
        max_citations=row["max_citations"],
        prompt_template=row["prompt_template"],
        prompt_template_version=row["prompt_template_version"],
        query_rewrite_enabled=bool(row["query_rewrite_enabled"])
        if "query_rewrite_enabled" in row.keys()
        else False,
    )


# ---------------------------------------------------------------- 公开契约 DTO

@dataclass
class RagFilters:
    data_type: str | None = None
    published_only: bool = True
    document_ids: list[str] | None = None
    # ``hybrid`` preserves the configured default; callers can force pure
    # vector or lexical ranking for the administrator recall console.
    mode: str | None = None
    # This console/evaluation override is intentionally not a global setting:
    # it applies only to pure vector recall and is persisted with a test case.
    retrieval_top_p: float | None = None


@dataclass
class RagHit:
    chunk_id: str
    document_id: str
    title: str
    section_title: str | None
    page_start: int | None
    page_end: int | None
    version: str
    content: str
    score: float
    rerank_score: float | None = None


@dataclass
class RetrievalResult:
    hits: list[RagHit] = field(default_factory=list)
    latency_ms: int = 0
    below_threshold: bool = False
    notice: str | None = None
    rerank_model: str | None = None  # 实际执行重排的模型名；未重排为 None


@dataclass
class RagAnswer:
    answer: str
    steps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    followups: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    related_cap_ids: list[str] = field(default_factory=list)
    refused: bool = False
    notice: str | None = None


# ---------------------------------------------------------------- 关键词特征（混合召回）

_CJK_RUN_RE = re.compile(r"[一-鿿]+")


def _cjk_bigrams(text: str) -> set[str]:
    """抽取 CJK 字 bigram 特征（单字 run 退化为单字），纯 Python 关键词相似度用。"""
    grams: set[str] = set()
    for run in _CJK_RUN_RE.findall(text):
        if len(run) == 1:
            grams.add(run)
        else:
            grams.update(run[i : i + 2] for i in range(len(run) - 1))
    return grams


def _keyword_ratio(query: str, content: str) -> float:
    """query 的 CJK bigram 在 content 中的命中比例（0..1）。"""
    query_grams = _cjk_bigrams(query)
    if not query_grams:
        return 0.0
    return len(query_grams & _cjk_bigrams(content)) / len(query_grams)


async def _rewrite_query(query: str, data_type: str | None = None) -> str:
    """Expand a short learner query while keeping retrieval fail-open.

    Query rewriting is optional and provider-backed.  Returning the original
    query for every malformed, oversized, or unavailable response preserves the
    established offline retrieval contract instead of turning an enhancement
    into a hard dependency.
    """

    normalized_query = query.strip()
    if not normalized_query or len(normalized_query) >= 15:
        return query
    prompt = (
        "请将以下简短的数据标注学习问题扩写为更完整的检索查询，"
        "保留原意，补充相关专业术语和上下文，输出一行，不要解释：\n\n"
        f"原始查询：{normalized_query}\n数据类型：{data_type or '通用'}\n\n扩写查询："
    )
    try:
        from ..agent.providers import complete

        result = await complete(
            [{"role": "user", "content": prompt}],
            role="primary",
        )
        text = result.get("text") if isinstance(result, dict) else None
        rewritten = str(text).strip() if text is not None else ""
        return rewritten if rewritten and len(rewritten) < 200 else query
    except Exception:
        return query


# ---------------------------------------------------------------- 重排（可选，容忍缺失）

# 重排只作用于向量序前 N 名：候选全集可能很大，全量塞进 prompt 既贵又慢
_RERANK_POOL_SIZE = 20


def _build_rerank_prompt(query: str, hits: list[RagHit]) -> list[dict]:
    """组装重排 prompt：编号候选 + 要求只输出按相关性排序的编号 JSON 数组。"""
    lines = [f"[{i}] {hit.content[:200]}" for i, hit in enumerate(hits)]
    return [
        {
            "role": "system",
            "content": (
                "你是检索结果重排器。只输出一个 JSON 数组，按与问题的相关性从高到低"
                "排列候选编号（例如 [2,0,1]），不要输出任何其他内容。"
            ),
        },
        {"role": "user", "content": f"问题：{query}\n\n候选片段：\n" + "\n".join(lines)},
    ]


def _parse_rerank_order(text: str, n: int) -> list[int] | None:
    """从模型输出防御性解析候选编号排序；任何不符都返回 None（保持向量序）。

    防御点：输出可能夹带散文/markdown 代码围栏（取第一个 [...] 片段）、
    编号可能是字符串、可能越界或重复（跳过而非整单判废）、可能漏候选
    （漏掉的按原相对顺序追加到末尾，保证每个候选都有位次分）。
    """
    match = re.search(r"\[[^\[\]]*\]", text, re.DOTALL)
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, list) or not data:
        return None
    order: list[int] = []
    for item in data:
        try:
            idx = int(item)
        except (TypeError, ValueError):
            continue  # 单项无法解析时跳过，不轻易放弃整次重排
        if idx < 0 or idx >= n or idx in order:
            continue
        order.append(idx)
    if not order:
        return None
    order.extend(i for i in range(n) if i not in order)
    return order


def _try_rerank(db: sqlite3.Connection, query: str, hits: list[RagHit]) -> tuple[list[float] | None, str | None]:
    """尝试 provider 重排，返回 (位次分数列表, 模型名)；不可用/失败 → (None, None)。

    为什么没有专用 rerank 协议：provider 契约只有 4 种对话协议（蓝图 §1），
    重排统一走 providers.complete() 让模型输出排序后的编号 JSON 数组——这是
    零新增协议下的最小接入；extra_json.rerank_endpoint 为将来专用 rerank
    HTTP 端点预留，当前一律走 complete()。complete() 是 async，经
    run_coro_sync 桥接进本同步检索路径。
    """
    try:
        from ..agent import providers  # 懒加载：避免 rag 域硬依赖 agent 域
    except Exception:
        return None, None
    try:
        row = providers.get_enabled_provider(db, "rerank")
    except Exception:
        return None, None  # provider_configs 表缺失等异常环境：按未配置处理
    if row is None:
        return None, None
    messages = _build_rerank_prompt(query, hits)
    try:
        result = providers.complete(messages, role="rerank")
        if inspect.iscoroutine(result):
            result = run_coro_sync(result)
    except Exception:
        return None, None
    if not result or not result.get("text"):
        return None, None
    order = _parse_rerank_order(str(result["text"]), len(hits))
    if order is None:
        return None, None
    # 位次换算成分数：位次越靠前分越高，保持 retriever 按 rerank_score 降序的结构
    scores = [0.0] * len(hits)
    for rank, idx in enumerate(order):
        scores[idx] = float(len(order) - rank)
    return scores, str(row["model"])


# ---------------------------------------------------------------- retrieve

_RETRIEVAL_MODES = frozenset({"hybrid", "vector", "keyword"})


def _resolve_retrieval_mode(requested: str | None, hybrid_default: bool) -> str:
    """Resolve a console override while preserving the historical setting default."""
    if requested in _RETRIEVAL_MODES:
        return requested
    return "hybrid" if hybrid_default else "vector"


def _apply_retrieval_top_p(hits: list[RagHit], top_p: float, top_k: int) -> list[RagHit]:
    """Apply a vector-only cumulative cosine-similarity nucleus filter.

    Similarities are clamped to zero before normalization because cosine scores
    may be negative. A non-positive/empty mass keeps the best hit as a useful
    fail-open fallback; otherwise the smallest prefix whose cumulative mass
    reaches ``top_p`` is retained and finally capped by ``top_k``. The router
    validates the public range; this guard keeps direct internal callers from
    accidentally turning an invalid override into surprising filtering.
    """
    if not hits:
        return []
    if not 0.0 < float(top_p) <= 1.0:
        return hits[:top_k]
    if top_p >= 1.0:
        return hits[:top_k]
    masses = [max(0.0, float(hit.score)) for hit in hits]
    total = sum(masses)
    if total <= 0.0:
        return hits[:1]
    selected_count = 0
    cumulative = 0.0
    for mass in masses:
        selected_count += 1
        cumulative += mass / total
        if cumulative >= top_p:
            break
    return hits[: max(1, min(top_k, selected_count))]

def retrieve(
    db: sqlite3.Connection,
    config: AppConfig,
    query: str,
    filters: RagFilters,
    top_k: int | None = None,
) -> RetrievalResult:
    """混合召回 + 元数据过滤 + 阈值判定；config 目前仅作契约预留位。"""
    started = time.perf_counter()
    settings = load_settings(db)
    k = top_k if top_k and top_k > 0 else settings.top_k

    # The public retriever remains synchronous.  The small bridge isolates the
    # optional provider call and lets legacy callers keep their stable contract.
    effective_query = query
    if settings.query_rewrite_enabled and len(query.strip()) < 15:
        try:
            rewritten = run_coro_sync(_rewrite_query(query, filters.data_type))
            if isinstance(rewritten, str) and rewritten.strip():
                effective_query = rewritten.strip()
        except Exception:
            effective_query = query

    mode = _resolve_retrieval_mode(filters.mode, settings.hybrid_search)
    query_model: str | None = None
    if mode == "keyword":
        # Lexical mode deliberately avoids embedding generation so it remains
        # useful while a document is waiting for indexing or a provider is down.
        candidates = keyword_search(
            db,
            published_only=filters.published_only,
            data_type=filters.data_type,
            document_ids=filters.document_ids,
        )
    else:
        query_blobs, query_model = embed_chunks(db, [effective_query])  # provider 优先、本地兜底
        candidates = vector_search(
            db,
            query_blobs[0],
            embedding_model=query_model,
            published_only=filters.published_only,
            data_type=filters.data_type,
            document_ids=filters.document_ids,
        )

    # 多版本去重：同标题只保留最新已发布版本所属文档（published_at 优先）
    best_doc_by_title: dict[str, tuple[str, str]] = {}
    for cand in candidates:
        recency = (cand.published_at or "", cand.created_at or "")
        if cand.title not in best_doc_by_title or recency > best_doc_by_title[cand.title][1]:
            best_doc_by_title[cand.title] = (cand.document_id, recency)
    allowed_docs = {doc_id for doc_id, _ in best_doc_by_title.values()}

    scored: list[RagHit] = []
    for cand in candidates:
        if cand.document_id not in allowed_docs:
            continue  # 旧版本资料不参与召回
        keyword_score = _keyword_ratio(effective_query, cand.content)
        if mode == "keyword":
            score = keyword_score
        elif mode == "hybrid":
            score = 0.7 * cand.cosine + 0.3 * keyword_score
        else:
            score = cand.cosine
        scored.append(
            RagHit(
                chunk_id=cand.chunk_id,
                document_id=cand.document_id,
                title=cand.title,
                section_title=cand.section_title,
                page_start=cand.page_start,
                page_end=cand.page_end,
                version=cand.version,
                content=cand.content,
                score=round(score, 4),
            )
    )
    scored.sort(key=lambda h: h.score, reverse=True)
    # A per-run nucleus override applies only to pure vector similarity while
    # scores are still in cosine order. Hybrid and keyword runs retain their
    # established TopK behavior, and reranking never changes eligibility.
    if mode == "vector" and filters.retrieval_top_p is not None:
        scored = _apply_retrieval_top_p(scored, filters.retrieval_top_p, k)
    else:
        scored = scored[:k]

    # 可选重排：只重排向量序前 _RERANK_POOL_SIZE 名（控制 prompt 体积），
    # 成功则按 rerank_score 重排并记录模型名，失败静默保持向量序
    rerank_model: str | None = None
    if settings.rerank_enabled and scored:
        pool = scored[:_RERANK_POOL_SIZE]
        rerank_scores, rerank_model = _try_rerank(db, effective_query, pool)
        if rerank_scores is not None:
            for hit, rscore in zip(pool, rerank_scores):
                hit.rerank_score = round(rscore, 4)
            pool.sort(key=lambda h: h.rerank_score or 0.0, reverse=True)
            scored = pool + scored[_RERANK_POOL_SIZE:]
        else:
            rerank_model = None  # 重排未真正执行，诊断里如实报 None

    below_threshold = not scored or scored[0].score < settings.score_threshold
    latency_ms = int((time.perf_counter() - started) * 1000)
    return RetrievalResult(
        hits=scored,
        latency_ms=latency_ms,
        below_threshold=below_threshold,
        notice=None,
        rerank_model=rerank_model,
    )


# ---------------------------------------------------------------- answer_question

def _compress_evidence(hits: list[RagHit], budget: int = _EVIDENCE_BUDGET) -> str:
    """Compress evidence to an approximate token budget."""
    parts: list[str] = []
    total = 0
    for hit in hits:
        piece = f"【来源：《{hit.title}》{hit.section_title or ''} v{hit.version}】\n{hit.content}"
        remain = budget - estimate_tokens("\n\n".join(parts))
        if remain <= 0:
            break
        # A token-to-character multiplier of four is safe for ASCII and the
        # subsequent loop rechecks exact mixed-script density for CJK text.
        take = min(len(piece), max(1, remain * 4))
        fragment = piece[:take]
        while fragment and estimate_tokens("\n\n".join(parts + [fragment])) > budget:
            fragment = fragment[:-max(1, len(fragment) // 20)]
        if not fragment:
            break
        parts.append(fragment)
        total += estimate_tokens(fragment)
    return "\n\n".join(parts)


def _build_messages(settings: RagSettings, question: str, evidence: str) -> list[dict]:
    """组装喂给 composer 的消息；prompt_template 支持 {question}/{evidence} 占位。"""
    template = settings.prompt_template.strip()
    system = _DEFAULT_SYSTEM_PROMPT
    if template:
        try:
            system = template.format(question=question, evidence=evidence)
        except (KeyError, IndexError, ValueError):
            system = template  # 模板占位符写错时按纯文本系统提示用，不阻断问答
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"问题：{question}\n\n证据：\n{evidence}"},
    ]


_STEP_LINE_RE = re.compile(r"^\s*(?:\d+\s*[\.、\)]|[-*•]|第[一二三四五六七八九十]+步[：:]?)\s*(.+)$")
_SENT_SPLIT_RE = re.compile(r"[。！？!?]")
_LEADING_TITLE_RE = re.compile(r"^【[^】]*】\s*")


def _extract_steps(content: str, limit: int = 4) -> list[str]:
    """从命中内容提取步骤：优先编号/列表行，不足时按句号拆分，取前 limit 条。"""
    text = _LEADING_TITLE_RE.sub("", content.strip())  # 标题继承前缀不是步骤
    steps = [m.group(1).strip() for line in text.splitlines() if (m := _STEP_LINE_RE.match(line))]
    if not steps:
        steps = [s.strip() for s in _SENT_SPLIT_RE.split(text) if s.strip()]
    return [s[:120] for s in steps[:limit]]


def _template_answer(hit: RagHit) -> str:
    """无 LLM 时的确定性模板答案：首条命中内容截取（≤300 字，尽量在句读处收尾）。"""
    content = hit.content.strip()
    if len(content) <= _ANSWER_SNIPPET:
        return content
    cut = max(content.rfind(mark, 0, _ANSWER_SNIPPET) for mark in "。！？\n")
    if cut < _ANSWER_SNIPPET // 2:
        cut = _ANSWER_SNIPPET
    return content[: cut + 1].rstrip() + "…"


def _build_followups(cap_ids: list[str], hits: list[RagHit]) -> list[str]:
    """基于关联能力节点生成 3 条追问；能力不足时围绕命中资料补全。"""
    followups = [f"想进一步了解 {cap} 的实操要点和常见错误吗？" for cap in cap_ids[:3]]
    if hits:
        title = hits[0].title
        fallbacks = [
            f"《{title}》中的质检标准还有哪些？",
            f"如何在实际标注任务中应用《{title}》的规范？",
            f"与《{title}》相关的练习任务有哪些？",
        ]
        for item in fallbacks:
            if len(followups) >= 3:
                break
            followups.append(item)
    return followups[:3]


def answer_question(
    db: sqlite3.Connection,
    config: AppConfig,
    question: str,
    *,
    data_type: str | None = None,
    published_only: bool = True,
    document_ids: list[str] | None = None,
    top_k: int | None = None,
    mode: str | None = None,
    retrieval_top_p: float | None = None,
    composer=None,
) -> RagAnswer:
    """召回 + 证据压缩 + LLM/模板合成 + 引用组装；无可靠依据时拒答不编造（AC6）。

    composer 是 agent 域注入的可选合成器：`callable(messages) -> str | None`，
    本模块永不 import agent 代码；composer 缺失/失败时退回确定性模板答案。
    """
    settings = load_settings(db)
    result = retrieve(
        db,
        config,
        question,
        RagFilters(
            data_type=data_type,
            published_only=published_only,
            document_ids=document_ids,
            # Evaluation callers pass their saved console shape here so answer
            # metrics use the same candidate set as Recall@K.
            mode=mode,
            retrieval_top_p=retrieval_top_p,
        ),
        top_k=top_k,
    )

    if not result.hits or result.below_threshold:
        answer_text = REFUSAL_MESSAGE
        if settings.refusal_policy == "generic_advice":
            answer_text += GENERIC_ADVICE  # PRD-06 §4.4：低于阈值可给通用学习建议
        notes = [result.notice] if result.notice else []
        return RagAnswer(
            answer=answer_text,
            steps=[],
            notes=notes,
            followups=[],
            citations=[],
            related_cap_ids=[],
            refused=True,
            notice=result.notice,
        )

    hits = result.hits
    answer_text: str | None = None
    if composer is not None:
        messages = _build_messages(settings, question, _compress_evidence(hits))
        try:
            answer_text = composer(messages) or None
        except Exception:
            answer_text = None  # LLM 故障 → 模板降级（PRD-06 §11.1）
    if not answer_text:
        answer_text = _template_answer(hits[0])

    # 关联能力 = 命中文档 cap_ids 的保序并集（RagHit 契约不含 cap_ids，回查文档表）
    related_cap_ids: list[str] = []
    doc_ids = list(dict.fromkeys(h.document_id for h in hits))
    if doc_ids:
        placeholders = ",".join("?" for _ in doc_ids)
        for row in db.execute(
            f"SELECT cap_ids_json FROM rag_documents WHERE id IN ({placeholders})", doc_ids
        ):
            for cap in json.loads(row["cap_ids_json"] or "[]"):
                if cap not in related_cap_ids:
                    related_cap_ids.append(cap)

    notes: list[str] = []
    if result.notice:
        notes.append(result.notice)
    # 版本提示：引用展示版本号，避免误引过期资料（PRD-06 §4.4/§4.5）
    seen_versions: dict[str, str] = {}
    for hit in hits:
        seen_versions.setdefault(hit.title, hit.version)
    for title, version in list(seen_versions.items())[:3]:
        notes.append(f"《{title}》当前引用版本 {version}")

    citations = [
        {
            "document_id": hit.document_id,
            "title": hit.title,
            "section_title": hit.section_title,
            "page_start": hit.page_start,
            "page_end": hit.page_end,
            "version": hit.version,
            "score": hit.score,
        }
        for hit in hits[: settings.max_citations]
    ]
    return RagAnswer(
        answer=answer_text,
        steps=_extract_steps(hits[0].content),
        notes=notes,
        followups=_build_followups(related_cap_ids, hits),
        citations=citations,
        related_cap_ids=related_cap_ids,
        refused=False,
        notice=result.notice,
    )
