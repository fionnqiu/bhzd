import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiRequestError, api } from "../api/client";
import type { MessageResponse } from "../api/types";
import { Spinner } from "../components";

/**
 * 邮箱验证页（POST /api/auth/verify-email）。
 * 令牌经邮件链接 ?token= 带入，进入页面即自动提交——验证令牌是一次性的
 * （服务端消费即失效），让用户再点一次按钮只会得到"已过期"的困惑反馈。
 */
export default function VerifyEmailPage() {
  const [params] = useSearchParams();
  const [state, setState] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("");
  // StrictMode 双调用防护：令牌一次性，重复提交第二次必失败
  const submitted = useRef(false);

  useEffect(() => {
    const token = params.get("token");
    if (!token) {
      setState("error");
      setMessage("链接缺少验证令牌，请从验证邮件中打开完整链接");
      return;
    }
    if (submitted.current) return;
    const controller = new AbortController();
    // Deferring one microtask lets StrictMode clean up its probe before this one-time token is sent.
    queueMicrotask(() => {
      if (controller.signal.aborted || submitted.current) return;
      submitted.current = true;
      void api
        .post<MessageResponse>("/api/auth/verify-email", { token }, { signal: controller.signal })
        .then((res) => {
          if (controller.signal.aborted) return;
          setState("success");
          setMessage(res.message);
        })
        .catch((err) => {
          if (controller.signal.aborted) {
            submitted.current = false;
            return;
          }
          setState("error");
          setMessage(
            err instanceof ApiRequestError
              ? err.message
              : "验证失败，请稍后重试或重新获取验证邮件",
          );
        });
    });
    return () => controller.abort();
  }, [params]);

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <div className="auth-brand-name">标航智导</div>
        </div>
        <h1 className="auth-title">邮箱验证</h1>
        {state === "loading" ? (
          <div className="loading-block">
            <Spinner /> 正在验证…
          </div>
        ) : state === "success" ? (
          <div className="form-alert form-alert-success">{message}</div>
        ) : (
          <div className="form-alert form-alert-error">{message}</div>
        )}
        <div className="auth-links">
          <Link to="/login">前往登录</Link>
          <Link to="/">返回首页</Link>
        </div>
      </div>
    </div>
  );
}
