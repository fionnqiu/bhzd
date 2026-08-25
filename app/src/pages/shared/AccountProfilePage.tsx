/**
 * 通用个人中心页（教师端 /teacher/profile 与系统管理端 /admin/profile 共用）。
 *
 * 为什么不复用学生端 /profile：学生页聚合能力地图、任务记录、班级等
 * 学生专属数据，教师/管理员打开后全部为空区块，反而误导。这里只保留
 * 三端通用的最小集合：账号信息（姓名可自助修改，PATCH /api/auth/profile）
 * + 原密码改密（/api/auth/change-password 对两类会话均可用）。
 */
import { useState } from "react";
import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { createPasswordEnvelope } from "../../auth/passwordCrypto";
import {
  Button,
  Card,
  Field,
  Input,
  Modal,
  PageHeader,
  useToast,
} from "../../components";

/** 与 ShellLayout.ROLE_NAMES 同口径；本页独立持有，避免反向依赖布局层。 */
const ROLE_NAMES: Record<string, string> = {
  student: "学生",
  teacher: "教师",
  system_admin: "系统管理员",
};

export default function AccountProfilePage() {
  const { user, refreshSession } = useAuth();
  const toast = useToast();

  const [nameInput, setNameInput] = useState(user?.name ?? "");
  const [savingName, setSavingName] = useState(false);
  const [passwordChangeOpen, setPasswordChangeOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [changingPassword, setChangingPassword] = useState(false);

  /** 自助改名：PATCH /api/auth/profile 后刷新会话，侧边栏账号菜单同步新姓名。 */
  const saveName = async () => {
    const name = nameInput.trim();
    if (!name) {
      toast.error("姓名不能为空");
      return;
    }
    if (name === user?.name) return;
    setSavingName(true);
    try {
      await api.patch("/api/auth/profile", { name });
      await refreshSession();
      toast.success("姓名已更新");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "姓名修改失败，请稍后重试");
    } finally {
      setSavingName(false);
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
      toast.error(err instanceof Error ? err.message : "修改密码失败，请稍后重试");
    } finally {
      setChangingPassword(false);
    }
  };

  return (
    <div>
      <PageHeader title="个人中心" />

      {/* 账号信息：直接读取会话中的当前用户；姓名可自助修改，邮箱为登录标识不可改 */}
      <Card title="账号信息">
        <div className="flex flex-col gap-4">
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
                disabled={nameInput.trim() === (user?.name ?? "")}
                onClick={() => void saveName()}
              >
                保存
              </Button>
            </div>
          </Field>
          <p className="text-sm">
            <span className="text-secondary">邮箱：</span>
            {user?.email}
          </p>
          <p className="text-sm">
            <span className="text-secondary">角色：</span>
            {ROLE_NAMES[user?.role ?? ""] ?? user?.role}
          </p>
        </div>
      </Card>

      <Card title="账号设置" className="mt-4">
        <Button variant="secondary" size="sm" onClick={() => setPasswordChangeOpen(true)}>
          修改密码（使用原密码）
        </Button>
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
    </div>
  );
}
