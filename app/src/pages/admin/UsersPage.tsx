/**
 * 用户与权限（/admin/users）——用户列表 + 角色/状态/密码管理（PRD-04 §5）。
 *
 * 关键决策（为什么）：
 * - 自我禁用/自我降权不前端拦截：后端 SELF_OPERATION_FORBIDDEN 中文错误
 *   直接 toast（前后端单一事实来源，且列表页不假设当前登录人是谁）。
 * - 临时密码只展示一次（后端响应即唯一出口，不落任何状态持久层）：
 *   弹窗关闭即不可再见，文案明确提醒管理员转达用户。
 * - 禁用即终止会话是后端行为（_revoke_user_sessions 吊销两张会话表），
 *   确认框文案如实说明，避免管理员以为只是"标记"。
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { AdminResetPasswordResponse, AdminUser, Paginated } from "../../api/types";
import {
  Button,
  Card,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorState,
  Field,
  Modal,
  PageHeader,
  Pagination,
  SearchInput,
  Select,
  Tag,
  useToast,
  type Column,
} from "../../components";
import { errText, fmtTime, ROLE_LABELS, ROLE_OPTIONS } from "./adminShared";

const LIMIT = 20;

/** 角色标签（权限语义重，用不同色区分管理角色与普通角色） */
function RoleTag({ role }: { role: string }) {
  const admin = role === "system_admin" || role === "content_admin";
  return <span className={`badge ${admin ? "badge-primary" : "badge-neutral"}`}>{ROLE_LABELS[role] ?? role}</span>;
}

