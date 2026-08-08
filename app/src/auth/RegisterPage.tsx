import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiRequestError } from "../api/client";
import type { RegisterResponse } from "../api/types";
import { Button, Field, Input, Select } from "../components";
import { useAuth } from "./AuthContext";

/**
 * 注册页（POST /api/auth/register）。
 * 学生自助注册；教师需邀请码（auth.py：role=teacher 时校验 teacher_invite）。
 * 注册后不建会话——需先完成邮箱验证，故成功态引导去验证而不是直接登录。
 */
export default function RegisterPage() {
  const { register } = useAuth();
  const [form, setForm] = useState({
    email: "",
    name: "",
    password: "",
    confirm: "",
    role: "student" as "student" | "teacher",
    teacher_invite: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RegisterResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const update = (key: keyof typeof form) => (value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (form.password !== form.confirm) {
      setError("两次输入的密码不一致");
      return;
    }
    setSubmitting(true);
    try {
      const res = await register({
        email: form.email.trim(),
        name: form.name.trim(),
        password: form.password,
        role: form.role,
        teacher_invite: form.role === "teacher" ? form.teacher_invite.trim() : undefined,
      });
      setResult(res);
    } catch (err) {
      setError(
        err instanceof ApiRequestError ? err.message : "注册失败，请稍后重试",
      );
    } finally {
      setSubmitting(false);
    }
  };

  // 成功态：提示查收验证邮件；开发模式后端回显 dev_verify_token，给可点链接
  if (result) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="auth-brand">
            <div className="auth-brand-name">标航智导</div>
          </div>
          <h1 className="auth-title">注册成功</h1>
          <div className="form-alert form-alert-success">{result.message}</div>
          <p className="text-sm text-secondary">
            验证邮件已发送至 {result.user.email}，请完成邮箱验证后登录。
          </p>
          {result.dev_verify_token ? (
            <div className="dev-token-box">
              开发模式（未配置 SMTP）：
              <Link to={`/verify-email?token=${encodeURIComponent(result.dev_verify_token)}`}>
                点击这里直接完成邮箱验证
              </Link>
            </div>
          ) : null}
          <div className="auth-links">
            <Link to="/login">前往登录</Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <div className="auth-brand-name">标航智导</div>
          <div className="auth-brand-slogan">数据标注能力成长平台</div>
        </div>
        <h1 className="auth-title">注册账号</h1>
        {error ? <div className="form-alert form-alert-error">{error}</div> : null}
        <form onSubmit={onSubmit}>
          <Field label="姓名" required>
            <Input
              value={form.name}
              onChange={(e) => update("name")(e.target.value)}
              placeholder="真实姓名或昵称"
              maxLength={50}
              required
            />
          </Field>
          <Field label="邮箱" required>
            <Input
              type="email"
              value={form.email}
              onChange={(e) => update("email")(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              required
            />
          </Field>
          <Field label="角色" required hint="教师账号需要邀请码，请向系统管理员索取">
            <Select
              value={form.role}
              onChange={(e) => update("role")(e.target.value)}
              options={[
                { value: "student", label: "学生" },
                { value: "teacher", label: "教师" },
              ]}
            />
          </Field>
          {form.role === "teacher" ? (
            <Field label="教师邀请码" required>
              <Input
                value={form.teacher_invite}
                onChange={(e) => update("teacher_invite")(e.target.value)}
                placeholder="请输入邀请码"
                required
              />
            </Field>
          ) : null}
          <Field label="密码" required hint="至少 8 位，需同时包含字母和数字">
            <Input
              type="password"
              value={form.password}
              onChange={(e) => update("password")(e.target.value)}
              autoComplete="new-password"
              minLength={8}
              required
            />
          </Field>
          <Field label="确认密码" required>
            <Input
              type="password"
              value={form.confirm}
              onChange={(e) => update("confirm")(e.target.value)}
              autoComplete="new-password"
              required
            />
          </Field>
          <Button type="submit" block loading={submitting}>
            注册
          </Button>
        </form>
        <div className="auth-links">
          <span />
          <Link to="/login">已有账号？去登录</Link>
        </div>
      </div>
    </div>
  );
}
