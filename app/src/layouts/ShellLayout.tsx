import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  ChevronDown,
  LogOut,
  Menu,
  PanelLeft,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { isTopmostFocusTrap, useFocusTrap } from "../components/useFocusTrap";
import { usePresence } from "../components/usePresence";
import { DesktopSidebarContext } from "./DesktopSidebarContext";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** 精确匹配（index 路由必须 true，否则父路径常驻激活态） */
  end?: boolean;
  /** Optional visible grouping label for dense operations navigation. */
  section?: string;
}

/** 门户定义：顶栏门户切换器的数据源（按角色过滤展示） */
export interface PortalDef {
  key: string;
  name: string;
  path: string;
  roles: string[];
}

export const PORTALS: PortalDef[] = [
  // Administrators retain the student portal for support; teachers use the dedicated teacher portal.
  {
    key: "student",
    name: "学生端",
    path: "/",
    roles: ["student", "system_admin"],
  },
  {
    key: "teacher",
    name: "教师端",
    path: "/teacher",
    roles: ["teacher", "system_admin"],
  },
  // rag-admin 门户入口已从切换器移除：RAG 知识库管理已并入 /admin，
  // system_admin 用户直接通过系统管理端侧边栏访问，无需独立门户切换。
  { key: "admin", name: "系统管理", path: "/admin", roles: ["system_admin"] },
];

const ROLE_NAMES: Record<string, string> = {
  student: "学生",
  teacher: "教师",
  system_admin: "系统管理员",
};

const COMPACT_SIDEBAR_QUERY = "(max-width: 900px)";

function compactSidebarMatches(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(COMPACT_SIDEBAR_QUERY).matches
  );
}

export interface ShellLayoutProps {
  /** 当前门户 key（用于切换器高亮） */
  portalKey: string;
  /** 侧栏顶部展示的门户名（如"教师端"） */
  portalName: string;
  navItems: NavItem[];
  /** Optional contextual content rendered above the shared route navigation. */
  sidebarContext?: ReactNode;
  /** Opt-in visual skin; default keeps the legacy portal shell unchanged. */
  variant?: "default" | "student-workbench" | "operations-workbench";
  /** Student-only content that follows the shared route navigation. */
  studentWorkbenchSidebar?: ReactNode;
  /** Student-only primary action that sits between the brand and route navigation. */
  studentWorkbenchSidebarTop?: ReactNode;
  /** Student-only actions fixed to the viewport without reserving page layout space. */
  studentWorkbenchFloatingActions?: ReactNode;
  /** Increments when workbench content completes an action that should dismiss the compact drawer. */
  studentWorkbenchCloseRequest?: number;
  /** Prevents student route/portal switches while Cockpit owns an active SSE run. */
  studentWorkbenchNavigationDisabled?: boolean;
}

/**
 * 四端共用壳：侧边导航 + 内容区。
 * 抽共享壳的原因：四个端布局只有导航项/门户名/侧栏槽位不同，复制四份
 * 骨架代码只会让窄屏抽屉、账户菜单等交互修复做四遍（NF17 响应式收敛于此）。
 */
