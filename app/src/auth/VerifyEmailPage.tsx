import { Link } from "react-router-dom";

/**
 * 保留历史邮件链接的落地页，但邮箱状态不再决定账号或功能可用性。
 * 不再读取或提交令牌，避免用户以为仍需要完成额外的验证步骤。
 */
export default function VerifyEmailPage() {
  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <div className="auth-brand-name">标航智导</div>
        </div>
        <h1 className="auth-title">账号可直接使用</h1>
        <div className="form-alert form-alert-success">邮箱验证已取消，请直接登录。</div>
        <div className="auth-links">
          <Link to="/login">前往登录</Link>
          <Link to="/">返回首页</Link>
        </div>
      </div>
    </div>
  );
}
