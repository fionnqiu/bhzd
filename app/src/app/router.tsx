/**
 * 路由表与守卫（蓝图 §14 信息架构逐字实现）。
 *
 * 为什么把 routes 导出为数据而非只在组件里写 <Routes>：守卫行为需要
 * 无浏览器环境测试（tests/router.test.tsx 用 createMemoryRouter 复用同
 * 一份路由表），路由即数据可以让测试与生产共用唯一事实来源。
 */

import { lazy, Suspense, type ComponentType, type ReactNode } from "react";
import {
  createBrowserRouter,
  isRouteErrorResponse,
  Navigate,
  useLocation,
  useRouteError,
  type RouteObject,
} from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import type { Role } from "../api/types";
import { ErrorState, Spinner } from "../components";
import LegacyRagAdminRedirect from "./LegacyRagAdminRedirect";

/**
 * Each route keeps its own suspense boundary so an authenticated shell stays mounted while a
 * child page downloads.  This is intentionally a small wrapper instead of a single app-wide
 * boundary: a page transition should not blank the surrounding navigation.
 */
function lazyRoute(loader: () => Promise<{ default: ComponentType }>) {
  const RouteComponent = lazy(loader);
  return function LazyRouteComponent() {
    return (
      <Suspense fallback={<RouteLoading />}>
        <RouteComponent />
      </Suspense>
    );
  };
}

// Route modules remain outside the initial bundle; in particular, vis-network is only requested
// after a learner actually opens the graph page.
const StudentLayout = lazyRoute(() => import("../layouts/StudentLayout"));
const TeacherLayout = lazyRoute(() => import("../layouts/TeacherLayout"));
const AdminLayout = lazyRoute(() => import("../layouts/AdminLayout"));
const LoginPage = lazyRoute(() => import("../auth/LoginPage"));
const RegisterPage = lazyRoute(() => import("../auth/RegisterPage"));
const VerifyEmailPage = lazyRoute(() => import("../auth/VerifyEmailPage"));
const ForgotPasswordPage = lazyRoute(() => import("../auth/ForgotPasswordPage"));
const ResetPasswordPage = lazyRoute(() => import("../auth/ResetPasswordPage"));
const CockpitPage = lazyRoute(() => import("../pages/student/CockpitPage"));
const OnboardingPage = lazyRoute(() => import("../pages/student/OnboardingPage"));
const PresetsPage = lazyRoute(() => import("../pages/student/PresetsPage"));
const GraphPage = lazyRoute(() => import("../pages/student/GraphPage"));
const TasksPage = lazyRoute(() => import("../pages/student/TasksPage"));
const TaskDetailPage = lazyRoute(() => import("../pages/student/TaskDetailPage"));
const ProfilePage = lazyRoute(() => import("../pages/student/ProfilePage"));
const DashboardPage = lazyRoute(() => import("../pages/teacher/DashboardPage"));
const ClassesPage = lazyRoute(() => import("../pages/teacher/ClassesPage"));
const ClassDetailPage = lazyRoute(() => import("../pages/teacher/ClassDetailPage"));
const TasksManagePage = lazyRoute(() => import("../pages/teacher/TasksManagePage"));
const TaskPublishPage = lazyRoute(() => import("../pages/teacher/TaskPublishPage"));
const AnalyticsPage = lazyRoute(() => import("../pages/teacher/AnalyticsPage"));
const StudentAnalyticsPage = lazyRoute(() => import("../pages/teacher/StudentAnalyticsPage"));
const DocumentsPage = lazyRoute(() => import("../pages/rag/DocumentsPage"));
const UploadPage = lazyRoute(() => import("../pages/rag/UploadPage"));
const DocumentDetailPage = lazyRoute(() => import("../pages/rag/DocumentDetailPage"));
const LedgersPage = lazyRoute(() => import("../pages/rag/LedgersPage"));
const ProvidersPage = lazyRoute(() => import("../pages/admin/ProvidersPage"));
const RagSettingsPage = lazyRoute(() => import("../pages/admin/RagSettingsPage"));
const UsersPage = lazyRoute(() => import("../pages/admin/UsersPage"));
const SecurityPage = lazyRoute(() => import("../pages/admin/SecurityPage"));
const AuditLogsPage = lazyRoute(() => import("../pages/admin/AuditLogsPage"));
const ForbiddenPage = lazyRoute(() => import("../pages/system/ForbiddenPage"));
const NotFoundPage = lazyRoute(() => import("../pages/system/NotFoundPage"));

/** Visible, announced fallback while a route chunk is fetched instead of a blank content region. */
function RouteLoading() {
  return (
    <div
      className="loading-block"
      style={{ minHeight: "60vh" }}
      aria-live="polite"
      aria-busy="true"
    >
      <Spinner large /> 正在加载页面…
    </div>
  );
}

/**
 * React Router data routers render `errorElement` for render and lazy-import failures.  Keep the
 * message generic so an unavailable chunk or an unexpected exception never exposes internals.
 */
function RouteErrorBoundary() {
  const error = useRouteError();
  const message =
    isRouteErrorResponse(error) && error.status === 404
      ? "页面不存在或已被移除，请检查访问地址。"
      : "页面加载出现问题，请稍后重试。";

  return (
    <section
      className="loading-block"
      style={{ minHeight: "60vh" }}
      role="alert"
      aria-live="assertive"
    >
      <ErrorState message={message} onRetry={() => window.location.reload()} />
    </section>
  );
}

/** 会话引导中的等待态（守卫在拿到会话结果前不做任何重定向判断） */
function BootLoading() {
  return (
    <div className="loading-block" style={{ minHeight: "60vh" }}>
      <Spinner large /> 正在加载…
    </div>
  );
}

