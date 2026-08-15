/**
 * 系统管理 · 召回测试（/admin/rag/search-test）——召回对比 + 生成回答 + 诊断 + 存评测用例（PRD-03 §10）。
 *
 * 关键决策（为什么）：
 * - 双列对比"原始召回 vs 重排后"是 §10 验收硬性要求；未启用重排时后端返回
 *   rerank_note，页面如实展示而不是假装有两套排序。
 * - "生成回答"走学生端同一入口 /api/rag/query（answer_question）：测试台看到
 *   的答案与学生端一致，拒答/不确定性话术也一并验证（AC6 不编造）。
 * - 阈值命中标记用后端 below_threshold 全局旗标——score_threshold 是系统管理
 *   端参数，教师角色读不到，前端不猜数值。
 * - 保存评测用例直接 POST /api/rag/eval-cases（而非 search-test 的 save 旗标），
 *   避免为存一条用例重跑一次检索；filters 快照随用例落库，保证评测复现条件。
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type {
  EvalCase,
  Paginated,
  RagAnswer,
  RagDocument,
  SearchTestHit,
  SearchTestResult,
} from "../../api/types";
import {
  Button,
  Card,
  CitationCard,
  Field,
  EmptyState,
  Input,
  Modal,
  PageHeader,
  Select,
  Tabs,
  Tag,
  Textarea,
  useToast,
} from "../../components";
import {
  clamp,
  DATA_TYPE_OPTIONS,
  errText,
  fmtTime,
} from "./ragShared";
import RagDocumentMultiSelect from "./RagDocumentMultiSelect";

/** 单条命中卡片：内容/相似度/重排分/来源位置（PRD-03 §10 召回结果字段） */
function HitCard({ hit, showRerank }: { hit: SearchTestHit; showRerank: boolean }) {
  const pages =
    hit.page_start != null
      ? hit.page_end != null && hit.page_end !== hit.page_start
        ? `第 ${hit.page_start}-${hit.page_end} 页`
        : `第 ${hit.page_start} 页`
      : null;
  return (
    <div
      className="mb-3"
      style={{
        border: "1px solid var(--color-border)",
        borderRadius: "var(--radius-md)",
        padding: "var(--space-3)",
      }}
    >
      <div className="flex items-center gap-2 mb-2" style={{ flexWrap: "wrap" }}>
        <strong className="text-sm">{hit.title}</strong>
        <Tag>相似度 {hit.score.toFixed(3)}</Tag>
        {showRerank && hit.rerank_score != null ? <Tag>重排 {hit.rerank_score.toFixed(3)}</Tag> : null}
      </div>
      <p className="text-sm text-secondary mb-2">{clamp(hit.content, 200)}</p>
      <p className="text-xs text-muted">
        来源位置：{[hit.section_title, pages, `v${hit.version}`].filter(Boolean).join(" · ") || "—"}
      </p>
    </div>
  );
}

type SearchTestTab = "console" | "saved";

