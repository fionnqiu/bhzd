import { Link } from "react-router-dom";
import { Button, Card } from "../../components";

/** 404 页（未匹配路由）。 */
export default function NotFoundPage() {
  return (
    <div className="main-content" style={{ margin: "0 auto", paddingTop: 80 }}>
      <Card>
        <div className="empty-state">
          <div className="empty-state-title">页面不存在</div>
          <p className="empty-state-hint">
            你访问的页面不存在或已被移除，请检查链接是否正确。
          </p>
          <Link to="/">
            <Button variant="secondary">返回首页</Button>
          </Link>
        </div>
      </Card>
    </div>
  );
}
