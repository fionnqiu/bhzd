import { Cpu, Database, ScrollText, SearchCheck, ShieldCheck, SlidersHorizontal, Upload, UserCog } from "lucide-react";
import ShellLayout, { type NavItem } from "./ShellLayout";

/**
 * 系统管理端导航。
 * RAG 知识库管理已并入此端，用 section 字段对导航项分组，避免两个独立入口
 * 带来的门户切换开销（两者均限 system_admin，用户群体完全重叠）。
 */
const NAV_ITEMS: NavItem[] = [
  // 系统配置组
  { to: "/admin/providers", label: "模型供应商", icon: Cpu, section: "系统配置" },
  { to: "/admin/rag-settings", label: "RAG 参数", icon: SlidersHorizontal, section: "系统配置" },
  { to: "/admin/users", label: "用户管理", icon: UserCog, section: "系统配置" },
  { to: "/admin/security", label: "安全配置", icon: ShieldCheck, section: "系统配置" },
  { to: "/admin/audit-logs", label: "审计日志", icon: ScrollText, section: "系统配置" },
  // RAG 知识库组：资料处理与召回验证三个常用入口
  { to: "/admin/rag", label: "资料库", icon: Database, end: true, section: "RAG 知识库" },
  { to: "/admin/rag/upload", label: "上传资料", icon: Upload, section: "RAG 知识库" },
  { to: "/admin/rag/search-test", label: "召回测试", icon: SearchCheck, section: "RAG 知识库" },
];

/** 系统管理端壳（仅 system_admin；/api/admin/* 服务端另校验管理端会话）。 */
export default function AdminLayout() {
  return (
    <ShellLayout
      portalKey="admin"
      portalName="系统管理"
      navItems={NAV_ITEMS}
      variant="operations-workbench"
    />
  );
}