export default function ShellLayout({
  portalKey,
  portalName,
  navItems,
  sidebarContext,
  variant = "default",
  studentWorkbenchSidebar,
  studentWorkbenchSidebarTop,
  studentWorkbenchFloatingActions,
  studentWorkbenchCloseRequest,
  studentWorkbenchNavigationDisabled = false,
}: ShellLayoutProps) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [openMenu, setOpenMenu] = useState<"user" | null>(null);
  const [compactSidebar, setCompactSidebar] = useState(compactSidebarMatches);
  const sidebarRef = useRef<HTMLElement>(null);
  const sidebarToggleRef = useRef<HTMLButtonElement>(null);
  const desktopSidebarExpandRef = useRef<HTMLButtonElement>(null);
  const sidebarWasOpenRef = useRef(false);
  const accountMenuRef = useRef<HTMLDivElement>(null);
  const handledWorkbenchCloseRequestRef = useRef(studentWorkbenchCloseRequest);
  const sidebarPresence = usePresence(sidebarOpen);
  const userMenuPresence = usePresence(openMenu === "user");
  const [workbenchSidebarCollapsed, setWorkbenchSidebarCollapsed] = useState(false);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mediaQuery = window.matchMedia(COMPACT_SIDEBAR_QUERY);
    const syncCompactSidebar = () => setCompactSidebar(mediaQuery.matches);

    syncCompactSidebar();
    mediaQuery.addEventListener("change", syncCompactSidebar);
    return () => mediaQuery.removeEventListener("change", syncCompactSidebar);
  }, []);

  useEffect(() => {
    if (handledWorkbenchCloseRequestRef.current === studentWorkbenchCloseRequest) return;
    handledWorkbenchCloseRequestRef.current = studentWorkbenchCloseRequest;
    // Slot content cannot access the drawer state directly.  Consume its close
    // request only for the compact shell so desktop navigation remains fixed.
    if (compactSidebar) setSidebarOpen(false);
  }, [compactSidebar, studentWorkbenchCloseRequest]);

  useEffect(() => {
    if (!compactSidebar || !sidebarOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && sidebarRef.current && isTopmostFocusTrap(sidebarRef.current)) {
        event.preventDefault();
        setSidebarOpen(false);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [compactSidebar, sidebarOpen]);

  useEffect(() => {
    if (compactSidebar && sidebarOpen) sidebarRef.current?.focus({ preventScroll: true });
  }, [compactSidebar, sidebarOpen]);

  useEffect(() => {
    if (compactSidebar && !sidebarOpen && sidebarWasOpenRef.current) {
      sidebarToggleRef.current?.focus({ preventScroll: true });
    }
    sidebarWasOpenRef.current = sidebarOpen;
  }, [compactSidebar, sidebarOpen]);

  useFocusTrap(sidebarRef, compactSidebar && sidebarOpen);

  // 点击下拉外部时收起（无全局监听库，原生实现即可）
  useEffect(() => {
    if (!openMenu) return;
    const onClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (!(accountMenuRef.current?.contains(target) ?? false)) {
        setOpenMenu(null);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [openMenu]);

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  const availablePortals = PORTALS.filter((p) => user && p.roles.includes(user.role));
  const sidebarId = "shell-sidebar";
  const isStudentWorkbench = variant === "student-workbench";
  const isOperationsWorkbench = variant === "operations-workbench";
  // Normal student routes receive shared page breathing room; Cockpit owns its
  // own transcript/header spacing so the fixed Composer can use the full height.
  const isStudentCockpitRoute = isStudentWorkbench && location.pathname === "/";
  const isWorkbench = isStudentWorkbench || isOperationsWorkbench;
  const hasStudentWorkbench = Boolean(studentWorkbenchSidebar || studentWorkbenchSidebarTop);
  const desktopWorkbenchSidebarCollapsed =
    isWorkbench && !compactSidebar && workbenchSidebarCollapsed;
  const desktopStudentSidebarCollapsed = isStudentWorkbench && desktopWorkbenchSidebarCollapsed;
  const desktopOperationsSidebarCollapsed =
    isOperationsWorkbench && desktopWorkbenchSidebarCollapsed;
  const portalHomePath = PORTALS.find((portal) => portal.key === portalKey)?.path ?? "/";
  const sidebarIsHidden = (compactSidebar && !sidebarOpen) || desktopWorkbenchSidebarCollapsed;
  const showPageHeaderSidebarExpand = desktopWorkbenchSidebarCollapsed && !isStudentCockpitRoute;
  const desktopSidebarContextValue = useMemo(
    () => ({
      showExpandControl: showPageHeaderSidebarExpand,
      sidebarId,
      expandDesktopSidebar: () => setWorkbenchSidebarCollapsed(false),
    }),
    [showPageHeaderSidebarExpand, sidebarId],
  );

  useEffect(() => {
    // The collapse trigger is removed with the rail, so preserve keyboard
    // continuity on the session route, whose title is not a shared PageHeader.
    if (desktopWorkbenchSidebarCollapsed && isStudentCockpitRoute) {
      desktopSidebarExpandRef.current?.focus({ preventScroll: true });
    }
  }, [desktopWorkbenchSidebarCollapsed, isStudentCockpitRoute]);

  const closeCompactSidebar = () => {
    if (compactSidebar) setSidebarOpen(false);
  };

  const renderAccountMenu = () => (
    <div className="dropdown-menu" data-motion-state={userMenuPresence.motionState}>
      <div className="dropdown-item" style={{ cursor: "default" }}>
        <div>
          <div>{user?.name}</div>
          <div className="text-xs text-muted">
            {user?.email} · {ROLE_NAMES[user?.role ?? ""] ?? user?.role}
          </div>
        </div>
      </div>
      {portalKey === "student" ? (
        <>
          <div className="dropdown-divider" />
          <Link
            to="/profile"
            className="dropdown-item"
            aria-disabled={studentWorkbenchNavigationDisabled || undefined}
            tabIndex={studentWorkbenchNavigationDisabled ? -1 : undefined}
            onClick={(event) => {
              if (studentWorkbenchNavigationDisabled) {
                event.preventDefault();
                return;
              }
              setOpenMenu(null);
              closeCompactSidebar();
            }}
          >
            <UserRound size={14} /> 个人中心
          </Link>
        </>
      ) : null}
      {availablePortals.length > 1 ? (
        <>
          <div className="dropdown-divider" />
          <div className="dropdown-item text-xs text-muted" style={{ cursor: "default" }}>
            切换端口
          </div>
          {availablePortals.map((portal) => (
            <Link
              key={portal.key}
              to={portal.path}
              className={["dropdown-item", portal.key === portalKey ? "current" : ""]
                .filter(Boolean)
                .join(" ")}
              onClick={(event) => {
                if (isStudentWorkbench && studentWorkbenchNavigationDisabled) {
                  event.preventDefault();
                  return;
                }
                setOpenMenu(null);
                closeCompactSidebar();
              }}
            >
              {portal.name}
            </Link>
          ))}
        </>
      ) : null}
      <div className="dropdown-divider" />
      <button
        className="dropdown-item"
        disabled={isStudentWorkbench && studentWorkbenchNavigationDisabled}
        onClick={handleLogout}
      >
        <LogOut size={14} /> 退出登录
      </button>
    </div>
  );

  const navigation = navItems.reduce<ReactNode[]>((items, item, index) => {
    if (item.section && (index === 0 || navItems[index - 1]?.section !== item.section)) {
      items.push(
        <div key={`section-${item.section}`} className="sidebar-nav-section" aria-hidden>
          {item.section}
        </div>,
      );
    }
    items.push(
      <NavLink
        key={item.to}
        to={item.to}
        end={item.end}
        aria-disabled={isStudentWorkbench && studentWorkbenchNavigationDisabled ? true : undefined}
        tabIndex={isStudentWorkbench && studentWorkbenchNavigationDisabled ? -1 : undefined}
        onClick={(event) => {
          if (isStudentWorkbench && studentWorkbenchNavigationDisabled) {
            event.preventDefault();
            return;
          }
          setOpenMenu(null);
          closeCompactSidebar();
        }}
      >
        <item.icon size={18} aria-hidden />
        <span>{item.label}</span>
      </NavLink>,
    );
    return items;
  }, []);

  // The variant is a styling hook only; navigation, menus, and focus behavior stay shared.
  return (
    <DesktopSidebarContext.Provider value={desktopSidebarContextValue}>
      <div
        className={[
          "shell",
          sidebarOpen ? "sidebar-open" : "",
          isStudentWorkbench ? "student-workbench-shell" : "",
          isOperationsWorkbench ? "operations-workbench-shell" : "",
          desktopWorkbenchSidebarCollapsed ? "workbench-sidebar-collapsed" : "",
          desktopStudentSidebarCollapsed ? "student-workbench-sidebar-collapsed" : "",
          desktopOperationsSidebarCollapsed ? "operations-workbench-sidebar-collapsed" : "",
        ]
          .filter(Boolean)
          .join(" ")}
        data-shell-variant={variant}
        data-student-workbench-collapsed={desktopStudentSidebarCollapsed || undefined}
        data-operations-workbench-collapsed={desktopOperationsSidebarCollapsed || undefined}
      >
      {sidebarPresence.isPresent ? (
        <div
          className="sidebar-overlay"
          data-motion-state={sidebarPresence.motionState}
          onClick={() => setSidebarOpen(false)}
        />
      ) : null}
      {/* An off-canvas sidebar remains mounted for its slide animation, so it
          becomes inert until the compact navigation is intentionally opened. */}
      <aside
        id={sidebarId}
        className={[
          "sidebar",
          isStudentWorkbench ? "student-workbench-navigation" : "",
          isOperationsWorkbench ? "operations-workbench-navigation" : "",
          hasStudentWorkbench ? "sidebar-has-student-workbench" : "",
        ]
          .filter(Boolean)
          .join(" ")}
        ref={sidebarRef}
        data-focus-trap={compactSidebar && sidebarOpen ? "active" : undefined}
        aria-hidden={sidebarIsHidden || undefined}
        inert={sidebarIsHidden}
        tabIndex={-1}
      >
        {isWorkbench ? (
          <div
            className={[
              "workbench-sidebar-header",
              isStudentWorkbench ? "student-workbench-sidebar-header" : "",
              isOperationsWorkbench ? "operations-workbench-sidebar-header" : "",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            <Link
              className={[
                "sidebar-brand",
                "workbench-brand",
                isStudentWorkbench ? "student-workbench-brand" : "",
                isOperationsWorkbench ? "operations-workbench-brand" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              to={portalHomePath}
              aria-label={`${portalName}首页`}
            >
              <span className="sidebar-brand-mark">标</span>
              <span
                className={[
                  "workbench-brand-copy",
                  isStudentWorkbench ? "student-workbench-brand-copy" : "",
                  isOperationsWorkbench ? "operations-workbench-brand-copy" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
              >
                {isStudentWorkbench ? "标航智导" : portalName}
              </span>
            </Link>
            {!compactSidebar && !desktopWorkbenchSidebarCollapsed ? (
              <button
                type="button"
                className={[
                  "icon-btn",
                  "workbench-sidebar-collapse",
                  isStudentWorkbench ? "student-workbench-sidebar-collapse" : "",
                  isOperationsWorkbench ? "operations-workbench-sidebar-collapse" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                aria-label={desktopWorkbenchSidebarCollapsed ? "展开导航" : "收起导航"}
                aria-controls={sidebarId}
                aria-expanded={!desktopWorkbenchSidebarCollapsed}
                onClick={() => setWorkbenchSidebarCollapsed((current) => !current)}
              >
                <PanelLeft size={18} aria-hidden />
              </button>
            ) : null}
          </div>
        ) : (
          <div className="sidebar-brand">
            <span className="sidebar-brand-mark">标</span>
            标航智导
          </div>
        )}
        <div className="sidebar-portal">{portalName}</div>
        {sidebarContext ? (
          <div className="sidebar-context">
            <div className="sidebar-context-main">{sidebarContext}</div>
          </div>
        ) : null}
        {studentWorkbenchSidebarTop ? (
          <div className="student-workbench-sidebar-top">{studentWorkbenchSidebarTop}</div>
        ) : null}
        {/* The navigation and conversation history intentionally share this single
            scroll surface. The new-session control and account menu remain
            outside it, so they are reachable even for a long history. */}
        <div className="sidebar-scroll-region">
          <nav className="sidebar-nav" aria-label={portalName}>
            {navigation}
          </nav>
          {studentWorkbenchSidebar ? (
            <div className="student-workbench-sidebar">{studentWorkbenchSidebar}</div>
          ) : null}
        </div>
        <div
          className={[
            "sidebar-footer",
            "workbench-account-footer",
            isStudentWorkbench ? "student-workbench-account-footer" : "",
            isOperationsWorkbench ? "operations-workbench-account-footer" : "",
          ]
            .filter(Boolean)
            .join(" ")}
        >
          <div
            className={[
              "dropdown",
              "workbench-account-menu",
              isStudentWorkbench ? "student-workbench-account-menu" : "",
              isOperationsWorkbench ? "operations-workbench-account-menu" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            ref={accountMenuRef}
          >
            <button
              type="button"
              className={[
                "workbench-account-trigger",
                isStudentWorkbench ? "student-workbench-account-trigger" : "",
                isOperationsWorkbench ? "operations-workbench-account-trigger" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              aria-label="打开个人菜单"
              aria-expanded={openMenu === "user"}
              disabled={isStudentWorkbench && studentWorkbenchNavigationDisabled}
              onClick={() => setOpenMenu(openMenu === "user" ? null : "user")}
            >
              <span
                className={[
                  "workbench-account-avatar",
                  isStudentWorkbench ? "student-workbench-account-avatar" : "",
                  isOperationsWorkbench ? "operations-workbench-account-avatar" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                aria-hidden
              >
                <UserRound size={17} />
              </span>
              <span
                className={[
                  "workbench-account-copy",
                  isStudentWorkbench ? "student-workbench-account-copy" : "",
                  isOperationsWorkbench ? "operations-workbench-account-copy" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
              >
                <span
                  className={[
                    "workbench-account-name",
                    isStudentWorkbench ? "student-workbench-account-name" : "",
                    isOperationsWorkbench ? "operations-workbench-account-name" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                >
                  {user?.name ?? (isStudentWorkbench ? "学生" : "用户")}
                </span>
                <span
                  className={[
                    "workbench-account-role",
                    isStudentWorkbench ? "student-workbench-account-role" : "",
                    isOperationsWorkbench ? "operations-workbench-account-role" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                >
                  {ROLE_NAMES[user?.role ?? ""] ??
                    user?.role ??
                    (isStudentWorkbench ? "学生" : "用户")}
                </span>
              </span>
              <ChevronDown size={15} aria-hidden />
            </button>
            {userMenuPresence.isPresent && !studentWorkbenchNavigationDisabled
              ? renderAccountMenu()
              : null}
          </div>
        </div>
      </aside>

      <div className="main">
        {desktopWorkbenchSidebarCollapsed && isStudentCockpitRoute ? (
          <button
            type="button"
            className={[
              "icon-btn",
              "workbench-sidebar-expand",
              isStudentWorkbench ? "student-workbench-sidebar-expand" : "",
              isOperationsWorkbench ? "operations-workbench-sidebar-expand" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            aria-label="展开导航"
            aria-controls={sidebarId}
            aria-expanded={false}
            title="展开导航"
            ref={desktopSidebarExpandRef}
            onClick={() => setWorkbenchSidebarCollapsed(false)}
          >
            <PanelLeft size={20} aria-hidden />
          </button>
        ) : null}
        <button
          className="icon-btn shell-mobile-nav-toggle"
          aria-label={sidebarOpen ? "关闭导航" : "打开导航"}
          aria-controls={sidebarId}
          aria-expanded={sidebarOpen}
          ref={sidebarToggleRef}
          onClick={() => setSidebarOpen((current) => !current)}
        >
          <Menu size={20} />
        </button>
        {isStudentWorkbench && studentWorkbenchFloatingActions ? (
          // The notification must remain globally reachable without creating a
          // page-level toolbar or reducing the Cockpit's usable conversation height.
          <div
            className={[
              "student-workbench-floating-actions",
              isStudentCockpitRoute ? "student-workbench-cockpit-actions" : "",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            {studentWorkbenchFloatingActions}
          </div>
        ) : null}
        <main
          className={[
            "main-content",
            // Student routes share one main-content contract; Cockpit adds a
            // dedicated class so its transcript can scroll beside a fixed Composer.
            isStudentWorkbench ? "student-workbench-main-content" : "",
            isStudentCockpitRoute ? "student-workbench-cockpit-main-content" : "",
            isOperationsWorkbench ? "operations-workbench-main-content" : "",
          ]
            .filter(Boolean)
            .join(" ")}
        >
          <Outlet />
        </main>
      </div>
      </div>
    </DesktopSidebarContext.Provider>
  );
}
