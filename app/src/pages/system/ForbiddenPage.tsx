import { Link } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";
import { Button, Card } from "../../components";

/**
 * 403 页（角色不足）。
 * 学生看不到其他端入口（PRD-04 §5.2），但直接敲 URL 仍会到达——此时
 * 明确告知权限不足并给出回自己端的出口，比沉默重定向更可解释。
 */
export default function ForbiddenPage() {
  const { user } = useAuth();
  // Teachers cannot use the student home route, so their recovery link must stay in the teacher portal.
  const homePath = user?.role === "teacher" ? "/teacher" : "/";

  return (
    <div className="main-content" style={{ margin: "0 auto", paddingTop: 80 }}>
      <Card>
        <div className="empty-state">
          <div className="empty-state-title">没有访问权限</div>
          <p className="empty-state-hint">
            当前账号的角色无权访问该页面。如需开通权限，请联系系统管理员。
          </p>
          <Link to={homePath}>
            <Button variant="secondary">返回首页</Button>
          </Link>
        </div>
      </Card>
    </div>
  );
}
