import { Cpu, Database, ScrollText, ShieldCheck, SlidersHorizontal, Upload, UserCog } from "lucide-react";
import ShellLayout, { type NavItem } from "./ShellLayout";

/**
 * 系统管理端导航保持为单一列表。
 * 管理配置与知识库操作属于同一管理员工作流，去掉分组标题可以减少
 * 分类跳转和重复认知；入口顺序与权限边界仍由 ShellLayout 保持不变。
 */
const NAV_ITEMS: NavItem[] = [
  { to: "/admin/providers", label: "模型供应商", icon: Cpu },
  { to: "/admin/rag-settings", label: "RAG 参数", icon: SlidersHorizontal },
  { to: "/admin/users", label: "用户管理", icon: UserCog },
  { to: "/admin/security", label: "安全配置", icon: ShieldCheck },
  { to: "/admin/audit-logs", label: "审计日志", icon: ScrollText },
  { to: "/admin/rag", label: "资料库", icon: Database, end: true },
  { to: "/admin/rag/upload", label: "上传资料", icon: Upload },
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
