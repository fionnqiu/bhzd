import { Children, isValidElement, useRef, useState, type ReactNode } from "react";
import ReactMarkdown, { defaultUrlTransform, type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { FileImage, FileText, FileVideo, Music2 } from "lucide-react";
import { AgentAvatar } from "../../../components";
import type { ChatAttachment, ChatMessage } from "./types";

const markdownPlugins = [remarkGfm];

function formatFileSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function attachmentKindLabel(kind: ChatAttachment["kind"]): string {
  if (kind === "image") return "图片";
  if (kind === "audio") return "音频";
  if (kind === "video") return "视频";
  return "文件";
}

function attachmentIcon(kind: ChatAttachment["kind"]) {
  if (kind === "audio") return <Music2 size={20} aria-hidden="true" />;
  if (kind === "video") return <FileVideo size={20} aria-hidden="true" />;
  if (kind === "document") return <FileText size={20} aria-hidden="true" />;
  return <FileImage size={20} aria-hidden="true" />;
}

function MessageAttachmentBand({ attachments }: { attachments: ChatAttachment[] }) {
  return (
    <ul
      className="message-attachment-strip"
      aria-label={`本条消息携带的 ${attachments.length} 个附件`}
    >
      {attachments.map((attachment) => {
        // A persisted thumbnail is same-origin and owner-scoped. It must win
        // over the temporary blob URL so a refresh never depends on browser state.
        const imageSource =
          attachment.kind === "image" ? attachment.thumbnailUrl ?? attachment.previewUrl : null;
        const kindLabel = attachmentKindLabel(attachment.kind);
        return (
          <li
            key={attachment.id}
            className="message-attachment"
            data-testid="message-attachment"
            aria-label={`${kindLabel}附件 ${attachment.name}，${formatFileSize(attachment.size)}`}
          >
            <span className={`message-attachment-thumb message-attachment-thumb-${attachment.kind}`}>
              {imageSource ? (
                <img src={imageSource} alt={`${attachment.name} 缩略图`} />
              ) : (
                attachmentIcon(attachment.kind)
              )}
            </span>
            <span className="message-attachment-details">
              <strong title={attachment.name}>{attachment.name}</strong>
              <span>{kindLabel} · {formatFileSize(attachment.size)}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

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

/**
 * 代码块外壳：语言标签 + 复制按钮的头部栏（对齐 Kimi/DeepSeek 的代码块处理）。
 * react-markdown 渲染 ``` 围栏代码时 pre 的子节点恒为 <code className="language-x">，
 * 语言名从该 className 提取；复制取 pre 渲染后的纯文本，避免依赖 children 结构。
 */
function MarkdownCodeBlock({ children }: { children?: ReactNode }) {
  const preRef = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);

  const language = (() => {
    const code = Children.toArray(children).find((child) => isValidElement(child));
    const className = isValidElement<{ className?: string }>(code)
      ? code.props.className
      : undefined;
    return /language-([\w-]+)/.exec(className ?? "")?.[1] ?? null;
  })();

  const copyCode = async () => {
    const text = preRef.current?.innerText ?? "";
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // 剪贴板不可用（权限或非安全上下文）时静默失败，不影响阅读
    }
  };

  return (
    <div className="md-codeblock">
      <div className="md-codeblock-header">
        <span className="md-codeblock-lang">{language ?? "code"}</span>
        <button
          type="button"
          className="md-codeblock-copy"
          aria-label="复制代码"
          onClick={() => void copyCode()}
        >
          {copied ? "已复制" : "复制"}
        </button>
      </div>
      <pre ref={preRef}>{children}</pre>
    </div>
  );
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
  // 围栏代码块套上语言标签 + 复制按钮的头部栏外壳（样式见 cockpit.css .md-codeblock）
  pre(props) {
    return <MarkdownCodeBlock>{props.children}</MarkdownCodeBlock>;
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
      {isAssistant ? (
        <AgentAvatar className="assistant-avatar" decorative />
      ) : null}
      {isAssistant ? (
        // Keep the assistant identity and rich reply in one column so the
        // fixed avatar never pushes the label beside the response on narrow screens.
        <div className="assistant-reply-body">
          <span className="message-label">标航智导</span>
          <div className="bubble-content bubble-markdown">
            {message.streaming && !message.content ? (
              // 首个 token 渲染前的打字指示：避免流式起始时出现空气泡
              <span className="bubble-typing" role="status" aria-label="正在输入">
                <span />
                <span />
                <span />
              </span>
            ) : (
              <>
                <ReactMarkdown
                  remarkPlugins={markdownPlugins}
                  skipHtml
                  urlTransform={safeMarkdownUrl}
                  components={markdownComponents}
                >
                  {message.content}
                </ReactMarkdown>
                {message.streaming ? <span className="bubble-cursor" aria-hidden /> : null}
              </>
            )}
          </div>
        </div>
      ) : (
        <div className="bubble-user-body">
          {message.attachments?.length ? <MessageAttachmentBand attachments={message.attachments} /> : null}
          <div className="bubble-content">{message.content}</div>
        </div>
      )}
    </article>
  );
}
