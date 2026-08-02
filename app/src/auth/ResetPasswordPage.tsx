import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiRequestError, api } from "../api/client";
import type { MessageResponse } from "../api/types";
import { Button, Field, Input } from "../components";
import { createPasswordEnvelope } from "./passwordCrypto";

/**
 * 重置密码页（POST /api/auth/reset-password）。
 * 成功后服务端会吊销该用户全部会话（auth.py：重置即按凭证泄露处置），
 * 因此成功态只给"去登录"入口，不做自动登录。
 */
export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("两次输入的密码不一致");
      return;
    }
    setSubmitting(true);
    try {
      const passwordEnvelope = await createPasswordEnvelope(password);
      const res = await api.post<MessageResponse>("/api/auth/reset-password", {
        token,
        passwordEnvelope,
      });
      setDone(res.message);
    } catch (err) {
      setError(
        err instanceof ApiRequestError ? err.message : "重置失败，请稍后重试",
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (!token) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="auth-brand">
            <div className="auth-brand-name">标航智导</div>
          </div>
          <div className="form-alert form-alert-error">
            链接缺少重置令牌，请从重置邮件中打开完整链接
          </div>
          <div className="auth-links">
            <Link to="/forgot-password">重新发起找回密码</Link>
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
        <h1 className="auth-title">设置新密码</h1>
        {done ? (
          <>
            <div className="form-alert form-alert-success">{done}</div>
            <div className="auth-links">
              <Link to="/login">使用新密码登录</Link>
            </div>
          </>
        ) : (
          <>
            {error ? <div className="form-alert form-alert-error">{error}</div> : null}
            <form onSubmit={onSubmit}>
              <Field label="新密码" required hint="至少 8 位，需同时包含字母和数字">
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  minLength={8}
                  required
                />
              </Field>
              <Field label="确认新密码" required>
                <Input
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  autoComplete="new-password"
                  required
                />
              </Field>
              <Button type="submit" block loading={submitting}>
                重置密码
              </Button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
