import { act, fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Drawer from "../src/components/Drawer";
import ConfirmDialog from "../src/components/ConfirmDialog";
import Modal from "../src/components/Modal";
import Tabs from "../src/components/Tabs";
import { ToastProvider, useToast } from "../src/components/Toast";
import { MOTION_EXIT_MS } from "../src/components/usePresence";

function ModalHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open modal
      </button>
      <Modal open={open} title={open ? "Confirm action" : ""} onClose={() => setOpen(false)}>
        {open ? <p>Retained dialog content</p> : null}
      </Modal>
    </>
  );
}

function DrawerHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open drawer
      </button>
      <Drawer open={open} title={open ? "Details" : ""} onClose={() => setOpen(false)}>
        {open ? <p>Retained drawer content</p> : null}
      </Drawer>
    </>
  );
}

function NestedDialogHarness() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setDrawerOpen(true)}>
        Open nested drawer
      </button>
      <Drawer open={drawerOpen} title="Parent drawer" onClose={() => setDrawerOpen(false)}>
        <button type="button" onClick={() => setConfirmOpen(true)}>
          Open nested confirmation
        </button>
        <ConfirmDialog
          open={confirmOpen}
          title="Nested confirmation"
          onConfirm={() => setConfirmOpen(false)}
          onCancel={() => setConfirmOpen(false)}
        />
      </Drawer>
    </>
  );
}

function ToastHarness() {
  const toast = useToast();
  return (
    <button type="button" onClick={() => toast.success("Saved")}>
      Show toast
    </button>
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("shared interaction presence", () => {
  it("keeps a closing modal mounted, preserves its content, and restores focus", () => {
    vi.useFakeTimers();
    render(<ModalHarness />);

    const trigger = screen.getByRole("button", { name: "Open modal" });
    trigger.focus();
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "Confirm action" });
    expect(dialog).toHaveFocus();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(dialog).toHaveAttribute("data-motion-state", "closing");
    expect(screen.getByText("Retained dialog content")).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(MOTION_EXIT_MS));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("keeps a drawer mounted through an overlay dismissal", () => {
    vi.useFakeTimers();
    render(<DrawerHarness />);

    fireEvent.click(screen.getByRole("button", { name: "Open drawer" }));
    const dialog = screen.getByRole("dialog", { name: "Details" });
    const overlay = document.querySelector(".drawer-overlay");
    if (!overlay) throw new Error("drawer overlay must render with an open drawer");

    fireEvent.click(overlay);
    expect(dialog).toHaveAttribute("data-motion-state", "closing");
    expect(screen.getByText("Retained drawer content")).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(MOTION_EXIT_MS));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps Tab navigation inside a modal while it is present", () => {
    render(<ModalHarness />);

    fireEvent.click(screen.getByRole("button", { name: "Open modal" }));
    const dialog = screen.getByRole("dialog", { name: "Confirm action" });
    const closeButton = screen.getByRole("button", { name: "关闭" });
    expect(dialog).toHaveFocus();

    fireEvent.keyDown(window, { key: "Tab" });
    expect(closeButton).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(closeButton).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(closeButton).toHaveFocus();
  });

  it("lets only the topmost nested dialog respond to Escape", () => {
    render(<NestedDialogHarness />);

    fireEvent.click(screen.getByRole("button", { name: "Open nested drawer" }));
    fireEvent.click(screen.getByRole("button", { name: "Open nested confirmation" }));
    const drawer = screen.getByRole("dialog", { name: "Parent drawer" });
    const confirmation = screen.getByRole("dialog", { name: "Nested confirmation" });

    fireEvent.keyDown(window, { key: "Escape" });
    expect(confirmation).toHaveAttribute("data-motion-state", "closing");
    expect(drawer).toHaveAttribute("data-motion-state", "open");
  });

  it("keeps the toast API compatible without rendering a top-right notice", () => {
    render(
      <ToastProvider>
        <ToastHarness />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Show toast" }));
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
    expect(document.querySelector(".toast-container")).not.toBeInTheDocument();
  });

  it("removes a closing surface immediately when the system requests reduced motion", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({
        matches: true,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    );
    const { rerender } = render(
      <Modal open title="Reduced motion" onClose={() => {}}>
        <p>Static close</p>
      </Modal>,
    );

    rerender(
      <Modal open={false} title="Reduced motion" onClose={() => {}}>
        <p>Static close</p>
      </Modal>,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps tab state changes synchronous while CSS supplies the visual transition", () => {
    const onChange = vi.fn();
    render(
      <Tabs
        active="overview"
        onChange={onChange}
        tabs={[
          { key: "overview", label: "Overview" },
          { key: "history", label: "History" },
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "History" }));
    expect(onChange).toHaveBeenCalledWith("history");
  });

  it("keeps tabs in one horizontal row and every command button on one line", () => {
    // Source-level assertions protect the shared CSS contract even though
    // jsdom cannot calculate overflow or line wrapping from a real viewport.
    const css = readFileSync("src/index.css", "utf8");

    expect(css).toMatch(/button\s*\{[^}]*white-space:\s*nowrap;/s);
    expect(css).toMatch(/\.tabs\s*\{[^}]*flex-wrap:\s*nowrap;[^}]*overflow-x:\s*auto;/s);
    expect(css).toMatch(/\.tab\s*\{[^}]*flex:\s*0\s+0\s+auto;[^}]*white-space:\s*nowrap;/s);
  });
});