export default function UsersPage() {
  const toast = useToast();
  const [items, setItems] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [role, setRole] = useState("");
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 编辑角色弹窗
  const [roleTarget, setRoleTarget] = useState<AdminUser | null>(null);
  const [roleDraft, setRoleDraft] = useState("");
  const [roleSaving, setRoleSaving] = useState(false);
  // 禁用/启用确认
  const [statusTarget, setStatusTarget] = useState<AdminUser | null>(null);
  // 重置密码：确认 → 结果弹窗（临时密码仅此一次）
  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
  const [tempPassword, setTempPassword] = useState<{ name: string; password: string } | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<Paginated<AdminUser>>("/api/admin/users", {
        role: role || undefined,
        q: q.trim() || undefined,
        limit: LIMIT,
        offset,
      }, { signal });
      if (signal?.aborted) return;
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      if (!signal?.aborted) setError(errText(err, "用户列表加载失败"));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [role, q, offset]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const openRoleModal = (user: AdminUser) => {
    setRoleTarget(user);
    setRoleDraft(user.role);
  };

  /** 编辑角色：PATCH role；权限变更写审计（后端 admin.py patch_user） */
  const saveRole = async () => {
    if (!roleTarget || roleDraft === roleTarget.role) {
      setRoleTarget(null);
      return;
    }
    setRoleSaving(true);
    try {
      await api.patch(`/api/admin/users/${roleTarget.id}`, { role: roleDraft });
      toast.success(`已将 ${roleTarget.name} 的角色调整为${ROLE_LABELS[roleDraft] ?? roleDraft}`);
      setRoleTarget(null);
      await load();
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setRoleSaving(false);
    }
  };

  /** 禁用/启用：PATCH status；自我禁用由后端 400 拦截并透传话术 */
  const toggleStatus = async () => {
    if (!statusTarget) return;
    const next = statusTarget.status === "active" ? "disabled" : "active";
    try {
      await api.patch(`/api/admin/users/${statusTarget.id}`, { status: next });
      toast.success(next === "disabled" ? `已禁用 ${statusTarget.name}（其会话已终止）` : `已启用 ${statusTarget.name}`);
      setStatusTarget(null);
      await load();
    } catch (err) {
      toast.error(errText(err));
      setStatusTarget(null);
    }
  };

  /** 重置密码：临时密码仅此一次展示，关闭弹窗即不可再见 */
  const doResetPassword = async () => {
    if (!resetTarget) return;
    try {
      const res = await api.post<AdminResetPasswordResponse>(
        `/api/admin/users/${resetTarget.id}/reset-password`,
      );
      setTempPassword({ name: resetTarget.name, password: res.temporary_password });
      setResetTarget(null);
    } catch (err) {
      toast.error(errText(err));
      setResetTarget(null);
    }
  };

  const copyTempPassword = async () => {
    if (!tempPassword) return;
    try {
      await navigator.clipboard.writeText(tempPassword.password);
      toast.success("已复制临时密码");
    } catch {
      toast.info("复制失败，请手动选择密码复制");
    }
  };

  const columns: Column<AdminUser>[] = [
    { key: "name", title: "姓名", render: (u) => <strong>{u.name}</strong> },
    { key: "email", title: "邮箱", render: (u) => <span className="text-sm">{u.email}</span> },
    { key: "role", title: "角色", width: "110px", render: (u) => <RoleTag role={u.role} /> },
    {
      key: "status",
      title: "状态",
      width: "90px",
      render: (u) =>
        u.status === "active" ? (
          <span className="badge badge-success">启用</span>
        ) : (
          <span className="badge badge-danger">已禁用</span>
        ),
    },
    {
      key: "email_verified",
      title: "邮箱验证",
      width: "90px",
      render: (u) =>
        u.email_verified ? <span className="text-success">✓ 已验证</span> : <span className="text-muted">✗ 未验证</span>,
    },
    {
      key: "created_at",
      title: "注册时间",
      width: "140px",
      render: (u) => <span className="text-sm text-secondary">{fmtTime(u.created_at)}</span>,
    },
    {
      key: "actions",
      title: "操作",
      width: "230px",
      render: (u) => (
        <div className="flex gap-1" style={{ flexWrap: "wrap" }}>
          <Button size="sm" variant="secondary" onClick={() => openRoleModal(u)}>
            编辑角色
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setStatusTarget(u)}>
            {u.status === "active" ? "禁用" : "启用"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setResetTarget(u)}>
            重置密码
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="用户与权限"
        sub="角色调整、账号禁用与密码重置；权限变更均记录审计日志"
      />

      <div className="card card-padded mb-4">
        <div className="flex gap-3" style={{ flexWrap: "wrap" }}>
          <div style={{ width: 220 }}>
            <Select
              aria-label="角色筛选"
              value={role}
              onChange={(e) => {
                setRole(e.target.value);
                setOffset(0);
              }}
              options={[...ROLE_OPTIONS]}
              placeholder="全部角色"
            />
          </div>
          <div style={{ width: 280 }}>
            <SearchInput
              value={q}
              // 防抖依赖 value 与内部态的差异（见 DocumentsPage 同处注释）
              onChange={() => {}}
              onSearch={(v) => {
                setQ(v);
                setOffset(0);
              }}
              placeholder="搜索姓名或邮箱…"
            />
          </div>
        </div>
      </div>

      {error ? (
        <ErrorState message={error} onRetry={() => void load()} />
      ) : (
        <Card padded={false}>
          <DataTable
            ariaLabel="用户列表"
            columns={columns}
            rows={items}
            loading={loading}
            empty={<EmptyState title="没有匹配的用户" hint="调整角色筛选或搜索关键词" />}
          />
          <div style={{ padding: "0 var(--space-5) var(--space-3)" }}>
            <Pagination offset={offset} limit={LIMIT} total={total} onChange={setOffset} />
          </div>
        </Card>
      )}

      {/* 编辑角色弹窗 */}
      <Modal
        open={roleTarget !== null}
        title={`编辑角色：${roleTarget?.name ?? ""}`}
        onClose={() => setRoleTarget(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setRoleTarget(null)}>
              取消
            </Button>
            <Button loading={roleSaving} onClick={() => void saveRole()}>
              保存角色
            </Button>
          </>
        }
      >
        <Field label="角色" hint="权限变更将记录审计日志">
          <Select
            value={roleDraft}
            onChange={(e) => setRoleDraft(e.target.value)}
            options={[...ROLE_OPTIONS]}
          />
        </Field>
        <p className="text-xs text-muted">
          学生：仅学生端；教师：+班级与 RAG 上传审核；内容管理员：+RAG 管理端全部；系统管理员：+系统管理端。
        </p>
      </Modal>

      {/* 禁用/启用确认 */}
      <ConfirmDialog
        open={statusTarget !== null}
        title={statusTarget?.status === "active" ? "禁用账号" : "启用账号"}
        danger={statusTarget?.status === "active"}
        confirmText={statusTarget?.status === "active" ? "确认禁用" : "确认启用"}
        description={
          statusTarget?.status === "active"
            ? `禁用 ${statusTarget?.name}（${statusTarget?.email}）将立即终止其全部会话，该用户无法登录与使用 Agent/RAG，直到重新启用。`
            : `启用后 ${statusTarget?.name} 可重新登录系统。`
        }
        onConfirm={toggleStatus}
        onCancel={() => setStatusTarget(null)}
      />

      {/* 重置密码确认 */}
      <ConfirmDialog
        open={resetTarget !== null}
        title="重置密码"
        danger
        confirmText="确认重置"
        description={`将为 ${resetTarget?.name}（${resetTarget?.email}）生成临时密码并终止其全部会话；临时密码仅在下一步展示一次。`}
        onConfirm={doResetPassword}
        onCancel={() => setResetTarget(null)}
      />

      {/* 临时密码展示（仅此一次，关闭即不可再见） */}
      <Modal
        open={tempPassword !== null}
        title="临时密码（仅本次展示）"
        onClose={() => setTempPassword(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => void copyTempPassword()}>
              复制密码
            </Button>
            <Button onClick={() => setTempPassword(null)}>我已转达，关闭</Button>
          </>
        }
      >
        <p className="text-sm mb-3">
          用户 <strong>{tempPassword?.name}</strong> 的临时密码：
        </p>
        <p className="font-mono text-sm mb-3" style={{ padding: "var(--space-3)", background: "var(--color-surface-muted)", borderRadius: "var(--radius-md)", wordBreak: "break-all" }}>
          {tempPassword?.password}
        </p>
        <p className="text-xs text-muted">
          请立即转达用户，并提醒其登录后马上修改密码；关闭本窗口后系统不再展示该密码。
        </p>
      </Modal>
    </div>
  );
}
