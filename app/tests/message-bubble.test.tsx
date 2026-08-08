import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import MessageBubble from "../src/pages/student/cockpit/MessageBubble";
import type { ChatMessage } from "../src/pages/student/cockpit/types";

function message(role: ChatMessage["role"], content: string): ChatMessage {
  return { id: `${role}-message`, role, content };
}

describe("助手消息 Markdown 预览", () => {
  it("将流式助手内容渲染为标题、强调、列表、代码和 GFM 表格", () => {
    const { container } = render(
      <MessageBubble
        message={{
          ...message(
            "assistant",
            [
              "## 学习建议",
              "",
              "先完成 **BIO 边界** 练习：",
              "",
              "- 识别实体起点",
              "- 延续同一实体",
              "",
              "```ts",
              'const label = "B-PER";',
              "```",
              "",
              "| 模块 | 状态 |",
              "| --- | --- |",
              "| NER | 待练习 |",
            ].join("\n"),
          ),
          streaming: true,
        }}
      />,
    );

    expect(screen.getByRole("heading", { name: "学习建议", level: 2 })).toBeInTheDocument();
    expect(screen.getByText("BIO 边界").tagName).toBe("STRONG");
    expect(screen.getByRole("list")).toHaveTextContent("识别实体起点");
    expect(screen.getByText('const label = "B-PER";').closest("pre")).not.toBeNull();
    expect(screen.getByRole("table")).toHaveTextContent("NER");
    // The cursor remains separate from the parsed tree so streamed deltas do
    // not require a different Markdown rendering path.
    expect(container.querySelector(".bubble-cursor")).not.toBeNull();
  });

  it("只解析助手回复，用户输入仍按字面文本显示", () => {
    const { container } = render(
      <MessageBubble message={message("user", "**这是用户输入，不应加粗**")} />,
    );

    expect(screen.getByText("**这是用户输入，不应加粗**")).toBeInTheDocument();
    expect(container.querySelector("strong")).toBeNull();
  });

  it("丢弃原始 HTML、图片和不安全链接，同时保留隔离的 HTTPS 链接", () => {
    const { container } = render(
      <MessageBubble
        message={message(
          "assistant",
          [
            "<script>window.__injected = true</script>",
            "",
            "[不安全链接](javascript:alert(1))",
            "",
            "![远程图片](https://example.com/pixel.png)",
            "",
            "[安全规范](https://example.com/spec)",
          ].join("\n"),
        )}
      />,
    );

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.queryByRole("link", { name: "不安全链接" })).toBeNull();
    const safeLink = screen.getByRole("link", { name: "安全规范" });
    expect(safeLink).toHaveAttribute("href", "https://example.com/spec");
    expect(safeLink).toHaveAttribute("target", "_blank");
    expect(safeLink).toHaveAttribute("rel", "noopener noreferrer");
  });
});
