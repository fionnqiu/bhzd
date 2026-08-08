/**
 * 底部输入区（PRD-01 §3.2：文本输入/文件上传/快捷指令/发送按钮）。
 *
 * 受控组件：value 由页面持有，这样"岗位任务训练"快捷卡才能把模板
 * 文本注入输入框（WelcomeState 不直接碰 composer）。
 * 文件选择器通过 ref 暴露 openFilePicker()，欢迎态"上传结果诊断"卡
 * 与上传按钮共用同一路径。
 */
import {
  forwardRef,
  useImperativeHandle,
  useRef,
  type ChangeEvent,
  type KeyboardEvent,
} from "react";
import { ArrowUp, ChevronDown, FolderOpen, Plus } from "lucide-react";
import { Textarea } from "../../../components";

export interface ComposerHandle {
  openFilePicker: () => void;
  focus: () => void;
}

/** PRD-06 §9.1：可诊断文件类型与 20MB 上限（客户端先拦一道） */
export const UPLOAD_ACCEPT = ".json,.textgrid,.xml";
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

export interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onUpload: (file: File) => void;
  /** 运行进行中：发送禁用（追问走新一轮 run，等本轮终态后开放） */
  sending: boolean;
  uploading?: boolean;
  scenarioName: string;
  /** 欢迎态使用同一输入路径的扩展视觉，避免产生第二个独立目标输入。 */
  variant?: "default" | "hero";
}

const Composer = forwardRef<ComposerHandle, ComposerProps>(function Composer(
  {
    value,
    onChange,
    onSend,
    onUpload,
    sending,
    uploading = false,
    scenarioName,
    variant = "default",
  },
  ref,
) {
  const fileRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const isHero = variant === "hero";

  useImperativeHandle(ref, () => ({
    openFilePicker: () => fileRef.current?.click(),
    focus: () => textRef.current?.focus(),
  }));

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter 发送、Shift+Enter 换行（聊天输入惯例）
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      // 键盘路径必须遵循发送按钮的禁用规则，避免运行中再开一轮并发编排。
      if (!value.trim() || sending) return;
      onSend();
    }
  };

  const handleFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    // 清空 value：同一文件可重复选择（诊断失败后重传同文件是常见路径）
    e.target.value = "";
    if (file) onUpload(file);
  };

  return (
    <div className={`composer composer-${variant}`} data-testid="composer">
      <div className="composer-row">
        <input
          ref={fileRef}
          type="file"
          accept={UPLOAD_ACCEPT}
          className="composer-file"
          aria-label="上传标注结果文件"
          onChange={handleFile}
        />
        <div className="composer-input-shell" data-testid="composer-input-shell">
          <Textarea
            ref={textRef}
            className="composer-textarea"
            aria-label="对话输入"
            placeholder={isHero ? "输入你的学习目标，或输入 / 选择能力" : "继续描述你的学习问题"}
            rows={isHero ? 3 : 2}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          {/* Both states share this toolbar so upload, keyboard submit, and the
              busy lock remain one production path instead of visual-only clones. */}
          <div className="composer-input-actions">
            <button
              type="button"
              className="composer-upload-btn composer-tool-button"
              aria-label="上传诊断文件"
              title="上传诊断文件"
              aria-busy={uploading || undefined}
              disabled={uploading}
              onClick={() => fileRef.current?.click()}
            >
              <Plus size={16} aria-hidden="true" />
            </button>
            <span
              className="composer-scenario"
              aria-label={`当前场景：${scenarioName}`}
              title={`当前场景：${scenarioName}`}
            >
              <FolderOpen size={16} aria-hidden="true" />
              <span>{scenarioName}</span>
              <ChevronDown size={14} aria-hidden="true" />
            </span>
            <button
              type="button"
              className="composer-send-btn"
              aria-label="发送"
              title="发送"
              aria-busy={sending || undefined}
              disabled={!value.trim() || sending}
              onClick={onSend}
            >
              <ArrowUp size={18} aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
});

export default Composer;
