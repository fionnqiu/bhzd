import { Cpu, ScrollText, ShieldCheck, SlidersHorizontal, UserCog } from "lucide-react";
import ShellLayout, { type NavItem } from "./ShellLayout";

/** 系统管理端导航按高频操作排列，业务页面仍由原路由负责。 */
const NAV_ITEMS: NavItem[] = [
  { to: "/admin/providers", label: "模型供应商", icon: Cpu },
  { to: "/admin/rag-settings", label: "RAG 参数", icon: SlidersHorizontal },
  { to: "/admin/users", label: "用户权限", icon: UserCog },
  { to: "/admin/security", label: "安全配置", icon: ShieldCheck },
  { to: "/admin/audit-logs", label: "审计日志", icon: ScrollText },
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
