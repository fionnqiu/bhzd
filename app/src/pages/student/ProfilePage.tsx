/**
 * 个人中心页（PRD-01 §9）。
 *
 * 聚合数据：/api/profile（任务统计/设置）与 /api/tasks（最近任务记录）。
 *
 * 关键决策（为什么）：
 * - 能力地图/诊断摘要/成长记录板块已按产品要求移除，页面聚焦学习任务
 *   与账号设置；对应 mastery/trend 取数与趋势抽屉一并下线。
 * - 姓名可自助修改（PATCH /api/auth/profile，三类账号共用），保存后
 *   refreshSession 让侧边栏账号菜单同步新姓名。
 * - share_diagnostics 默认关闭（PRD-06 待确认项 #2 的产品决策）：关闭时教师
 *   只能看班级聚合统计，开启后才可查看本人诊断详情；开关改动即 PATCH 生效。
 * - 修改密码在站内校验原密码；成功后当前会话保留，其他设备会话由服务端吊销。
 *
 * 类型说明：api/types.ts 由其他任务并行维护，新增 DTO（设置）。
 * 一律页内声明，与后端 profile.py 响应逐字段对齐。
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type {
  JoinClassResponse,
  LeaveClassResponse,
  Paginated,
  ProfileClass,
  ProfileOverview,
  TaskSummary,
} from "../../api/types";
import {
  Button,
  Card,
  DataTable,
  ErrorState,
  Field,
  Input,
  Modal,
  PageHeader,
  Spinner,
  StatusBadge,
  ConfirmDialog,
  useToast,
} from "../../components";
import { useAuth } from "../../auth/AuthContext";
import { createPasswordEnvelope } from "../../auth/passwordCrypto";
import {
  errMsg,
  formatDateTime,
} from "./shared";

/** 最近任务条数（PRD-01 §9：任务记录做紧凑列表，全量进 /tasks） */
const RECENT_TASK_LIMIT = 10;

/* ---------------------------------------------------------------- 页内 DTO（对齐 profile.py） */

/** GET /api/profile 新增的 settings 段（类型文件并行维护，这里本地扩展） */
interface ProfileSettings {
  share_diagnostics: boolean;
}

