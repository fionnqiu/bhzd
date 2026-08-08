import {
  BookMarked,
  Database,
  FlaskConical,
  ListOrdered,
  SearchCheck,
  Send,
  Upload,
} from "lucide-react";
import ShellLayout, { type NavItem } from "./ShellLayout";

/** RAG 管理端导航按资料到发布的操作顺序排列。 */
const NAV_ITEMS: NavItem[] = [
  { to: "/rag-admin", label: "资料库", icon: Database, end: true },
  { to: "/rag-admin/upload", label: "上传资料", icon: Upload },
  { to: "/rag-admin/jobs", label: "任务队列", icon: ListOrdered },
  { to: "/rag-admin/ledgers", label: "来源台账", icon: BookMarked },
  { to: "/rag-admin/search-test", label: "召回测试", icon: SearchCheck },
  { to: "/rag-admin/eval-cases", label: "评测集", icon: FlaskConical },
  { to: "/rag-admin/publish", label: "发布审核", icon: Send },
];

/** RAG 管理端壳（仅 system_admin；服务端对管理接口和 Agent 工具同步校验）。 */
export default function RagAdminLayout() {
  return (
    <ShellLayout
      portalKey="rag-admin"
      portalName="RAG 知识库管理"
      navItems={NAV_ITEMS}
      variant="operations-workbench"
    />
  );
}
