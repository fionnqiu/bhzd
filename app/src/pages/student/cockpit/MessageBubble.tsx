import ReactMarkdown, { defaultUrlTransform, type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "./types";

const markdownPlugins = [remarkGfm];

/**
 * Keep Agent-provided links useful without allowing scheme-based navigation
 * payloads. `defaultUrlTransform` handles encoded protocol tricks first; this
 * stricter allowlist then keeps the learner-facing surface to web and local
 * navigation only.
 */
function safeMarkdownUrl(url: string) {
  const transformed = defaultUrlTransform(url).trim();
  if (!transformed) return "";
  if (/^https?:\/\//i.test(transformed) || transformed.startsWith("#")) return transformed;
  if (transformed.startsWith("/") && !transformed.startsWith("//")) return transformed;
  return "";
}

const markdownComponents: Components = {
  a({ href, children }) {
    if (!href) return <>{children}</>;
    const opensNewTab = /^https?:\/\//i.test(href);
    return (
      <a
        href={href}
        target={opensNewTab ? "_blank" : undefined}
        rel={opensNewTab ? "noopener noreferrer" : undefined}
      >
        {children}
      </a>
    );
  },
  // Remote image URLs are not needed in an instructional reply and can track
  // learners or disrupt the compact transcript, so Markdown images stay hidden.
  img() {
    return null;
  },
};

/**
 * 对话消息：用户保留右对齐浅蓝气泡，助手使用无边框的阅读流。
 * 助手回复经安全 Markdown 预览；用户和系统输入保持字面文本，避免误把提问
 * 当作格式指令。streaming 时加打字光标提示（纯 CSS 动画）。
 */
export default function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "system") {
    return <div className="bubble bubble-system">{message.content}</div>;
  }
  const isAssistant = message.role === "assistant";
  return (
    <article
      className={`bubble bubble-${message.role}`}
      aria-label={isAssistant ? "标航智导回复" : "你的消息"}
    >
      {isAssistant ? <span className="message-label">标航智导</span> : null}
      <div className={`bubble-content${isAssistant ? " bubble-markdown" : ""}`}>
        {isAssistant ? (
          <ReactMarkdown
            remarkPlugins={markdownPlugins}
            skipHtml
            urlTransform={safeMarkdownUrl}
            components={markdownComponents}
          >
            {message.content}
          </ReactMarkdown>
        ) : (
          message.content
        )}
        {message.streaming ? <span className="bubble-cursor" aria-hidden /> : null}
      </div>
    </article>
  );
}
