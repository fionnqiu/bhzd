/**
 * 审计日志（/admin/audit-logs）——多条件查询 + before/after 变更摘要（PRD-04 §7）。
 *
 * 关键决策（为什么）：
 * - 动作/目标类型下拉是"代码中实际会写入的动作"的策展清单（grep 全后端
 *   audit() 调用点得来），后端没有去重动作查询端点；清单只影响筛选便利，
 *   不筛选时点"全部"即可见所有记录。
 * - 变更摘要渲染 before→after 的关键字段 diff（顶层键值对比），完整 JSON
 *   收进 <details> 展开——表格里塞两段完整 JSON 会让审计页不可用。
 * - 时间筛选用 datetime-local 原生输入，ISO 前缀比较与后端字符串排序口径
 *   兼容（created_at 是 UTC ISO8601，字典序即时间序）。
 * - 审计日志不允许删除（PRD-06 §12.1）：页面只读，caption 明示。
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { AuditLog, Paginated } from "../../api/types";
import {
  Card,
  DataTable,
  EmptyState,
  ErrorState,
  Input,
  PageHeader,
  Pagination,
  Select,
  Tag,
  type Column,
} from "../../components";
import { clamp, errText, fmtTime } from "./adminShared";

const LIMIT = 20;

/** 动作类型筛选清单（后端 audit() 实际调用点汇总；留空 = 全部） */
const ACTION_OPTIONS = [
  "auth.login",
  "auth.login_failed",
  "auth.logout",
  "auth.password_reset",
  "provider.create",
  "provider.update",
  "provider.delete",
  "provider.test",
  "provider.set_role",
  "rag_settings.update",
  "user.update",
  "user.reset_password",
  "rag.upload_document",
  "rag.update_document",
  "rag.delete_document",
  "rag.submit_review",
  "rag.publish_document",
  "rag.reject_document",
  "rag.archive_document",
  "rag.update_chunk",
  "rag.split_chunk",
  "rag.merge_chunks",
  "rag.retry_job",
  "rag.save_eval_case",
  "rag.run_eval",
  "rag.create_ledger",
  "rag.update_ledger",
  "class.join",
].map((v) => ({ value: v, label: v }));

/** 目标类型筛选清单（audit() target_type 实际取值） */
const TARGET_TYPE_OPTIONS = [
  "user",
  "provider",
  "rag_settings",
  "rag_document",
  "rag_chunk",
  "rag_job",
  "eval_case",
  "eval_run",
  "source_ledger",
  "class",
].map((v) => ({ value: v, label: v }));

/** before/after 顶层键值 diff：返回 "键: 前 → 后" 行（值截断防撑爆） */
function diffLines(before: unknown, after: unknown, maxLines = 4): string[] {
  const b = (before ?? {}) as Record<string, unknown>;
  const a = (after ?? {}) as Record<string, unknown>;
  if (typeof b !== "object" || typeof a !== "object" || b === null || a === null) return [];
  const keys = [...new Set([...Object.keys(b), ...Object.keys(a)])];
  const lines: string[] = [];
  for (const key of keys) {
    const bv = b[key];
    const av = a[key];
    if (JSON.stringify(bv) === JSON.stringify(av)) continue;
    const fmt = (v: unknown) =>
      v === undefined ? "—" : clamp(typeof v === "string" ? v : JSON.stringify(v), 40);
    lines.push(`${key}: ${fmt(bv)} → ${fmt(av)}`);
    if (lines.length >= maxLines) break;
  }
  return lines;
}

/** 变更摘要单元格：diff 摘要 + 完整 JSON 折叠 */
function DiffCell({ log }: { log: AuditLog }) {
  if (log.before == null && log.after == null) return <span className="text-muted">—</span>;
  const lines = diffLines(log.before, log.after);
  return (
    <div className="text-xs">
      {lines.length > 0 ? (
        lines.map((line) => (
          <div key={line} className="font-mono" style={{ wordBreak: "break-all" }}>
            {line}
          </div>
        ))
      ) : (
        <span className="text-muted">（无字段级差异）</span>
      )}
      <details className="mt-2">
        <summary className="text-muted" style={{ cursor: "pointer" }}>
          完整 JSON
        </summary>
        <pre
          className="font-mono text-xs mt-2"
          style={{
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
            background: "var(--color-surface-muted)",
            padding: "var(--space-2)",
            borderRadius: "var(--radius-sm)",
            maxHeight: 220,
            overflowY: "auto",
          }}
        >
          {JSON.stringify({ before: log.before, after: log.after }, null, 2)}
        </pre>
      </details>
    </div>
  );
}

