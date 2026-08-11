import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { Database, SearchCheck } from "lucide-react";
import { PageHeader } from "../src/components";
import AdminLayout from "../src/layouts/AdminLayout";
import ShellLayout from "../src/layouts/ShellLayout";
import {
  StudentWorkbenchShellProvider,
  useStudentWorkbenchShell,
  useStudentWorkbenchSidebarClose,
  useStudentWorkbenchSidebarTop,
} from "../src/layouts/StudentWorkbenchShellContext";

vi.mock("../src/auth/AuthContext", () => ({
  useAuth: () => ({
    user: {
      id: "student-1",
      email: "student@example.com",
      name: "Test student",
      role: "student",
      email_verified: true,
    },
    logout: vi.fn(),
  }),
}));

/** Sets the responsive shell mode without relying on CSS media queries in jsdom. */
function stubViewport(compact: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({
      matches: compact,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  );
}

/** Bridges the provider-owned workbench slots to the shared shell under test. */
function WorkbenchShellLayout() {
  const { studentWorkbenchSidebar, studentWorkbenchSidebarTop, studentWorkbenchCloseRequest } =
    useStudentWorkbenchShell();

  return (
    <ShellLayout
      portalKey="student"
      portalName="Student portal"
      navItems={[]}
      variant="student-workbench"
      studentWorkbenchSidebar={studentWorkbenchSidebar}
      studentWorkbenchSidebarTop={studentWorkbenchSidebarTop}
      studentWorkbenchCloseRequest={studentWorkbenchCloseRequest}
    />
  );
}

/** Registers a representative sidebar action that asks the compact drawer to close. */
function WorkbenchSlotCloseAction() {
  const setStudentWorkbenchSidebarTop = useStudentWorkbenchSidebarTop();
  const requestStudentWorkbenchSidebarClose = useStudentWorkbenchSidebarClose();

  useEffect(() => {
    setStudentWorkbenchSidebarTop(
      <button type="button" onClick={requestStudentWorkbenchSidebarClose}>
        Close compact workbench navigation
      </button>,
    );
    return () => setStudentWorkbenchSidebarTop(null);
  }, [requestStudentWorkbenchSidebarClose, setStudentWorkbenchSidebarTop]);

  return null;
}

function renderWorkbenchShell(child = <></>) {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <StudentWorkbenchShellProvider>
        <Routes>
          <Route path="/" element={<WorkbenchShellLayout />}>
            <Route index element={child} />
          </Route>
        </Routes>
      </StudentWorkbenchShellProvider>
    </MemoryRouter>,
  );
}

/** Exercises the employee shell without importing a role-specific layout module. */
function renderOperationsShell(compact = false) {
  stubViewport(compact);
  return render(
    <MemoryRouter initialEntries={["/rag-admin/search-test"]}>
      <Routes>
        <Route
          element={
            <ShellLayout
              portalKey="rag-admin"
              portalName="RAG 知识库管理"
              variant="operations-workbench"
              navItems={[
                { to: "/rag-admin", label: "资料库", icon: Database, end: true, section: "资料管理" },
                {
                  to: "/rag-admin/search-test",
                  label: "召回测试",
                  icon: SearchCheck,
                  section: "检索与质量",
                },
              ]}
            />
          }
        >
          <Route
            path="/rag-admin/search-test"
            element={<PageHeader title="召回测试" sub="验证知识库召回结果与排序质量" />}
          />
          <Route
            path="/rag-admin"
            element={<PageHeader title="资料库" sub="管理资料与发布状态" />}
          />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ShellLayout student workbench navigation", () => {
  it("exposes the mobile toggle state and its controlled sidebar", () => {
    stubViewport(true);
    renderWorkbenchShell();

    const toggle = screen.getByRole("button", { name: "打开导航" });
    const sidebar = document.getElementById("shell-sidebar");

    expect(sidebar).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-controls", "shell-sidebar");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(sidebar).toHaveAttribute("aria-hidden", "true");

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(sidebar).not.toHaveAttribute("aria-hidden", "true");
    expect(toggle).toHaveAccessibleName("关闭导航");
  });

  it("closes the compact drawer when a workbench slot requests it", async () => {
    stubViewport(true);
    renderWorkbenchShell(<WorkbenchSlotCloseAction />);

    const toggle = screen.getByRole("button", { name: "打开导航" });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(
      await screen.findByRole("button", { name: "Close compact workbench navigation" }),
    );

    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "false"));
  });

  it("fully hides the desktop student rail and restores it from the main-area control", () => {
    stubViewport(false);
    renderWorkbenchShell();

    const shell = document.querySelector<HTMLElement>(".shell");
    const sidebar = document.getElementById("shell-sidebar");
    const collapseButton = screen.getByRole("button", { name: "收起导航" });

    expect(shell).not.toBeNull();
    expect(sidebar).toContainElement(document.querySelector(".student-workbench-account-footer"));
    expect(collapseButton).toHaveAttribute("aria-controls", "shell-sidebar");
    expect(collapseButton).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(collapseButton);

    expect(shell).toHaveClass("student-workbench-sidebar-collapsed");
    expect(shell).toHaveAttribute("data-student-workbench-collapsed", "true");
    expect(sidebar).toHaveAttribute("aria-hidden", "true");

    const expandButton = screen.getByRole("button", { name: "展开导航" });
    expect(expandButton).toHaveAttribute("aria-controls", "shell-sidebar");
    expect(expandButton).toHaveAttribute("aria-expanded", "false");
    expect(expandButton).toHaveFocus();

    fireEvent.click(expandButton);

    expect(shell).not.toHaveClass("student-workbench-sidebar-collapsed");
    expect(sidebar).not.toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("button", { name: "收起导航" })).toBeInTheDocument();
  });
});

