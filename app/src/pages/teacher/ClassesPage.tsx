/**
 * 班级管理列表（/teacher/classes，PRD-02 §4）。
 *
 * 实现要点（为什么）：
 * - 列表数据即 GET /api/teacher/classes（后端按 class_teachers 隔离，验收
 *   "教师只能查看自己班级"由服务端强制，前端不做二次过滤）。
 * - "学习状态"列后端没有独立字段：由真实字段推导（有最近任务=教学进行中；
 *   有学生=待发布任务；否则=待招生），比硬编码"正常"诚实。
 * - DataTable（F0 组件）不支持整行点击，改为班级名称渲染为链接 + 操作列
 *   "管理"入口，导航目标一致（/teacher/classes/:id）。
 * - 新建班级采用两步弹窗：提交后直接在同弹窗展示邀请码（后端只在创建响应
 *   里返回一次最醒目），避免教师创建完还要点进详情找码。
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { ClassInfo } from "../../api/types";
import {
  Button,
  Card,
  DataTable,
  ErrorState,
  Field,
  Input,
  Modal,
  PageHeader,
  useToast,
  type Column,
} from "../../components";
import { errMsg } from "./utils";

/** 学习状态推导（见模块注释）：全部由行内真实字段得出 */
function learningStatusOf(row: ClassInfo): { label: string; cls: string } {
  if (row.recent_task_title) return { label: "教学进行中", cls: "badge badge-primary" };
  if (row.student_count > 0) return { label: "待发布任务", cls: "badge badge-neutral" };
  return { label: "待招生", cls: "badge badge-neutral" };
}

export default function ClassesPage() {
  const toast = useToast();
  const [items, setItems] = useState<ClassInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // ---- 新建班级弹窗状态：created 非空时进入"邀请码展示"第二步 ----
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<{ name: string; invite_code: string } | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<{ items: ClassInfo[] }>("/api/teacher/classes", undefined, {
        signal,
      });
      if (signal?.aborted) return;
      setItems(res.items);
    } catch (err) {
      if (!signal?.aborted) setError(errMsg(err, "班级列表加载失败"));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const openModal = () => {
    setName("");
    setNameError(null);
    setCreated(null);
    setModalOpen(true);
  };

  const createClass = async () => {
    if (!name.trim()) {
      setNameError("班级名称不能为空");
      return;
    }
    setCreating(true);
    setNameError(null);
    try {
      const res = await api.post<{ id: string; name: string; invite_code: string }>(
        "/api/teacher/classes",
        { name: name.trim() },
      );
      // 进入第二步：展示邀请码（列表在关闭弹窗时统一刷新）
      setCreated({ name: res.name, invite_code: res.invite_code });
    } catch (err) {
      setNameError(errMsg(err));
    } finally {
      setCreating(false);
    }
  };

  const copyInviteCode = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code);
      toast.success("邀请码已复制");
    } catch {
      // 剪贴板权限被拒时给出可执行提示（码本身就在页面上，手动复制即可）
      toast.error("复制失败，请手动选中邀请码复制");
    }
  };

  const closeModal = () => {
    setModalOpen(false);
    if (created) void load(); // 有新建成果才刷新列表，避免无谓请求
  };

  const columns: Column<ClassInfo>[] = [
    {
      key: "name",
      title: "班级名称",
      render: (row) => <Link to={`/teacher/classes/${row.id}`}>{row.name}</Link>,
    },
    { key: "student_count", title: "学生人数", width: "100px" },
    {
      key: "recent_task_title",
      title: "最近任务",
      render: (row) => row.recent_task_title ?? <span className="text-muted">—</span>,
    },
    {
      key: "status",
      title: "学习状态",
      width: "120px",
      render: (row) => {
        const s = learningStatusOf(row);
        return <span className={s.cls}>{s.label}</span>;
      },
    },
    {
      key: "actions",
      title: "操作",
      width: "90px",
      render: (row) => <Link to={`/teacher/classes/${row.id}`}>管理</Link>,
    },
  ];

  return (
    <div className="teacher-workbench-page teacher-classes-page">
      <PageHeader
        title="班级管理"
        sub="管理你带的班级与学生，邀请码分享给学生即可加入"
        actions={<Button onClick={openModal}>新建班级</Button>}
      />

      {error && !items ? (
        <ErrorState message={error} onRetry={load} />
      ) : (
        <Card padded={false} className="teacher-table-surface">
          {/* The card supplies the page surface; the table drops its own border to avoid a double frame. */}
          <DataTable
            ariaLabel="班级列表"
            columns={columns}
            rows={items ?? []}
            loading={loading && !items}
            empty="还没有班级，点击右上角「新建班级」开始"
            wrapperClassName="table-wrap-borderless"
          />
        </Card>
      )}

      <Modal
        open={modalOpen}
        title={created ? "班级已创建" : "新建班级"}
        onClose={closeModal}
        footer={
          created ? (
            <Button onClick={closeModal}>完成</Button>
          ) : (
            <>
              <Button variant="ghost" onClick={closeModal} disabled={creating}>
                取消
              </Button>
              <Button onClick={createClass} loading={creating}>
                创建
              </Button>
            </>
          )
        }
      >
        {created ? (
          // 第二步：邀请码醒目展示（创建响应是唯一最及时的展示时机）
          <div className="flex flex-col items-center gap-3" style={{ textAlign: "center" }}>
            <p>班级「{created.name}」创建成功，邀请码：</p>
            <div
              className="font-mono"
              style={{
                fontSize: "var(--font-size-2xl)",
                fontWeight: 700,
                letterSpacing: 2,
                padding: "var(--space-3) var(--space-6)",
                background: "var(--color-primary-soft)",
                border: "1px solid var(--color-primary-border)",
                borderRadius: "var(--radius-md)",
              }}
            >
              {created.invite_code}
            </div>
            <Button variant="secondary" onClick={() => copyInviteCode(created.invite_code)}>
              复制邀请码
            </Button>
            <p className="text-sm text-secondary">
              分享给学生加入：学生登录后可在个人中心输入邀请码进入班级
            </p>
          </div>
        ) : (
          <Field label="班级名称" required error={nameError ?? undefined}>
            <Input
              value={name}
              placeholder="例如：数据标注2301班"
              invalid={!!nameError}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void createClass();
              }}
            />
          </Field>
        )}
      </Modal>
    </div>
  );
}