interface SavedCasesPanelProps {
  cases: EvalCase[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onLoad: (caseItem: EvalCase) => void;
}

/** Saved cases stay lightweight: loading one restores the console draft without rerunning it. */
function SavedCasesPanel({ cases, loading, error, onRetry, onLoad }: SavedCasesPanelProps) {
  return (
    <Card
      title={`已保存用例（${cases.length}）`}
      actions={
        <Button size="sm" variant="secondary" loading={loading} onClick={onRetry}>
          刷新
        </Button>
      }
    >
      {error ? (
        <div className="flex items-center gap-2" role="alert">
          <span className="text-danger text-sm">{error}</span>
          <Button size="sm" variant="secondary" onClick={onRetry}>
            重试
          </Button>
        </div>
      ) : loading && cases.length === 0 ? (
        <p className="text-sm text-secondary">正在加载已保存用例…</p>
      ) : cases.length === 0 ? (
        <EmptyState title="暂无已保存用例" hint="在测试台运行一次召回后，可将问题保存为评测用例" />
      ) : (
        <ul>
          {cases.map((caseItem) => (
            <li
              key={caseItem.id}
              className="flex items-start justify-between gap-3"
              style={{ borderBottom: "1px solid var(--color-border)", padding: "var(--space-3) 0" }}
            >
              <div style={{ minWidth: 0 }}>
                <strong className="text-sm">{caseItem.question}</strong>
                <p className="text-xs text-muted mt-1">
                  {caseItem.must_hit_document_ids.length > 0
                    ? `必须命中 ${caseItem.must_hit_document_ids.length} 份资料`
                    : "用于验证拒答"}
                  {caseItem.expected_answer ? " · 含标准答案" : ""}
                  {caseItem.created_at ? ` · ${fmtTime(caseItem.created_at)}` : ""}
                </p>
              </div>
              <Button
                size="sm"
                variant="secondary"
                aria-label={`加载用例：${caseItem.question}`}
                onClick={() => onLoad(caseItem)}
              >
                加载到测试台
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function SearchTestPage() {
  const toast = useToast();
  const [activeTab, setActiveTab] = useState<SearchTestTab>("console");

  // ---- 查询表单 ----
  const [question, setQuestion] = useState("");
  const [documents, setDocuments] = useState<RagDocument[]>([]);
  const [docIds, setDocIds] = useState<string[]>([]);
  const [dataType, setDataType] = useState("");
  const [topK, setTopK] = useState("");
  const [includeUnpublished, setIncludeUnpublished] = useState(false);

  // ---- 结果 ----
  const [result, setResult] = useState<SearchTestResult | null>(null);
  const [answer, setAnswer] = useState<RagAnswer | null>(null);
  const [answerError, setAnswerError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [answering, setAnswering] = useState(false);

  // ---- 存评测用例 ----
  const [saveOpen, setSaveOpen] = useState(false);
  const [expectedAnswer, setExpectedAnswer] = useState("");
  const [mustHitIds, setMustHitIds] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  // ---- 已保存用例 ----
  const [cases, setCases] = useState<EvalCase[]>([]);
  const [casesLoading, setCasesLoading] = useState(false);
  const [casesError, setCasesError] = useState<string | null>(null);

  // 资料集选项（多选限定召回范围；空 = 全库）
  useEffect(() => {
    const controller = new AbortController();
    api
      .get<Paginated<RagDocument>>("/api/rag/documents", { limit: 100 }, { signal: controller.signal })
      .then((res) => {
        if (!controller.signal.aborted) setDocuments(res.items);
      })
      .catch(() => {
        /* 资料集选项加载失败时仍可全库测试 */
      });
    return () => controller.abort();
  }, []);

  /** Load persisted cases only when their tab is opened; the console remains usable if this auxiliary API is unavailable. */
  const loadCases = useCallback(async (signal?: AbortSignal) => {
    setCasesLoading(true);
    setCasesError(null);
    try {
      const res = await api.get<Paginated<EvalCase>>("/api/rag/eval-cases", { limit: 100, offset: 0 }, { signal });
      if (signal?.aborted) return;
      setCases(res.items);
    } catch (err) {
      if (!signal?.aborted) setCasesError(errText(err, "已保存用例加载失败"));
    } finally {
      if (!signal?.aborted) setCasesLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab !== "saved") return undefined;
    const controller = new AbortController();
    void loadCases(controller.signal);
    return () => controller.abort();
  }, [activeTab, loadCases]);

  const buildFilters = () => ({
    data_type: dataType || null,
    published_only: !includeUnpublished,
    document_ids: docIds.length > 0 ? docIds : null,
  });

  /** 生成回答：与学生端同一合成路径；失败（如邮箱未验证）如实展示 */
  const runAnswer = async (q: string) => {
    setAnswering(true);
    setAnswerError(null);
    try {
      const res = await api.post<RagAnswer>("/api/rag/query", {
        question: q,
        data_type: dataType || null,
        published_only: !includeUnpublished,
        document_ids: docIds.length > 0 ? docIds : null,
      });
      setAnswer(res);
    } catch (err) {
      setAnswer(null);
      setAnswerError(errText(err, "回答生成失败"));
    } finally {
      setAnswering(false);
    }
  };

  const run = async () => {
    const q = question.trim();
    if (!q) {
      toast.error("请输入测试问题");
      return;
    }
    const k = topK.trim() ? Number(topK) : null;
    if (k !== null && (!Number.isInteger(k) || k < 1 || k > 20)) {
      toast.error("TopK 需为 1-20 的整数");
      return;
    }
    setRunning(true);
    setResult(null);
    setAnswer(null);
    setAnswerError(null);
    try {
      const res = await api.post<SearchTestResult>("/api/rag/search-test", {
        query: q,
        filters: buildFilters(),
        top_k: k,
      });
      setResult(res);
      // 测试台联动：召回完成后用同一问题生成回答草稿，验证端到端效果
      void runAnswer(q);
    } catch (err) {
      toast.error(errText(err, "召回测试失败"));
    } finally {
      setRunning(false);
    }
  };

  /** 打开存用例弹窗：必须命中文档用本次命中去重预填（可再勾选调整） */
  const openSaveCase = () => {
    if (!result) return;
    const hitDocIds = [...new Set(result.reranked_results.map((h) => h.document_id))];
    setMustHitIds(hitDocIds);
    setExpectedAnswer("");
    setSaveOpen(true);
  };

  const saveCase = async () => {
    setSaving(true);
    try {
      // Keep the optional TopK in the persisted filter snapshot so loading a case restores
      // the same retrieval shape instead of silently falling back to the system default.
      const filters = {
        ...buildFilters(),
        ...(topK.trim() ? { top_k: Number(topK) } : {}),
      };
      await api.post("/api/rag/eval-cases", {
        question: question.trim(),
        expected_answer: expectedAnswer.trim() || null,
        must_hit_document_ids: mustHitIds,
        must_hit_chunk_ids: [],
        filters,
      });
      toast.success("已保存为评测用例");
      setSaveOpen(false);
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setSaving(false);
    }
  };

  /** Restore a saved case into the editable console without pretending it has been executed. */
  const loadCase = (caseItem: EvalCase) => {
    const filters = caseItem.filters ?? {};
    const savedDocumentIds = Array.isArray(filters.document_ids)
      ? filters.document_ids.filter((value): value is string => typeof value === "string")
      : caseItem.must_hit_document_ids;
    const savedTopK =
      typeof filters.top_k === "number" || typeof filters.top_k === "string"
        ? String(filters.top_k)
        : "";
    setQuestion(caseItem.question);
    setExpectedAnswer(caseItem.expected_answer ?? "");
    setMustHitIds(caseItem.must_hit_document_ids);
    setDataType(typeof filters.data_type === "string" ? filters.data_type : "");
    setDocIds(savedDocumentIds);
    setIncludeUnpublished(filters.published_only === false);
    setTopK(savedTopK);
    setResult(null);
    setAnswer(null);
    setAnswerError(null);
    setActiveTab("console");
    toast.success("已加载用例，请运行召回测试");
  };

  const hitDocTitle = (docId: string) =>
    documents.find((d) => d.id === docId)?.title ??
    result?.reranked_results.find((h) => h.document_id === docId)?.title ??
    `${docId.slice(0, 8)}…`;

  return (
    <div>
      <PageHeader
        title="召回测试台"
        sub="对比原始召回与重排结果、验证回答生成与拒答行为，可把测试问题沉淀为评测用例"
      />

      <Tabs
        tabs={[
          { key: "console", label: "测试台" },
          { key: "saved", label: "已保存用例" },
        ]}
        active={activeTab}
        onChange={(key) => setActiveTab(key as SearchTestTab)}
      />

      {activeTab === "console" ? (
        <>
          {/* 查询输入（PRD-03 §10） */}
          <Card title="查询输入" className="mb-4">
        <Field label="问题" required>
          <Textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="例如：语音标注中情感标签的判定规则是什么？"
          />
        </Field>
        <div className="grid grid-cols-2">
          <Field label="数据类型">
            <Select
              value={dataType}
              onChange={(e) => setDataType(e.target.value)}
              options={[...DATA_TYPE_OPTIONS]}
              placeholder="不限数据类型"
            />
          </Field>
          <Field label="TopK" hint="留空使用系统默认（RAG 参数 top_k）">
            <Input value={topK} onChange={(e) => setTopK(e.target.value)} placeholder="例如：5" inputMode="numeric" />
          </Field>
          <Field label="召回范围" hint="仅教师/管理员可勾选含未发布（学生端强制仅已发布）">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={includeUnpublished}
                onChange={(e) => setIncludeUnpublished(e.target.checked)}
              />
              包含未发布资料（预览用）
            </label>
          </Field>
        </div>
        <Field label={`资料集（已选 ${docIds.length}，不选为全库）`}>
          <RagDocumentMultiSelect
            label="召回资料集"
            documents={documents}
            value={docIds}
            onChange={setDocIds}
          />
        </Field>
        <Button size="lg" loading={running} onClick={() => void run()}>
          运行召回测试
        </Button>
          </Card>

          {result ? (
            <>
          {/* 阈值/重排提示（PRD-06 §4.4：低于阈值学生端拒答） */}
          {result.below_threshold ? (
            <p className="form-alert form-alert-error" role="alert">
              全部命中低于召回阈值：学生端将拒答或只给通用学习建议，不会生成专业结论。
            </p>
          ) : null}
          {result.notice ? <p className="form-alert form-alert-success">{result.notice}</p> : null}

          {/* 双列对比（§10 验收：支持查看原始召回和重排后的顺序） */}
          <div className="grid grid-cols-2">
            <Card title={`原始召回（${result.vector_results.length}）`}>
              {result.vector_results.length === 0 ? (
                <p className="text-sm text-secondary">无召回结果</p>
              ) : (
                result.vector_results.map((hit) => (
                  <HitCard key={`v-${hit.chunk_id}`} hit={hit} showRerank={false} />
                ))
              )}
            </Card>
            <Card
              title={`重排后（${result.reranked_results.length}）`}
              actions={result.rerank_note ? <span className="text-xs text-muted">{result.rerank_note}</span> : undefined}
            >
              {result.reranked_results.length === 0 ? (
                <p className="text-sm text-secondary">无召回结果</p>
              ) : (
                result.reranked_results.map((hit) => (
                  <HitCard key={`r-${hit.chunk_id}`} hit={hit} showRerank />
                ))
              )}
            </Card>
          </div>

          {/* 生成回答（§10：答案草稿/引用/不确定性提示/重新生成） */}
          <Card
            title="生成回答（与学生端同一路径）"
            className="mt-4"
            actions={
              <Button
                size="sm"
                variant="secondary"
                loading={answering}
                onClick={() => void runAnswer(question.trim())}
              >
                重新生成
              </Button>
            }
          >
            {answering ? <p className="text-sm text-secondary">正在生成回答…</p> : null}
            {answerError ? (
              <p className="text-sm text-danger">无法生成回答：{answerError}</p>
            ) : null}
            {answer ? (
              <div>
                {answer.refused ? (
                  <p className="form-alert form-alert-error" role="alert">
                    已拒答：知识库暂无可靠依据（AC6：不编造专业结论）。
                  </p>
                ) : null}
                <p className="text-sm mb-3" style={{ whiteSpace: "pre-wrap" }}>{answer.answer}</p>
                {answer.notes.length > 0 ? (
                  <div className="mb-3">
                    {answer.notes.map((note) => (
                      <p key={note} className="text-xs text-muted">不确定性提示：{note}</p>
                    ))}
                  </div>
                ) : null}
                {answer.notice ? <p className="text-xs text-muted mb-3">{answer.notice}</p> : null}
                {answer.citations.length > 0 ? (
                  <div>
                    <p className="text-sm mb-2"><strong>引用来源</strong></p>
                    {answer.citations.map((citation, i) => (
                      <CitationCard key={citation.document_id} citation={citation} index={i + 1} />
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </Card>

          {/* 诊断信息（§10） */}
          <Card title="诊断信息" className="mt-4">
            <div className="grid grid-cols-3">
              <p className="text-sm">检索耗时：<strong>{result.diagnostics.latency_ms}ms</strong></p>
              <p className="text-sm">向量模型：<strong>{result.diagnostics.embedding_model ?? "—"}</strong></p>
              <p className="text-sm">重排模型：<strong>{result.diagnostics.rerank_model ?? "未启用"}</strong></p>
              <p className="text-sm">Prompt 模板版本：<strong>{result.diagnostics.prompt_template_version}</strong></p>
              <p className="text-sm" style={{ gridColumn: "span 2" }}>
                过滤条件：
                {[
                  `数据类型=${result.diagnostics.filters.data_type ?? "不限"}`,
                  `仅已发布=${result.diagnostics.filters.published_only ? "是" : "否"}`,
                  `资料集=${Array.isArray(result.diagnostics.filters.document_ids) ? (result.diagnostics.filters.document_ids as string[]).length : "全库"}`,
                ].join("；")}
              </p>
            </div>
          </Card>

          <div className="mt-4">
            <Button variant="secondary" onClick={openSaveCase}>
              保存为评测用例
            </Button>
          </div>
            </>
          ) : null}
        </>
      ) : (
        <SavedCasesPanel
          cases={cases}
          loading={casesLoading}
          error={casesError}
          onRetry={() => void loadCases()}
          onLoad={loadCase}
        />
      )}

      {/* 存评测用例弹窗 */}
      <Modal
        open={saveOpen}
        title="保存为评测用例"
        onClose={() => setSaveOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setSaveOpen(false)}>
              取消
            </Button>
            <Button loading={saving} onClick={() => void saveCase()}>
              保存用例
            </Button>
          </>
        }
      >
        <Field label="问题">
          <Input value={question} readOnly disabled />
        </Field>
        <Field label="标准答案（可选，用于人工比对）">
          <Textarea
            value={expectedAnswer}
            onChange={(e) => setExpectedAnswer(e.target.value)}
            placeholder="期望回答的要点…"
          />
        </Field>
        <Field label="必须命中文档（按本次召回预填，可调整）">
          {result && [...new Set(result.reranked_results.map((h) => h.document_id))].length === 0 ? (
            <p className="text-sm text-muted">本次无命中，保存后该用例将用于验证拒答行为</p>
          ) : (
            <ul>
              {[...new Set(result?.reranked_results.map((h) => h.document_id) ?? [])].map((docId) => (
                <li key={docId}>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={mustHitIds.includes(docId)}
                      onChange={() =>
                        setMustHitIds((prev) =>
                          prev.includes(docId)
                            ? prev.filter((v) => v !== docId)
                            : [...prev, docId],
                        )
                      }
                    />
                    {hitDocTitle(docId)}
                  </label>
                </li>
              ))}
            </ul>
          )}
        </Field>
      </Modal>
    </div>
  );
}
