/**
 * 个人中心页（PRD-01 §9）。
 *
 * 聚合数据：/api/profile（任务统计/诊断摘要/成长记录/设置）、
 * /api/profile/mastery（能力地图）与 /api/tasks（最近任务记录）。
 *
 * 关键决策（为什么）：
 * - 能力地图统一按薄弱优先排序：学生第一眼应看到"最该补的"
 *   （与预设页薄弱优先同口径）；点击能力行开抽屉看近 30 天掌握度趋势
 *   （GET mastery/trend），趋势是学生判断"学习方法是否有效"的直接证据。
 * - share_diagnostics 默认关闭（PRD-06 待确认项 #2 的产品决策）：关闭时教师
 *   只能看班级聚合统计，开启后才可查看本人诊断详情；开关改动即 PATCH 生效。
 * - 修改密码在站内校验原密码；成功后当前会话保留，其他设备会话由服务端吊销。
 *
 * 类型说明：api/types.ts 由其他任务并行维护，新增 DTO（趋势/设置）。
 * 一律页内声明，与后端 profile.py 响应逐字段对齐。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type {
  JoinClassResponse,
  LeaveClassResponse,
  MasteryRecord,
  Paginated,
  ProfileClass,
  ProfileOverview,
  TaskSummary,
} from "../../api/types";
import {
  Button,
  Card,
  DataTable,
  Drawer,
  EmptyState,
  ErrorState,
  Field,
  Input,
  MasteryBadge,
  Modal,
  PageHeader,
  ProgressBar,
  Spinner,
  StatusBadge,
  Tag,
  ConfirmDialog,
  useToast,
} from "../../components";
import { createPasswordEnvelope } from "../../auth/passwordCrypto";
import {
  errMsg,
  formatDateTime,
  masterySourceLabel,
} from "./shared";

/** 最近任务条数（PRD-01 §9：任务记录做紧凑列表，全量进 /tasks） */
const RECENT_TASK_LIMIT = 10;

/* ---------------------------------------------------------------- 页内 DTO（对齐 profile.py） */

/** GET /api/profile 新增的 settings 段（类型文件并行维护，这里本地扩展） */
interface ProfileSettings {
  share_diagnostics: boolean;
}

/** GET /api/profile/mastery/trend 的时间序列点（mastery_events 按时间升序） */
interface MasteryTrendPoint {
  date: string;
  cap_id: string;
  old_score: number;
  new_score: number;
  source: string;
  created_at: string;
}

/**
 * 掌握度趋势迷你折线（纯 SVG 无依赖）：new_score 序列按时间升序描点。
 * 为什么手画而不用图表库：趋势只是"方向感"参考，一条折线足够，
 * 引入图表库只为这张小图不值（NO new npm deps 约束同向）。
 */
function TrendSparkline({ points }: { points: number[] }) {
  const W = 280;
  const H = 64;
  const PAD = 6;
  if (points.length === 0) return null;
  if (points.length === 1) {
    // 单点无法成线：画一个点，避免空图误解为"无数据"
    const y = H - PAD - points[0] * (H - PAD * 2);
    return (
      <svg width={W} height={H} role="img" aria-label="掌握度趋势（1 次记录）">
        <circle cx={W / 2} cy={y} r={4} fill="var(--color-primary)" />
      </svg>
    );
  }
  const coords = points.map((score, index) => {
    const x = PAD + (index / (points.length - 1)) * (W - PAD * 2);
    const y = H - PAD - score * (H - PAD * 2);
    return `${x},${y}`;
  });
  return (
    <svg width={W} height={H} role="img" aria-label="掌握度趋势">
      {/* 0.8/0.4 档位参考线：与 MasteryBadge 阈值同一口径 */}
      <line x1={PAD} x2={W - PAD} y1={H - PAD - 0.8 * (H - PAD * 2)} y2={H - PAD - 0.8 * (H - PAD * 2)} stroke="var(--color-success)" strokeDasharray="4 4" strokeWidth={1} opacity={0.5} />
      <line x1={PAD} x2={W - PAD} y1={H - PAD - 0.4 * (H - PAD * 2)} y2={H - PAD - 0.4 * (H - PAD * 2)} stroke="var(--color-danger)" strokeDasharray="4 4" strokeWidth={1} opacity={0.5} />
      <polyline points={coords.join(" ")} fill="none" stroke="var(--color-primary)" strokeWidth={2} />
    </svg>
  );
}

