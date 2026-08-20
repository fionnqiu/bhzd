/**
 * Shared Agent presentation tests.
 *
 * 对话页步骤流重做后，旧的共享执行/思考组件已下线，展示层只剩
 * AgentAvatar 这一助手身份元素。流式层仍负责在内容到达该基础组件前
 * 完成脱敏。
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentAvatar } from "../src/components/agent/AgentPresentation";

describe("共享 Agent 展示组件", () => {
  it("AgentAvatar 以 img 角色呈现默认助手身份", () => {
    render(<AgentAvatar />);

    const avatar = screen.getByRole("img", { name: "标航智导" });
    expect(avatar).toHaveClass("agent-avatar");
    expect(avatar).not.toHaveAttribute("data-streaming");
    expect(avatar).not.toHaveAttribute("aria-hidden");
  });

  it("AgentAvatar 支持自定义标签与 streaming 标记", () => {
    render(<AgentAvatar label="学习助手" streaming />);

    const avatar = screen.getByRole("img", { name: "学习助手" });
    expect(avatar).toHaveAttribute("data-streaming", "true");
  });

  it("装饰模式不进入无障碍树，仅保留视觉标记", () => {
    render(<AgentAvatar decorative className="extra-mark" />);

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    const avatar = document.querySelector(".agent-avatar");
    expect(avatar).not.toBeNull();
    expect(avatar).toHaveAttribute("aria-hidden", "true");
    expect(avatar).toHaveClass("agent-avatar", "extra-mark");
  });
});