describe("ShellLayout operations workbench navigation", () => {
  it("renames the user navigation label without changing its route", () => {
    render(
      <MemoryRouter initialEntries={["/admin/users"]}>
        <Routes>
          <Route element={<AdminLayout />}>
            <Route path="/admin/users" element={<PageHeader title="用户管理" />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    const navigation = screen.getByRole("navigation", { name: "系统管理" });
    // The label is presentation-only; the existing route continues to carry
    // the server-enforced users permission contract.
    expect(within(navigation).getByRole("link", { name: "用户管理" })).toHaveAttribute(
      "href",
      "/admin/users",
    );
    expect(within(navigation).queryByRole("link", { name: "用户权限" })).not.toBeInTheDocument();
  });

  it("renders ungrouped navigation without a top bar or breadcrumb", async () => {
    renderOperationsShell();

    const shell = document.querySelector<HTMLElement>(".shell");
    const sidebar = document.getElementById("shell-sidebar");
    const collapseButton = screen.getByRole("button", { name: "收起导航" });

    expect(shell).toHaveAttribute("data-shell-variant", "operations-workbench");
    expect(sidebar).toHaveClass("operations-workbench-navigation");
    expect(screen.queryByText("资料管理")).not.toBeInTheDocument();
    expect(screen.queryByText("检索与质量")).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "当前位置" })).not.toBeInTheDocument();
    expect(screen.queryByRole("banner")).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "RAG 知识库管理" })).toHaveTextContent("召回测试");

    fireEvent.click(collapseButton);

    expect(shell).toHaveClass("operations-workbench-sidebar-collapsed");
    expect(shell).toHaveAttribute("data-operations-workbench-collapsed", "true");
    expect(sidebar).toHaveAttribute("aria-hidden", "true");

    const expandButton = screen.getByRole("button", { name: "展开导航" });
    expect(expandButton).toHaveAttribute("aria-controls", "shell-sidebar");
    expect(expandButton).toHaveAttribute("aria-expanded", "false");
    expect(expandButton).toHaveFocus();

    fireEvent.click(expandButton);

    expect(shell).not.toHaveClass("operations-workbench-sidebar-collapsed");
    expect(sidebar).not.toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("button", { name: "收起导航" })).toBeInTheDocument();
  });

  it("uses the shared compact drawer and closes it after navigation", () => {
    renderOperationsShell(true);

    const toggle = screen.getByRole("button", { name: "打开导航" });
    const sidebar = document.getElementById("shell-sidebar");

    expect(sidebar).toHaveAttribute("aria-hidden", "true");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(screen.getByRole("link", { name: "资料库" }));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});
