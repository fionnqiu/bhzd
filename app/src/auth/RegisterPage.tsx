import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiRequestError } from "../api/client";
import type { RegisterResponse } from "../api/types";
import { Button, Field, Input, Select } from "../components";
import { useAuth } from "./AuthContext";

/**
 * 注册页（POST /api/auth/register）。
 * 学生和教师都可自助注册；管理员角色仍不属于公开注册范围。
 * 邮箱验证已取消，注册成功后直接提示用户登录。
 */
export default function RegisterPage() {
  const { register } = useAuth();
  const [form, setForm] = useState({
    email: "",
    name: "",
    password: "",
    confirm: "",
    role: "student" as "student" | "teacher",
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

  // 注册已即时生效；保留独立登录步骤，不改变现有会话和跳转契约。
  if (result) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="auth-brand">
            <div className="auth-brand-name">标航智导</div>
          </div>
          <h1 className="auth-title">注册成功</h1>
          <div className="form-alert form-alert-success">{result.message}</div>
          <p className="text-sm text-secondary">账号已启用，可使用 {result.user.email} 直接登录。</p>
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
          <Field label="角色" required>
            <Select
              value={form.role}
              onChange={(e) => update("role")(e.target.value)}
              options={[
                { value: "student", label: "学生" },
                { value: "teacher", label: "教师" },
              ]}
            />
          </Field>
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