export default function ProfilePage() {
  const toast = useToast();
  const { refreshSession } = useAuth();

  const [profile, setProfile] = useState<(ProfileOverview & { settings?: ProfileSettings }) | null>(null);
  const [recentTasks, setRecentTasks] = useState<TaskSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [nameInput, setNameInput] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [inviteCode, setInviteCode] = useState("");
  const [joining, setJoining] = useState(false);
  const [savingShare, setSavingShare] = useState(false);
  const [leaveClassTarget, setLeaveClassTarget] = useState<ProfileClass | null>(null);
  const [passwordChangeOpen, setPasswordChangeOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [changingPassword, setChangingPassword] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      // 两路并发：任一失败整体进错误态（个人中心是聚合页，缺一角会误导）
      const [profileRes, tasksRes] = await Promise.all([
        api.get<ProfileOverview & { settings?: ProfileSettings }>("/api/profile", undefined, { signal }),
        api.get<Paginated<TaskSummary>>("/api/tasks", undefined, { signal }),
      ]);
      if (signal?.aborted) return;
      setProfile(profileRes);
      setRecentTasks(tasksRes.items.slice(0, RECENT_TASK_LIMIT));
    } catch (err) {
      if (!signal?.aborted) setError(errMsg(err));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  // 姓名输入框跟随加载结果初始化；保存成功后 profile 更新会再次同步
  useEffect(() => {
    setNameInput(profile?.user.name ?? "");
  }, [profile?.user.name]);

  /** 自助改名：PATCH /api/auth/profile 后刷新会话，侧边栏账号菜单同步新姓名。 */
  const saveName = async () => {
    const name = nameInput.trim();
    if (!name) {
      toast.error("姓名不能为空");
      return;
    }
    if (name === profile?.user.name) return;
    setSavingName(true);
    try {
      const res = await api.patch<{ user: ProfileOverview["user"] }>("/api/auth/profile", { name });
      setProfile((prev) => (prev ? { ...prev, user: res.user } : prev));
      await refreshSession();
      toast.success("姓名已更新");
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setSavingName(false);
    }
  };

  /** 加入班级：邀请码 → join-class（幂等；无效码后端 404 中文提示） */
  const joinClass = async () => {
    const code = inviteCode.trim();
    if (!code) {
      toast.error("请输入教师提供的邀请码");
      return;
    }
    setJoining(true);
    try {
      const res = await api.post<JoinClassResponse>("/api/student/join-class", {
        invite_code: code,
      });
      toast.success(
        res.already_enrolled ? `你已在「${res.class_name}」班级中` : `已加入「${res.class_name}」`,
      );
      setInviteCode("");
      if (res.joined_at) {
        setProfile((prev) => {
          if (!prev) return prev;
          const classes = prev.classes ?? [];
          const nextClass = {
            id: res.class_id,
            name: res.class_name,
            joined_at: res.joined_at,
          };
          return {
            ...prev,
            classes: [nextClass, ...classes.filter((item) => item.id !== res.class_id)],
          };
        });
      }
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setJoining(false);
    }
  };

  /** 退出班级仅标记 left_at，保持历史任务和审计关联可追溯。 */
  const leaveClass = async (clazz: ProfileClass) => {
    try {
      await api.delete<LeaveClassResponse>(`/api/student/classes/${clazz.id}`);
      setProfile((prev) =>
        prev ? { ...prev, classes: (prev.classes ?? []).filter((item) => item.id !== clazz.id) } : prev,
      );
      setLeaveClassTarget(null);
      toast.success(`已退出「${clazz.name}」`);
    } catch (err) {
      toast.error(errMsg(err));
    }
  };

  /** 原密码改密：两项密码分别加密传输，成功后服务端吊销其他设备会话。 */
  const changePassword = async () => {
    if (!currentPassword || !newPassword || !confirmPassword) {
      toast.error("请完整填写密码字段");
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.error("两次输入的新密码不一致");
      return;
    }
    setChangingPassword(true);
    try {
      const [currentPasswordEnvelope, newPasswordEnvelope] = await Promise.all([
        createPasswordEnvelope(currentPassword),
        createPasswordEnvelope(newPassword),
      ]);
      await api.post("/api/auth/change-password", {
        currentPasswordEnvelope,
        newPasswordEnvelope,
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordChangeOpen(false);
      toast.success("密码修改成功，其他设备已退出登录");
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setChangingPassword(false);
    }
  };


  /**
   * 诊断分享开关（PRD-06：默认关闭，教师只能看班级聚合统计）。
   * 成功后才更新本地态：失败时开关停留在原值，不出现"看着开了其实没开"。
   */
  const toggleShareDiagnostics = async (next: boolean) => {
    setSavingShare(true);
    try {
      const res = await api.patch<{ settings: ProfileSettings }>("/api/profile", {
        share_diagnostics: next,
      });
      setProfile((prev) => (prev ? { ...prev, settings: res.settings } : prev));
      toast.success(next ? "已允许任课教师查看你的诊断详情" : "已关闭诊断详情分享");
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setSavingShare(false);
    }
  };

  if (loading) {
    return (
      <div className="loading-block">
        <Spinner large /> 正在加载个人中心…
      </div>
    );
  }
  if (error || !profile) {
    return <ErrorState message={error ?? "加载失败"} onRetry={load} />;
  }

  const statusCount = (status: string): number => profile.task_counts[status] ?? 0;
  const shareDiagnostics = profile.settings?.share_diagnostics ?? false;

  return (
    <div>
      <PageHeader title="个人中心" />

      {/* 学习任务记录（统计 chips + 最近 10 条紧凑表） */}
      <Card
        title="学习任务记录"
        className="mb-4"
        actions={
          <Link to="/tasks" className="text-sm">
            查看全部 →
          </Link>
        }
      >
        <div className="flex items-center gap-2 flex-wrap mb-3">
          <span className="badge badge-primary">进行中 {statusCount("in_progress")}</span>
          <span className="badge badge-neutral">未开始 {statusCount("not_started")}</span>
          <span className="badge badge-success">已完成 {statusCount("completed")}</span>
        </div>
        <DataTable<TaskSummary>
          ariaLabel="学习任务记录"
          columns={[
            { key: "title", title: "任务" },
            {
              key: "status",
              title: "状态",
              width: "90px",
              render: (row) => <StatusBadge status={row.status} />,
            },
            {
              key: "latest_score",
              title: "得分",
              width: "70px",
              render: (row) =>
                row.latest_score == null ? "—" : `${Math.round(row.latest_score * 100)}`,
            },
          ]}
          rows={recentTasks}
          empty="还没有学习任务"
        />
      </Card>

      {/* 账号设置 */}
      <Card title="账号设置">
        <div className="grid grid-cols-2">
          <div className="flex flex-col gap-4">
            {/* 姓名可自助修改（PATCH /api/auth/profile）；邮箱为登录标识不可改 */}
            <Field label="姓名" hint="修改后侧边栏账号菜单同步更新。">
              <div className="flex items-center gap-2">
                <Input
                  aria-label="姓名"
                  value={nameInput}
                  onChange={(e) => setNameInput(e.target.value)}
                />
                <Button
                  variant="secondary"
                  size="sm"
                  loading={savingName}
                  disabled={nameInput.trim() === profile.user.name}
                  onClick={() => void saveName()}
                >
                  保存
                </Button>
              </div>
            </Field>
            <p className="text-sm">
              <span className="text-secondary">邮箱：</span>
              {profile.user.email}
            </p>
            <div>
              <Button variant="secondary" size="sm" onClick={() => setPasswordChangeOpen(true)}>
                修改密码（使用原密码）
              </Button>
            </div>
          </div>
          <div className="flex flex-col gap-4">
            <Field label="已加入班级" hint="你可以查看当前班级，退出后仍可使用邀请码重新加入。">
              {(profile.classes ?? []).length === 0 ? (
                <p className="text-sm text-secondary">暂未加入班级</p>
              ) : (
                <div className="flex flex-col gap-2">
                  {(profile.classes ?? []).map((clazz) => (
                    <div key={clazz.id} className="profile-class-row">
                      <div className="flex flex-col gap-1">
                        <span className="text-sm">{clazz.name}</span>
                        <span className="text-xs text-muted">加入于 {formatDateTime(clazz.joined_at)}</span>
                      </div>
                      <Button
                        variant="danger"
                        size="sm"
                        onClick={() => setLeaveClassTarget(clazz)}
                      >
                        退出班级
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </Field>
            <Field label="加入班级" hint="输入教师提供的班级邀请码">
              <div className="flex items-center gap-2">
                <Input
                  aria-label="班级邀请码"
                  placeholder="如 BHZD-2026"
                  value={inviteCode}
                  onChange={(e) => setInviteCode(e.target.value)}
                />
                {/* 固定最小宽度，防止弹性输入框挤压操作目标。 */}
                <Button
                  variant="secondary"
                  className="profile-join-class-button"
                  loading={joining}
                  onClick={joinClass}
                >
                  加入班级
                </Button>
              </div>
            </Field>
            {/* 诊断详情分享授权（PRD-06 待确认项 #2：默认关闭，教师仅见聚合） */}
            <Field
              label="隐私授权"
              hint="默认关闭：关闭时任课教师只能看到你所在班级的聚合统计；开启后教师可查看你的诊断详情，用于针对性辅导。"
            >
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  aria-label="允许任课教师查看我的诊断详情"
                  checked={shareDiagnostics}
                  disabled={savingShare}
                  onChange={(e) => toggleShareDiagnostics(e.target.checked)}
                />
                允许任课教师查看我的诊断详情
              </label>
            </Field>
          </div>
        </div>
      </Card>

      {/* 原密码改密弹窗：前端先校验必填和确认值，后端再验证原密码与策略。 */}
      <Modal
        open={passwordChangeOpen}
        title="修改密码"
        onClose={() => {
          if (!changingPassword) setPasswordChangeOpen(false);
        }}
        footer={
          <>
            <Button
              variant="ghost"
              disabled={changingPassword}
              onClick={() => setPasswordChangeOpen(false)}
            >
              取消
            </Button>
            <Button variant="primary" loading={changingPassword} onClick={() => void changePassword()}>
              保存新密码
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Field label="原密码">
            <Input
              type="password"
              aria-label="原密码"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
            />
          </Field>
          <Field label="新密码" hint="至少 8 位，且同时包含字母和数字">
            <Input
              type="password"
              aria-label="新密码"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
          </Field>
          <Field label="确认新密码">
            <Input
              type="password"
              aria-label="确认新密码"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
          </Field>
        </div>
      </Modal>

      <ConfirmDialog
        open={leaveClassTarget !== null}
        title="退出班级"
        description={leaveClassTarget ? `确认退出「${leaveClassTarget.name}」吗？退出后可使用邀请码重新加入。` : undefined}
        confirmText="退出班级"
        danger
        onConfirm={() => (leaveClassTarget ? leaveClass(leaveClassTarget) : undefined)}
        onCancel={() => setLeaveClassTarget(null)}
      />
    </div>
  );
}
