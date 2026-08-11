import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider, useToast } from "../src/components";

function ToastHarness() {
  const toast = useToast();
  return (
    <div>
      <button type="button" onClick={() => toast.success("操作成功")}>成功</button>
      <button type="button" onClick={() => toast.error("操作失败")}>失败</button>
      <button type="button" onClick={() => toast.info("提示信息")}>提示</button>
    </div>
  );
}

afterEach(() => {
  vi.useRealTimers();
});

describe("全局右上角弹幕提示", () => {
  it("显示不同类型消息并支持手动关闭", () => {
    render(
      <ToastProvider>
        <ToastHarness />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "失败" }));
    expect(screen.getByRole("alert")).toHaveTextContent("操作失败");
    expect(screen.getByTestId("toast-viewport")).toHaveClass("toast-viewport");

    fireEvent.click(screen.getByRole("button", { name: "关闭提示" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("自动移除过期消息，并限制同时显示数量", () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <ToastHarness />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "成功" }));
    fireEvent.click(screen.getByRole("button", { name: "失败" }));
    fireEvent.click(screen.getByRole("button", { name: "提示" }));
    fireEvent.click(screen.getByRole("button", { name: "成功" }));
    expect(document.querySelectorAll(".toast")).toHaveLength(3);

    act(() => {
      vi.advanceTimersByTime(3600);
    });
    expect(screen.queryByTestId("toast-viewport")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