/** 登录守卫：未登录 → /login（携带来源路径，登录后原路返回） */
/** 角色守卫：先过登录，再校验角色；角色不足 → 403 页（蓝图 §14 守卫口径） */
function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user, bootstrapping } = useAuth();
  const location = useLocation();
  if (bootstrapping) return <BootLoading />;
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  if (!roles.includes(user.role)) return <ForbiddenPage />;
  return <>{children}</>;
}

const STAFF_ROLES: Role[] = ["teacher", "content_admin", "system_admin"];
// Teachers must use the teacher portal; administrators retain student-portal support access.
const STUDENT_PORTAL_ROLES: Role[] = ["student", "content_admin", "system_admin"];
// RAG management changes shared knowledge data, so only the system administrator may enter it.
const RAG_ADMIN_ROLES: Role[] = ["system_admin"];

/** 全站路由表（测试与生产共用） */
export const routes: RouteObject[] = [
  // ---- 公共认证页（/verify-email 保留为历史邮件链接的兼容落地页）
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },
  { path: "/verify-email", element: <VerifyEmailPage /> },
  { path: "/forgot-password", element: <ForgotPasswordPage /> },
  { path: "/reset-password", element: <ResetPasswordPage /> },
  // 旧入口兼容：/index 一律回首页
  { path: "/index", element: <Navigate to="/" replace /> },

  // ---- 学生壳（教师禁止进入；管理员保留支持与验收能力）
  {
    path: "/",
    element: (
      <RequireRole roles={STUDENT_PORTAL_ROLES}>
        <StudentLayout />
      </RequireRole>
    ),
    children: [
      { index: true, element: <CockpitPage /> },
      // 入学引导（v3.0 §11.1）：已登录学生可访问；门禁由 CockpitPage 的 useOnboardingGate 触发
      { path: "onboarding", element: <OnboardingPage /> },
      { path: "presets", element: <PresetsPage /> },
      { path: "graph", element: <GraphPage /> },
      { path: "tasks", element: <TasksPage /> },
      { path: "tasks/:id", element: <TaskDetailPage /> },
      // 诊断现已是 Agent 的内置能力；保留旧书签兼容入口，避免历史链接落到
      // 已下线的独立页面。replace 保证浏览器后退不会再次回到旧入口。
      { path: "diagnostics", element: <Navigate to="/" replace /> },
      // The student knowledge-QA board is retired.  Keep legacy links usable
      // by returning to the Agent workbench instead of leaving old bookmarks at a 404.
      { path: "rag-qa", element: <Navigate to="/" replace /> },
      { path: "profile", element: <ProfilePage /> },
    ],
  },

  // ---- 教师壳
  {
    path: "/teacher",
    element: (
      <RequireRole roles={STAFF_ROLES}>
        <TeacherLayout />
      </RequireRole>
    ),
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "classes", element: <ClassesPage /> },
      { path: "classes/:id", element: <ClassDetailPage /> },
      // Keep the directory and the long-running editor as separate routes so a refresh or a
      // copied edit link always returns to the same teacher workflow state.
      { path: "tasks", element: <TasksManagePage /> },
      { path: "tasks/new", element: <TaskPublishPage /> },
      { path: "tasks/:taskId", element: <TaskPublishPage /> },
      { path: "analytics", element: <AnalyticsPage /> },
      { path: "analytics/students", element: <StudentAnalyticsPage /> },
      // Keep old review bookmarks useful without retaining a review screen.
      {
        path: "review",
        element: (
          <RequireRole roles={RAG_ADMIN_ROLES}>
            <Navigate to="/admin/rag" replace />
          </RequireRole>
        ),
      },
    ],
  },

  // ---- 历史 RAG 管理地址（独立门户已删除）
  {
    path: "/rag-admin/*",
    element: (
      <RequireRole roles={RAG_ADMIN_ROLES}>
        <LegacyRagAdminRedirect />
      </RequireRole>
    ),
  },

  // ---- 系统管理壳（仅 system_admin；服务端另校验管理端会话 cookie）
  {
    path: "/admin",
    element: (
      <RequireRole roles={["system_admin"]}>
        <AdminLayout />
      </RequireRole>
    ),
    children: [
      { index: true, element: <Navigate to="/admin/providers" replace /> },
      { path: "providers", element: <ProvidersPage /> },
      { path: "rag-settings", element: <RagSettingsPage /> },
      { path: "users", element: <UsersPage /> },
      { path: "security", element: <SecurityPage /> },
      { path: "audit-logs", element: <AuditLogsPage /> },
      // RAG 知识库管理——从独立的 /rag-admin 壳迁入，路径统一为 /admin/rag/*
      { path: "rag", element: <DocumentsPage /> },
      { path: "rag/upload", element: <UploadPage /> },
      { path: "rag/documents/:id", element: <DocumentDetailPage /> },
      // Source provenance needs a first-class management destination so staff can
      // resolve authorization risks before they affect knowledge-base governance.
      { path: "rag/ledgers", element: <LedgersPage /> },
      // Keep previously shared console URLs usable without retaining a hidden page.
      { path: "rag/search-test", element: <Navigate to="/admin/rag" replace /> },
      // The legacy /rag-admin wildcard handles old document/chunk bookmarks.
    ],
  },

  { path: "*", element: <NotFoundPage /> },
].map((route) => ({
  ...route,
  // A top-level data-router boundary also catches failures from every child route module.
  errorElement: <RouteErrorBoundary />,
}));

const router = createBrowserRouter(routes);

export default router;
