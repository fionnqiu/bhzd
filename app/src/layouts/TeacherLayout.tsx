import { BarChart3, ClipboardList, LayoutDashboard, Users } from "lucide-react";
import ShellLayout, { type NavItem } from "./ShellLayout";
import "../pages/teacher/teacher-workbench.css";

/** 教师端导航按日常工作顺序排列，避免侧栏再出现分类标签。 */
const NAV_ITEMS: NavItem[] = [
  { to: "/teacher", label: "工作台", icon: LayoutDashboard, end: true },
  { to: "/teacher/classes", label: "班级管理", icon: Users },
  { to: "/teacher/tasks", label: "任务发布", icon: ClipboardList },
  { to: "/teacher/analytics", label: "学情分析", icon: BarChart3 },
];

/** 教师端壳（teacher/content_admin/system_admin 可进，路由守卫控制）。 */
export default function TeacherLayout() {
  return (
    <ShellLayout
      portalKey="teacher"
      portalName="教师端"
      navItems={NAV_ITEMS}
      variant="operations-workbench"
    />
  );
}
