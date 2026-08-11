/**
 * 切片编辑器（/rag-admin/documents/:id/chunks）——原文预览 / 切片列表 / 编辑面板（PRD-03 §8）。
 *
 * 关键决策（为什么）：
 * - 保存内容立即重嵌入是后端行为（rag_admin.py _reembed_chunk），页面如实提示
 *   "保存即重建向量"；额外的"保存并重建索引"按钮用于触发文档级 index 阶段，
 *   保证跨切片的索引一致性（PRD-03 §8"保存并重建索引"）。
 * - 未保存修改守卫：切换选中切片前 window.confirm + 页面关闭前 beforeunload，
 *   防止编辑半天被误点丢弃（拆分/合并会重排 chunk_index，丢失修改代价高）。
 * - 关联能力落在 metadata.cap_ids：rag_chunks 没有独立能力列，metadata 是
 *   后端开放的自由字典（ChunkPatchBody.metadata 整体替换），因此保存时用
 *   现有 metadata 合并而不是覆盖，避免丢掉切片的其他元信息。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { Paginated, RagChunk, RagDocument } from "../../api/types";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  PageHeader,
  Pagination,
  Spinner,
  Tag,
  Textarea,
  useToast,
} from "../../components";
import { clamp, errText, safeRagReturnPath } from "./ragShared";

const DEFAULT_LIMIT = 50;

/** 逗号（中英文）分隔输入 → 字符串数组（关键词/能力 id 共用） */
function parseList(input: string): string[] {
  return input
    .split(/[,，]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function ChunkEditorPage() {
  const { id = "" } = useParams();
  const location = useLocation();
  const returnTo = safeRagReturnPath(
    (location.state as { returnTo?: unknown } | null)?.returnTo ??
      new URLSearchParams(location.search).get("returnTo"),
  );
  const toast = useToast();

  const [doc, setDoc] = useState<RagDocument | null>(null);
  const [chunks, setChunks] = useState<RagChunk[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 编辑状态：选中切片 + 三份草稿（内容/关键词/能力）；dirty 驱动未保存守卫
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [contentDraft, setContentDraft] = useState("");
  const [keywordsDraft, setKeywordsDraft] = useState("");
  const [capsDraft, setCapsDraft] = useState("");
  const [mergeChecked, setMergeChecked] = useState<string[]>([]);
  const [splitAt, setSplitAt] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const selected = useMemo(
    () => chunks.find((c) => c.id === selectedId) ?? null,
    [chunks, selectedId],
  );

  /** 用切片当前值重置草稿（选中切换/保存成功后调用） */
  const syncDrafts = useCallback((chunk: RagChunk | null) => {
    setContentDraft(chunk?.content ?? "");
    setKeywordsDraft((chunk?.keywords ?? []).join(", "));
    const caps = chunk?.metadata?.cap_ids;
    setCapsDraft(Array.isArray(caps) ? caps.join(", ") : "");
  }, []);

  const load = useCallback(
    async (keepSelection = false, signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const [docRes, chunkRes] = await Promise.all([
          api.get<{ document: RagDocument }>(`/api/rag/documents/${id}`, undefined, { signal }),
          api.get<Paginated<RagChunk>>(
            `/api/rag/documents/${id}/chunks`,
            {
              limit,
              offset,
            },
            { signal },
          ),
        ]);
        if (signal?.aborted) return;
        setDoc(docRes.document);
        setChunks(chunkRes.items);
        setTotal(chunkRes.total);
        if (!keepSelection) {
          const first = chunkRes.items[0] ?? null;
          setSelectedId(first?.id ?? null);
          syncDrafts(first);
        } else if (selectedId) {
          // 保持选中：用最新内容刷新草稿（若未被自己改脏则交给 dirty 判断）
          syncDrafts(chunkRes.items.find((c) => c.id === selectedId) ?? null);
        }
      } catch (err) {
        if (!signal?.aborted) setError(errText(err, "切片加载失败"));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [id, offset, limit, selectedId, syncDrafts],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(false, controller.signal);
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset, limit]);

  const dirty = useMemo(() => {
    if (!selected) return false;
    return (
      contentDraft !== selected.content ||
      parseList(keywordsDraft).join("") !== selected.keywords.join("") ||
      capsDraft !==
        (Array.isArray(selected.metadata?.cap_ids)
          ? (selected.metadata.cap_ids as string[]).join(", ")
          : "")
    );
  }, [selected, contentDraft, keywordsDraft, capsDraft]);

  // 未保存守卫：关闭/刷新页面前拦截（切换切片在 selectChunk 里单独处理）
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  /** 切换选中切片：有未保存修改时先确认，避免误丢编辑成果 */
  const selectChunk = (chunk: RagChunk) => {
    if (chunk.id === selectedId) return;
    if (dirty && !window.confirm("当前切片有未保存修改，切换将丢弃，继续吗？")) return;
    setSelectedId(chunk.id);
    syncDrafts(chunk);
    setSplitAt("");
  };

  /** 保存选中切片的修改（内容/关键词/能力），只提交变化字段 */
  const saveChunk = async (): Promise<boolean> => {
    if (!selected || !dirty) return true;
    // 空内容前端先拦：后端 422 同样拒绝，但本地提示更靠近操作点
    if (!contentDraft.trim()) {
      toast.error("切片内容不能为空");
      return false;
    }
    const body: Record<string, unknown> = {};
    if (contentDraft.trim() && contentDraft !== selected.content) {
      body.content = contentDraft;
    }
    const keywords = parseList(keywordsDraft);
    if (keywords.join("") !== selected.keywords.join("")) body.keywords = keywords;
    const capIds = parseList(capsDraft);
    const oldCaps = Array.isArray(selected.metadata?.cap_ids)
      ? (selected.metadata.cap_ids as string[])
      : [];
    if (capIds.join("") !== oldCaps.join("")) {
      // metadata 整体替换语义：合并现有键，只覆盖 cap_ids
      body.metadata = { ...selected.metadata, cap_ids: capIds };
    }
    if (Object.keys(body).length === 0) return true;
    setBusy("save");
    try {
      await api.patch(`/api/rag/chunks/${selected.id}`, body);
      toast.success("切片已保存（内容变更已自动重新嵌入）");
      await load(true);
      return true;
    } catch (err) {
      toast.error(errText(err));
      return false;
    } finally {
      setBusy(null);
    }
  };

  /** 拆分：留空由后端取最靠近中点的句读位置（保证两半都是完整句子） */
  const doSplit = async () => {
    if (!selected) return;
    const at = splitAt.trim() ? Number(splitAt) : undefined;
    if (at !== undefined && (!Number.isInteger(at) || at <= 0 || at >= selected.content.length)) {
      toast.error(`拆分位置需为 1 到 ${selected.content.length - 1} 之间的整数`);
      return;
    }
    setBusy("split");
    try {
      await api.post(`/api/rag/chunks/${selected.id}/split`, at === undefined ? {} : { at });
      toast.success("已拆分为两个切片");
      setSplitAt("");
      await load(true);
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setBusy(null);
    }
  };

  /** 合并：≥2 个勾选切片，后端按 chunk_index 顺序拼接进首个切片 */
  const doMerge = async () => {
    if (mergeChecked.length < 2) return;
    setBusy("merge");
    try {
      const ordered = chunks
        .filter((c) => mergeChecked.includes(c.id))
        .sort((a, b) => a.chunk_index - b.chunk_index)
        .map((c) => c.id);
      const res = await api.post<{ chunk: RagChunk }>("/api/rag/chunks/merge", {
        chunk_ids: ordered,
      });
      toast.success("已合并所选切片");
      setMergeChecked([]);
      // 先刷新列表再切换选中：合并会删除其余切片并重排序号，
      // 草稿必须以合并后 keeper 的最新 DTO 为准，不能沿用旧选中切片
      await load(true);
      setSelectedId(res.chunk.id);
      syncDrafts(res.chunk);
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setBusy(null);
    }
  };

  /** 保存并重建索引：先落切片修改，再跑文档级 index 阶段（PRD-03 §8） */
  const saveAndReindex = async () => {
    const saved = await saveChunk();
    if (!saved) return;
    setBusy("reindex");
    try {
      await api.post(`/api/rag/documents/${id}/index`);
      toast.success("已保存并重建索引");
      await load(true);
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setBusy(null);
    }
  };

  const toggleMerge = (chunkId: string) => {
    setMergeChecked((prev) =>
      prev.includes(chunkId) ? prev.filter((v) => v !== chunkId) : [...prev, chunkId],
    );
  };

  if (error) return <ErrorState message={error} onRetry={() => void load()} />;

  return (
    <div>
      <PageHeader
        title={`切片编辑器${doc ? `：${doc.title}` : ""}`}
        sub="修改内容保存后立即重新嵌入；拆分/合并会重排切片序号"
        actions={
          <Link
            to={`/rag-admin/documents/${id}?returnTo=${encodeURIComponent(returnTo)}`}
            state={{ returnTo }}
            className="btn btn-ghost"
          >
            ← 返回资料详情
          </Link>
        }
      />
      {loading && chunks.length === 0 ? (
        <div className="loading-block">
          <Spinner large /> 正在加载切片…
        </div>
      ) : chunks.length === 0 ? (
        <EmptyState
          title="暂无切片"
          hint="资料尚未完成解析切片，请先在资料详情页触发解析"
          action={
            <Link
              to={`/rag-admin/documents/${id}?returnTo=${encodeURIComponent(returnTo)}`}
              state={{ returnTo }}
              className="btn btn-primary"
            >
              前往资料详情
            </Link>
          }
        />
      ) : (
        <>
          {/* The editor has three distinct working surfaces. Its column policy
              lives in the shared operations CSS so narrow management screens
              can reflow without JSX pinning them to an unusable three-column grid. */}
          <div className="rag-chunk-editor-layout">
            {/* 左：原文预览（当前页切片按序拼接，只读） */}
            <Card title="原文预览（只读）">
              <div style={{ maxHeight: "70vh", overflowY: "auto" }}>
                {chunks.map((chunk) => (
                  <div
                    key={chunk.id}
                    className="mb-3"
                    style={{
                      padding: "var(--space-2)",
                      borderRadius: "var(--radius-md)",
                      background:
                        chunk.id === selectedId ? "var(--color-primary-soft)" : "transparent",
                    }}
                  >
                    {chunk.section_title ? (
                      <p className="text-sm mb-2">
                        <strong>{chunk.section_title}</strong>
                      </p>
                    ) : null}
                    <p className="text-sm text-secondary" style={{ whiteSpace: "pre-wrap" }}>
                      {chunk.content}
                    </p>
                  </div>
                ))}
              </div>
            </Card>

            {/* 中：切片列表（勾选用于合并；点击载入编辑面板） */}
            <Card title={`切片列表（共 ${total} 条）`}>
              <div style={{ maxHeight: "70vh", overflowY: "auto" }}>
                {chunks.map((chunk) => (
                  <div
                    key={chunk.id}
                    className="mb-3"
                    style={{
                      border: "1px solid var(--color-border)",
                      borderRadius: "var(--radius-md)",
                      padding: "var(--space-3)",
                      cursor: "pointer",
                      borderColor: chunk.id === selectedId ? "var(--color-primary)" : undefined,
                    }}
                    onClick={() => selectChunk(chunk)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") selectChunk(chunk);
                    }}
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <input
                        type="checkbox"
                        aria-label={`选择切片 #${chunk.chunk_index} 用于合并`}
                        checked={mergeChecked.includes(chunk.id)}
                        onClick={(e) => e.stopPropagation()}
                        onChange={() => toggleMerge(chunk.id)}
                      />
                      <Tag>#{chunk.chunk_index}</Tag>
                      {chunk.section_title ? (
                        <span className="text-sm">
                          <strong>{chunk.section_title}</strong>
                        </span>
                      ) : null}
                      <span className="text-xs text-muted">
                        {chunk.page_start != null
                          ? chunk.page_end != null && chunk.page_end !== chunk.page_start
                            ? `第 ${chunk.page_start}-${chunk.page_end} 页`
                            : `第 ${chunk.page_start} 页`
                          : "段落"}
                        {" · "}
                        {chunk.token_count} tokens
                      </span>
                    </div>
                    <p className="text-sm text-secondary">{clamp(chunk.content, 100)}</p>
                    {chunk.keywords.length > 0 ? (
                      <div className="flex gap-1 mt-2" style={{ flexWrap: "wrap" }}>
                        {chunk.keywords.map((kw) => (
                          <Tag key={kw}>{kw}</Tag>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
              <div className="mt-3">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={mergeChecked.length < 2}
                  loading={busy === "merge"}
                  onClick={() => void doMerge()}
                >
                  合并所选（{mergeChecked.length}）
                </Button>
              </div>
            </Card>

            {/* 右：编辑面板 */}
            <Card title={selected ? `编辑切片 #${selected.chunk_index}` : "编辑面板"}>
              {selected ? (
                <>
                  <Field label="切片内容" hint="保存后自动重新嵌入（重算向量与 token 数）">
                    <Textarea
                      value={contentDraft}
                      onChange={(e) => setContentDraft(e.target.value)}
                      style={{ minHeight: 160 }}
                    />
                  </Field>
                  <Field label="关键词（逗号分隔）">
                    <Input
                      value={keywordsDraft}
                      onChange={(e) => setKeywordsDraft(e.target.value)}
                      placeholder="例如：语音标注, 情感标签"
                    />
                  </Field>
                  <Field label="关联能力节点（逗号分隔，存入 metadata.cap_ids）">
                    <Input
                      value={capsDraft}
                      onChange={(e) => setCapsDraft(e.target.value)}
                      placeholder="例如：CAP-AUDIO-001"
                    />
                  </Field>
                  <Field
                    label={`拆分位置（字符偏移 1-${Math.max(1, selected.content.length - 1)}，留空自动取中点附近句读）`}
                  >
                    <div className="flex gap-2">
                      <Input
                        value={splitAt}
                        onChange={(e) => setSplitAt(e.target.value)}
                        placeholder="留空自动"
                        inputMode="numeric"
                      />
                      <Button
                        variant="secondary"
                        loading={busy === "split"}
                        onClick={() => void doSplit()}
                      >
                        拆分
                      </Button>
                    </div>
                  </Field>
                  <div className="flex gap-2 mt-4" style={{ flexWrap: "wrap" }}>
                    <Button
                      variant="secondary"
                      disabled={!dirty}
                      loading={busy === "save"}
                      onClick={() => void saveChunk()}
                    >
                      保存修改{dirty ? " ●" : ""}
                    </Button>
                    <Button loading={busy === "reindex"} onClick={() => void saveAndReindex()}>
                      保存并重建索引
                    </Button>
                  </div>
                  {dirty ? (
                    <p className="text-xs text-muted mt-2">有未保存修改，切换切片前会提示</p>
                  ) : null}
                </>
              ) : (
                <p className="text-sm text-secondary">从中间列表选择一个切片开始编辑</p>
              )}
            </Card>
          </div>
          <Pagination
            offset={offset}
            limit={limit}
            total={total}
            onChange={setOffset}
            onLimitChange={(nextLimit) => {
              setLimit(nextLimit);
              setOffset(0);
            }}
          />
        </>
      )}
    </div>
  );
}