export default function ProfilePage() {
  const toast = useToast();

  const [profile, setProfile] = useState<(ProfileOverview & { settings?: ProfileSettings }) | null>(null);
  const [mastery, setMastery] = useState<MasteryRecord[] | null>(null);
  const [recentTasks, setRecentTasks] = useState<TaskSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [inviteCode, setInviteCode] = useState("");
  const [joining, setJoining] = useState(false);
  const [savingShare, setSavingShare] = useState(false);
  const [leaveClassTarget, setLeaveClassTarget] = useState<ProfileClass | null>(null);
  const [passwordChangeOpen, setPasswordChangeOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [changingPassword, setChangingPassword] = useState(false);

  // 能力趋势抽屉：点击能力行打开，drawer 内拉该 cap 近 30 天事件序列
  const [trendCap, setTrendCap] = useState<MasteryRecord | null>(null);
  const [trend, setTrend] = useState<MasteryTrendPoint[] | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      // 四路并发：任一失败整体进错误态（个人中心是聚合页，缺一角会误导）
      const [profileRes, masteryRes, tasksRes] = await Promise.all([
        api.get<ProfileOverview & { settings?: ProfileSettings }>("/api/profile", undefined, { signal }),
        api.get<Paginated<MasteryRecord>>("/api/profile/mastery", undefined, { signal }),
        api.get<Paginated<TaskSummary>>("/api/tasks", undefined, { signal }),
      ]);
      if (signal?.aborted) return;
      setProfile(profileRes);
      setMastery(masteryRes.items);
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

  // 打开趋势抽屉时拉取该能力近 30 天序列；换能力重拉，关闭时清空防串数据
  useEffect(() => {
    if (!trendCap) {
      setTrend(null);
      return;
    }
    const controller = new AbortController();
    setTrend(null);
    api
      .get<{ items: MasteryTrendPoint[] }>("/api/profile/mastery/trend", {
        cap_id: trendCap.cap_id,
        days: 30,
      }, { signal: controller.signal })
      .then((res) => {
        if (!controller.signal.aborted) setTrend(res.items);
      })
      .catch(() => {
        if (!controller.signal.aborted) setTrend([]);
      });
    return () => controller.abort();
  }, [trendCap]);

  /** 能力地图统一排序：按分数升序，让薄弱能力优先进入视线。 */
  const masteryGroups = useMemo(() => {
    return [
      {
        name: "能力掌握度",
        records: [...(mastery ?? [])].sort((a, b) => a.score - b.score),
      },
    ];
  }, [mastery]);

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
  if (error || !profile || !mastery) {
    return <ErrorState message={error ?? "加载失败"} onRetry={load} />;
  }

  const statusCount = (status: string): number => profile.task_counts[status] ?? 0;
  const shareDiagnostics = profile.settings?.share_diagnostics ?? false;

  return (
    <div>
      <PageHeader title="个人中心" sub="能力地图、学习记录与账号设置" />

      <div className="grid grid-cols-2 mb-4">
        {/* 能力地图（薄弱优先；点击能力行看 30 天趋势） */}
        <Card title="能力地图">
          {mastery.length === 0 ? (
            <EmptyState
              title="还没有掌握度记录"
              hint="完成一次练习或诊断后，这里会生成你的能力地图"
              action={
                <Link to="/presets" className="btn btn-primary btn-sm">
                  去预设学习
                </Link>
              }
            />
          ) : (
            <div className="flex flex-col gap-4">
              {masteryGroups.map((group) => (
                <div key={group.name}>
                  <h3 className="mb-2" style={{ fontSize: "var(--font-size-base)" }}>
                    {group.name}
                  </h3>
                  <div className="flex flex-col gap-3">
                    {group.records.map((record) => (
                      <div key={record.cap_id}>
                        <div className="flex items-center justify-between gap-2 mb-2">
                          {/* 能力名改为按钮：点击开趋势抽屉（图谱入口移到抽屉内） */}
                          <button
                            type="button"
                            className="text-sm"
                            style={{
                              background: "none",
                              border: "none",
                              padding: 0,
                              cursor: "pointer",
                              color: "var(--color-primary)",
                            }}
                            onClick={() => setTrendCap(record)}
                          >
                            {record.cap_name}
                          </button>
                          <MasteryBadge score={record.score} />
                        </div>
                        <ProgressBar value={record.score} />
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <div className="flex flex-col gap-4">
          {/* 学习任务记录（统计 chips + 最近 10 条紧凑表） */}
          <Card
            title="学习任务记录"
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

          {/* 诊断摘要 */}
          <Card
            title="诊断摘要"
            actions={
              <Link to="/" className="text-sm">
                去 Agent 查看 →
              </Link>
            }
          >
            {profile.recent_diagnostic_summaries.length === 0 ? (
              <EmptyState title="还没有诊断摘要" hint="上传一次标注结果，获取第一次诊断" />
            ) : (
              <div className="flex flex-col gap-2">
                {profile.recent_diagnostic_summaries.map((summary) => (
                  <div key={summary.id} className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2">
                      <Tag>{summary.file_format}</Tag>
                      <span className="text-sm">{summary.error_count} 个错误</span>
                    </span>
                    <span className="text-xs text-muted">{formatDateTime(summary.created_at)}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>

      <div className="grid grid-cols-2 mb-4">
        {/* 成长记录（mastery_events 时间线；来源中文化） */}
        <Card title="成长记录">
          {profile.growth.length === 0 ? (
            <EmptyState title="还没有成长记录" hint="掌握度每次变化都会记录在这里" />
          ) : (
            <div className="flex flex-col gap-2">
              {profile.growth.map((event, index) => (
                <div key={index} className="flex items-center justify-between gap-2">
                  <span className="text-sm">
                    {event.cap_name}
                    <span className="text-xs text-muted">
                      {" "}
                      {Math.round(event.old_score * 100)}% → {Math.round(event.new_score * 100)}%
                    </span>
                  </span>
                  <span className="flex items-center gap-2">
                    <Tag>{masterySourceLabel(event.source)}</Tag>
                    <span className="text-xs text-muted">{formatDateTime(event.created_at)}</span>
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>

      </div>

      {/* 账号设置 */}
      <Card title="账号设置">
        <div className="grid grid-cols-2">
          <div>
            <p className="text-sm mb-2">
              <span className="text-secondary">姓名：</span>
              {profile.user.name}
            </p>
            <p className="text-sm mb-4">
              <span className="text-secondary">邮箱：</span>
              {profile.user.email}
            </p>
            <Button variant="secondary" size="sm" onClick={() => setPasswordChangeOpen(true)}>
              修改密码（使用原密码）
            </Button>
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

      {/* 能力趋势抽屉：近 30 天掌握度事件折线（mastery/trend 升序序列） */}
      <Drawer
        open={trendCap !== null}
        title={trendCap ? `${trendCap.cap_name} · 近 30 天趋势` : ""}
        onClose={() => setTrendCap(null)}
      >
        {trendCap ? (
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm text-secondary">当前掌握度</span>
              <MasteryBadge score={trendCap.score} />
            </div>
            {trend === null ? (
              <div className="loading-block">
                <Spinner /> 正在加载趋势…
              </div>
            ) : trend.length === 0 ? (
              <p className="text-sm text-secondary">近 30 天暂无掌握度变化记录。</p>
            ) : (
              <>
                <TrendSparkline points={trend.map((p) => p.new_score)} />
                <p className="text-xs text-muted">
                  共 {trend.length} 次变化；虚线为「已掌握 80%」与「待加强 40%」参考线。
                </p>
                <ul className="flex flex-col gap-2">
                  {[...trend].reverse().slice(0, 5).map((point, index) => (
                    <li key={index} className="flex items-center justify-between gap-2 text-sm">
                      <span>
                        {Math.round(point.old_score * 100)}% → {Math.round(point.new_score * 100)}%
                        <span className="text-xs text-muted">（{masterySourceLabel(point.source)}）</span>
                      </span>
                      <span className="text-xs text-muted">{point.date}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            <Link to={`/graph?node=${trendCap.cap_id}`} className="btn btn-secondary btn-sm">
              在能力图谱中查看 →
            </Link>
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}
