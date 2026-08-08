import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiRequestError, api } from "../api/client";
import type { ForgotPasswordResponse } from "../api/types";
import { Button, Field, Input } from "../components";

/**
 * 找回密码页（POST /api/auth/forgot-password）。
 * 后端对"邮箱是否存在"返回统一话术（PRD-06 §3.4），前端原样展示即可；
 * 开发模式响应带 dev_reset_token，渲染为可点链接直达重置页。
 */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ForgotPasswordResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await api.post<ForgotPasswordResponse>(
        "/api/auth/forgot-password",
        { email: email.trim() },
      );
      setResult(res);
    } catch (err) {
      setError(
        err instanceof ApiRequestError ? err.message : "发送失败，请稍后重试",
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (result) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="auth-brand">
            <div className="auth-brand-name">标航智导</div>
          </div>
          <h1 className="auth-title">重置邮件已发送</h1>
          <div className="form-alert form-alert-success">{result.message}</div>
          <p className="text-sm text-secondary">重置链接 30 分钟内有效。</p>
          {result.dev_reset_token ? (
            <div className="dev-token-box">
              开发模式（未配置 SMTP）：
              <Link to={`/reset-password?token=${encodeURIComponent(result.dev_reset_token)}`}>
                点击这里直接重置密码
              </Link>
            </div>
          ) : null}
          <div className="auth-links">
            <Link to="/login">返回登录</Link>
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
        </div>
        <h1 className="auth-title">找回密码</h1>
        {error ? <div className="form-alert form-alert-error">{error}</div> : null}
        <form onSubmit={onSubmit}>
          <Field label="注册邮箱" required hint="我们将向该邮箱发送密码重置链接">
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              required
            />
          </Field>
          <Button type="submit" block loading={submitting}>
            发送重置邮件
          </Button>
        </form>
        <div className="auth-links">
          <Link to="/login">返回登录</Link>
          <Link to="/register">注册账号</Link>
        </div>
      </div>
    </div>
  );
}
