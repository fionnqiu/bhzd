import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { MessageResponse } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import Button from "./Button";

interface ResendResponse extends MessageResponse {
  dev_verify_token?: string;
}

/**
 * 邮箱未验证横幅。
 *
 * 为什么必须在所有壳里展示：未验证用户登录不被拦截，但 Agent/RAG/诊断
 * 等核心能力会被服务端 403（EMAIL_NOT_VERIFIED）——不提示的话学生会
 * 在每个按钮上收到莫名其妙的失败（PRD-06 §3.2 + runs.py `_require_verified`）。
 */
export default function EmailVerifyBanner() {
  const { user } = useAuth();
  const [sending, setSending] = useState(false);
  const [sentMessage, setSentMessage] = useState<string | null>(null);
  const [devToken, setDevToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!user || user.email_verified) return null;

  const resend = async () => {
    setSending(true);
    setError(null);
    try {
      const res = await api.post<ResendResponse>("/api/auth/resend-verification");
      setSentMessage(res.message);
      // 开发兜底：未配置 SMTP 时后端回显令牌，直接给可点链接（生产无此字段）
      if (res.dev_verify_token) setDevToken(res.dev_verify_token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送失败，请稍后重试");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="verify-banner" role="alert">
      <span>
        你的邮箱尚未验证，验证后才能使用 Agent 指挥舱、知识问答与标注诊断。
      </span>
      <Button size="sm" variant="secondary" loading={sending} onClick={resend}>
        重发验证邮件
      </Button>
      {sentMessage ? <span className="text-success">{sentMessage}</span> : null}
      {error ? <span className="text-danger">{error}</span> : null}
      {devToken ? (
        <Link to={`/verify-email?token=${encodeURIComponent(devToken)}`}>
          开发模式：点击直接验证
        </Link>
      ) : null}
    </div>
  );
}
