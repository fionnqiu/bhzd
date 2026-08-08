import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { Database, SearchCheck } from "lucide-react";
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

  it("collapses the desktop student rail while retaining its account footer semantics", async () => {
    stubViewport(false);
    renderWorkbenchShell();

    const shell = document.querySelector<HTMLElement>(".shell");
    const sidebar = document.getElementById("shell-sidebar");
    const collapseButton = screen.getByRole("button", { name: "收起导航" });
    const accountTrigger = screen.getByRole("button", { name: "打开个人菜单" });

    expect(shell).not.toBeNull();
    expect(sidebar).toContainElement(document.querySelector(".student-workbench-account-footer"));
    expect(collapseButton).toHaveAttribute("aria-controls", "shell-sidebar");
    expect(collapseButton).toHaveAttribute("aria-expanded", "true");
    expect(accountTrigger).toHaveAttribute("aria-expanded", "false");
    expect(accountTrigger).toHaveTextContent("Test student");

    fireEvent.click(collapseButton);

    expect(shell).toHaveClass("student-workbench-sidebar-collapsed");
    expect(shell).toHaveAttribute("data-student-workbench-collapsed", "true");
    expect(screen.getByRole("button", { name: "展开导航" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );

    fireEvent.click(accountTrigger);
    await waitFor(() => expect(accountTrigger).toHaveAttribute("aria-expanded", "true"));
    expect(await screen.findByRole("button", { name: "退出登录" })).toBeInTheDocument();
  });
});

describe("ShellLayout operations workbench navigation", () => {
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
    expect(screen.getByRole("button", { name: "展开导航" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );

    fireEvent.click(screen.getByRole("button", { name: "打开个人菜单" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "退出登录" })).toBeInTheDocument(),
    );
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
