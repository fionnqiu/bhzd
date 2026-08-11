/**
 * Shared Agent presentation tests.
 *
 * The stream layer is responsible for sanitizing input before it reaches these
 * primitives. These checks keep the public surface constrained to reviewed
 * lifecycle labels and a collapsible task projection.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentTaskList, AgentThinkingReasoning } from "../src/components/agent/AgentPresentation";

describe("共享 Agent 展示组件", () => {
  it("执行清单可折叠和展开，并保留可读的完成与进行中状态", () => {
    render(
      <AgentTaskList
        testId="shared-task-list"
        title="今天的练习路径"
        steps={[
          { id: "done", title: "回顾 BIO 标注规则", status: "completed" },
          { id: "active", title: "完成边界练习", status: "running" },
        ]}
      />,
    );

    const taskList = screen.getByTestId("shared-task-list");
    const toggle = within(taskList).getByRole("button");
    const fold = taskList.querySelector<HTMLElement>(".agent-task-list-fold");
    if (!fold) throw new Error("shared task list must provide a collapsible content region");

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(fold).toHaveAttribute("aria-hidden", "false");
    expect(taskList.querySelector(".agent-task-list-item.is-done")).toHaveTextContent(
      "回顾 BIO 标注规则",
    );
    expect(taskList.querySelector(".agent-task-list-item.is-active")).toHaveTextContent(
      "完成边界练习",
    );

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(fold).toHaveAttribute("aria-hidden", "true");

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(fold).toHaveAttribute("aria-hidden", "false");
  });

  it("只呈现受控生命周期状态，不自行生成模型思考文本", () => {
    // The marker represents content that must remain in a private model trace.
    // The public component receives only a reviewed lifecycle label and has no
    // secondary details region unless its caller deliberately supplies safe UI.
    const privateTrace = "PRIVATE_REASONING: choose hidden tool arguments";
    render(
      <AgentThinkingReasoning
        testId="safe-agent-thinking"
        label="正在整理学习目标"
        phase="preparing"
      />,
    );

    const status = screen.getByTestId("safe-agent-thinking");
    expect(status).toHaveAttribute("role", "status");
    expect(status).toHaveTextContent("正在整理学习目标");
    expect(status).not.toHaveTextContent(privateTrace);
    expect(status.querySelector(".agent-thinking-fold")).toBeNull();
  });
});
