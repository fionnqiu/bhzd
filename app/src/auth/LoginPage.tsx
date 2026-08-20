import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ApiRequestError } from "../api/client";
import { Button, Field, Input } from "../components";
import { useAuth } from "./AuthContext";

function loginDestination(role: string, requestedPath?: string): string {
  // Administrators have an explicit management portal. Keep that as their
  // default landing page while allowing the portal switcher to visit `/`.
  if (role === "system_admin") return requestedPath ?? "/admin";
  if (role !== "teacher") return requestedPath ?? "/";

  // A saved student/RAG URL must not bounce a teacher into a page their role may not open.
  if (requestedPath?.startsWith("/teacher") && !requestedPath.startsWith("/teacher/review")) {
    return requestedPath;
  }
  return "/teacher";
}

/**
 * 登录页（POST /api/auth/login）。
 * 成功后回到守卫拦下来的原路径（location.state.from），缺省进首页。
 */
export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [retryAfterSeconds, setRetryAfterSeconds] = useState<number | null>(null);
  const retryDeadlineRef = useRef<number | null>(null);

  const requestedPath = (location.state as { from?: string } | null)?.from;

  useEffect(() => {
    if (retryAfterSeconds === null) {
      retryDeadlineRef.current = null;
      return;
    }
    // Keep one absolute deadline across state updates; rebuilding it whenever
    // the displayed seconds change would make the lockout extend forever.
    const deadline =
      retryDeadlineRef.current ?? (Date.now() + retryAfterSeconds * 1000);
    retryDeadlineRef.current = deadline;
    const timer = window.setInterval(() => {
      const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      if (remaining === 0) {
        // The next submission is allowed again; remove the stale lockout copy
        // so the form does not claim that a completed wait is still active.
        setRetryAfterSeconds(null);
        setError(null);
        return;
      }
      setRetryAfterSeconds(remaining);
    }, 250);
    return () => window.clearInterval(timer);
  }, [retryAfterSeconds]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (retryAfterSeconds !== null) return;
    setError(null);
    setSubmitting(true);
    try {
      const session = await login(email.trim(), password);
      navigate(loginDestination(session.user.role, requestedPath), { replace: true });
    } catch (err) {
      const retryAfter = err instanceof ApiRequestError ? err.retryAfterSeconds : null;
      if (
        err instanceof ApiRequestError &&
        err.code === "RATE_LIMITED" &&
        typeof retryAfter === "number" &&
        Number.isFinite(retryAfter) &&
        retryAfter > 0
      ) {
        setRetryAfterSeconds(Math.ceil(retryAfter));
        setError(`尝试过于频繁，请 ${Math.ceil(retryAfter)} 秒后再试`);
      } else {
        // Other backend messages are already user-safe and actionable.
        setError(err instanceof ApiRequestError ? err.message : "登录失败，请稍后重试");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <div className="auth-brand-name">标航智导</div>
        </div>
        <h1 className="auth-title">登录</h1>
        {error ? <div className="form-alert form-alert-error">{error}</div> : null}
        <form onSubmit={onSubmit}>
          <Field label="邮箱" required>
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              required
            />
          </Field>
          <Field label="密码" required>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入密码"
              autoComplete="current-password"
              required
            />
          </Field>
          <Button type="submit" block loading={submitting} disabled={retryAfterSeconds !== null}>
            {retryAfterSeconds === null ? "登录" : `${retryAfterSeconds} 秒后重试`}
          </Button>
        </form>
        <div className="auth-links">
          <Link to="/forgot-password">忘记密码？</Link>
          <Link to="/register">注册</Link>
        </div>
      </div>
    </div>
  );
}
