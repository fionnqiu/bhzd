import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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

describe("全局通知兼容 API", () => {
  it("保留页面调用器，同时不渲染会遮挡工作区的浮层", () => {
    render(
      <ToastProvider>
        <ToastHarness />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "失败" }));
    // ToastProvider is an API compatibility boundary. Persistent page states
    // own user feedback, so calls must never reintroduce a transient overlay.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByTestId("toast-viewport")).not.toBeInTheDocument();
  });

  it("repeated calls remain inert and do not create a hidden message queue", () => {
    render(
      <ToastProvider>
        <ToastHarness />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "成功" }));
    fireEvent.click(screen.getByRole("button", { name: "失败" }));
    fireEvent.click(screen.getByRole("button", { name: "提示" }));
    fireEvent.click(screen.getByRole("button", { name: "成功" }));
    expect(document.querySelectorAll(".toast")).toHaveLength(0);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