export default function AuditLogsPage() {
  const [items, setItems] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [actorId, setActorId] = useState("");
  const [action, setAction] = useState("");
  const [targetType, setTargetType] = useState("");
  const [fromTime, setFromTime] = useState("");
  const [toTime, setToTime] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<Paginated<AuditLog>>("/api/admin/audit-logs", {
        actor_id: actorId.trim() || undefined,
        action: action || undefined,
        target_type: targetType || undefined,
        from: fromTime || undefined,
        to: toTime || undefined,
        limit: LIMIT,
        offset,
      }, { signal });
      if (signal?.aborted) return;
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      if (!signal?.aborted) setError(errText(err, "审计日志加载失败"));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [actorId, action, targetType, fromTime, toTime, offset]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const resetAnd = (fn: () => void) => {
    fn();
    setOffset(0);
  };

  const columns: Column<AuditLog>[] = [
    {
      key: "created_at",
      title: "时间",
      width: "140px",
      render: (log) => <span className="text-sm text-secondary">{fmtTime(log.created_at)}</span>,
    },
    {
      key: "actor",
      title: "操作人",
      width: "140px",
      render: (log) => (
        <div>
          <div className="font-mono text-xs" title={log.actor_id ?? ""}>
            {log.actor_id ? `${log.actor_id.slice(0, 8)}…` : "系统"}
          </div>
          {log.actor_role ? <Tag>{log.actor_role}</Tag> : null}
        </div>
      ),
    },
    {
      key: "action",
      title: "动作",
      width: "170px",
      render: (log) => <span className="font-mono text-xs">{log.action}</span>,
    },
    {
      key: "target",
      title: "目标",
      width: "150px",
      render: (log) =>
        log.target_type ? (
          <div>
            <Tag>{log.target_type}</Tag>
            <div className="font-mono text-xs text-muted" title={log.target_id ?? ""}>
              {log.target_id ? clamp(log.target_id, 12) : ""}
            </div>
          </div>
        ) : (
          <span className="text-muted">—</span>
        ),
    },
    { key: "diff", title: "变更摘要", render: (log) => <DiffCell log={log} /> },
    {
      key: "ip",
      title: "IP",
      width: "110px",
      render: (log) => <span className="font-mono text-xs">{log.ip ?? "—"}</span>,
    },
    {
      key: "ua",
      title: "UserAgent",
      width: "140px",
      render: (log) => (
        <span className="text-xs text-muted" title={log.user_agent ?? ""}>
          {log.user_agent ? clamp(log.user_agent, 30) : "—"}
        </span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="审计日志"
        sub="登录、配置变更、资料发布、权限变更等关键操作全量留痕；审计日志不允许删除"
      />

      {/* 筛选区（PRD-04 §7：操作人/动作/目标/时间） */}
      <div className="card card-padded mb-4">
        <div className="grid grid-cols-3">
          <Input
            aria-label="操作人 ID"
            value={actorId}
            onChange={(e) => resetAnd(() => setActorId(e.target.value))}
            placeholder="操作人 ID（actor_id）"
          />
          <Select
            aria-label="动作类型"
            value={action}
            onChange={(e) => resetAnd(() => setAction(e.target.value))}
            options={ACTION_OPTIONS}
            placeholder="全部动作类型"
          />
          <Select
            aria-label="目标类型"
            value={targetType}
            onChange={(e) => resetAnd(() => setTargetType(e.target.value))}
            options={TARGET_TYPE_OPTIONS}
            placeholder="全部目标类型"
          />
          <Input
            aria-label="起始时间"
            type="datetime-local"
            value={fromTime}
            onChange={(e) => resetAnd(() => setFromTime(e.target.value))}
          />
          <Input
            aria-label="截止时间"
            type="datetime-local"
            value={toTime}
            onChange={(e) => resetAnd(() => setToTime(e.target.value))}
          />
        </div>
      </div>

      {error ? (
        <ErrorState message={error} onRetry={() => void load()} />
      ) : (
        <Card padded={false}>
          <DataTable
            ariaLabel="审计记录"
            columns={columns}
            rows={items}
            loading={loading}
            empty={<EmptyState title="没有匹配的审计记录" hint="调整筛选条件，或先执行一些管理操作" />}
          />
          <div style={{ padding: "0 var(--space-5) var(--space-3)" }}>
            <Pagination offset={offset} limit={LIMIT} total={total} onChange={setOffset} />
          </div>
        </Card>
      )}
      <p className="text-xs text-muted mt-2">审计日志不允许删除（PRD-06 §12.1）；动作清单为系统内置动作的常用子集。</p>
    </div>
  );
}
