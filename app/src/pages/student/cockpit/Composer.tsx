/**
 * Bottom input surface for learner conversations. File selection stays inside
 * this controlled Composer so welcome shortcuts and the transcript use one path.
 */
import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
} from "react";
import { ArrowUp, FileImage, FileText, FileVideo, Music2, Plus, X } from "lucide-react";
import { Modal, Spinner, Textarea } from "../../../components";
import type { RunAttachmentPreviewResponse, RunAttachmentResponse } from "../../../api/types";
import type { MediaAttachment, PendingMediaAttachment } from "./useMediaUpload";

export interface ComposerHandle {
  openFilePicker: () => void;
  openDiagnosticPicker: () => void;
  focus: () => void;
}

/** The primary picker accepts every file type that can travel with one Agent turn. */
export const UPLOAD_ACCEPT = [
  ".pdf,.docx,.pptx,.xlsx,.csv,.tsv,.txt,.md,.markdown,.log",
  ".json,.textgrid,.xml,.yaml,.yml,.html,.htm,.css,.js,.jsx,.ts,.tsx",
  ".py,.java,.go,.rs,.sql,.sh,.ps1,image/*,video/*,audio/*",
].join(",");
/** Diagnostics remain an explicit workflow, rather than silently taking over a chat attachment. */
export const DIAGNOSTIC_UPLOAD_ACCEPT = ".json,.textgrid,.xml";
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

export interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onUpload: (files: File[]) => void;
  onDiagnosticUpload?: (file: File) => void;
  /** Run progress blocks a new request, except an explicit reviewed-task confirmation. */
  sending: boolean;
  allowSendWhileSending?: boolean;
  uploading?: boolean;
  uploadingAttachments?: PendingMediaAttachment[];
  mediaAttachments?: MediaAttachment[];
  onRemoveMedia?: (token: string) => void;
  onLoadDocumentPreview?: (token: string) => Promise<RunAttachmentPreviewResponse>;
  variant?: "default" | "hero";
}

function formatFileSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function attachmentIcon(kind: RunAttachmentResponse["kind"], label: string) {
  if (kind === "audio") return <Music2 size={22} aria-label={label} />;
  if (kind === "video") return <FileVideo size={22} aria-label={label} />;
  if (kind === "document") return <FileText size={22} aria-label={label} />;
  return <FileImage size={22} aria-label={label} />;
}

function hasNativePreview(attachment: MediaAttachment): boolean {
  return attachment.kind !== "document" || attachment.mime_type === "application/pdf";
}

const Composer = forwardRef<ComposerHandle, ComposerProps>(function Composer(
  {
    value,
    onChange,
    onSend,
    onUpload,
    onDiagnosticUpload,
    sending,
    allowSendWhileSending = false,
    uploading = false,
    uploadingAttachments = [],
    mediaAttachments = [],
    onRemoveMedia,
    onLoadDocumentPreview,
    variant = "default",
  },
  ref,
) {
  const attachmentFileRef = useRef<HTMLInputElement>(null);
  const diagnosticFileRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const [previewAttachment, setPreviewAttachment] = useState<MediaAttachment | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [documentPreview, setDocumentPreview] = useState<RunAttachmentPreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const isHero = variant === "hero";
  // A pending task write is intentionally the only exception: its text command
  // reaches the same confirmation endpoint as the visible sync button. Uploads
  // are never an exception because their tokens do not exist until they finish.
  const sendLocked = uploading || (sending && !allowSendWhileSending);

  useEffect(() => {
    // Removing a card must also close its modal so focus never stays in a view
    // whose owner-scoped temporary token has already been released.
    if (
      previewAttachment &&
      !mediaAttachments.some(
        (attachment) => attachment.attachment_token === previewAttachment.attachment_token,
      )
    ) {
      setPreviewAttachment(null);
      setDocumentPreview(null);
      setPreviewError(null);
      setPreviewLoading(false);
    }
  }, [mediaAttachments, previewAttachment]);

  useImperativeHandle(ref, () => ({
    openFilePicker: () => attachmentFileRef.current?.click(),
    openDiagnosticPicker: () => diagnosticFileRef.current?.click(),
    focus: () => textRef.current?.focus(),
  }));

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!value.trim() || sendLocked) return;
      onSend();
    }
  };

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    // Resetting allows a failed or removed file to be selected again.
    event.target.value = "";
    if (files.length) onUpload(files);
  };

  const handleDiagnosticFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    // Resetting permits selecting the same report again after a validation failure.
    event.target.value = "";
    if (file) onDiagnosticUpload?.(file);
  };

  const openPreview = async (attachment: MediaAttachment) => {
    setPreviewAttachment(attachment);
    setDocumentPreview(null);
    setPreviewError(null);
    const needsParsedText = attachment.kind === "document" && !hasNativePreview(attachment);
    setPreviewLoading(
      Boolean(needsParsedText || (attachment.previewUrl && hasNativePreview(attachment))),
    );
    if (!needsParsedText || !onLoadDocumentPreview) return;
    try {
      const preview = await onLoadDocumentPreview(attachment.attachment_token);
      setDocumentPreview(preview);
    } catch {
      setPreviewError("文件预览加载失败，请稍后重试");
    } finally {
      setPreviewLoading(false);
    }
  };

  const closePreview = () => {
    setPreviewAttachment(null);
    setDocumentPreview(null);
    setPreviewError(null);
    setPreviewLoading(false);
  };

  const hasAttachmentCards = uploadingAttachments.length > 0 || mediaAttachments.length > 0;

  return (
    <div
      className={`composer composer-${variant}${hasAttachmentCards ? " composer-has-media" : ""}`}
      data-testid="composer"
    >
      <div className="composer-row">
        <input
          ref={attachmentFileRef}
          type="file"
          multiple
          accept={UPLOAD_ACCEPT}
          className="composer-file"
          aria-label="选择对话附件"
          onChange={handleFile}
        />
        <input
          ref={diagnosticFileRef}
          type="file"
          accept={DIAGNOSTIC_UPLOAD_ACCEPT}
          className="composer-file"
          aria-label="上传诊断文件"
          onChange={handleDiagnosticFile}
        />
        <div className="composer-input-shell" data-testid="composer-input-shell">
          {hasAttachmentCards ? (
            <div className="composer-media-grid" aria-label="待发送附件">
              {uploadingAttachments.map((attachment) => (
                <div
                  key={attachment.id}
                  className="composer-media-preview composer-media-uploading"
                  data-testid="composer-media-uploading"
                  role="status"
                  aria-live="polite"
                  aria-busy="true"
                >
                  <div className="composer-media-thumb" aria-hidden="true">
                    <Spinner size={20} />
                  </div>
                  <div className="composer-media-details">
                    <strong title={attachment.name}>{attachment.name}</strong>
                    <span>正在上传 · {formatFileSize(attachment.size)}</span>
                  </div>
                </div>
              ))}
              {mediaAttachments.map((attachment) => (
                <div
                  key={attachment.clientId}
                  className="composer-media-preview"
                  data-testid="composer-media-preview"
                  role="group"
                  aria-label={`已上传${attachment.kind === "image" ? "图片" : attachment.kind === "video" ? "视频" : attachment.kind === "audio" ? "音频" : "文件"}预览`}
                >
                  <button
                    type="button"
                    className="composer-media-open"
                    aria-label={`预览文件 ${attachment.name}`}
                    title={`预览 ${attachment.name}`}
                    onClick={() => void openPreview(attachment)}
                  >
                    <span
                      className={`composer-media-thumb composer-media-thumb-${attachment.kind}`}
                    >
                      {attachment.kind === "image" && attachment.previewUrl ? (
                        <img src={attachment.previewUrl} alt="已上传图片缩略图" />
                      ) : attachment.kind === "video" && attachment.previewUrl ? (
                        <video
                          src={attachment.previewUrl}
                          muted
                          preload="metadata"
                          aria-label="已上传视频缩略图"
                        />
                      ) : (
                        attachmentIcon(attachment.kind, "已上传文件")
                      )}
                    </span>
                    <span className="composer-media-details">
                      <strong title={attachment.name}>{attachment.name}</strong>
                      <span>{formatFileSize(attachment.size)}</span>
                    </span>
                  </button>
                  <button
                    type="button"
                    className="composer-media-remove"
                    aria-label={`移除附件 ${attachment.name}`}
                    title={`移除 ${attachment.name}`}
                    onClick={() => onRemoveMedia?.(attachment.attachment_token)}
                  >
                    <X size={14} aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
          ) : null}
          <Textarea
            ref={textRef}
            className="composer-textarea"
            aria-label="对话输入"
            placeholder={isHero ? "输入你的学习目标，或输入 / 选择能力" : "继续描述你的学习问题"}
            rows={isHero ? 3 : 2}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
          />
          <div className="composer-input-actions" data-testid="composer-input-actions">
            <button
              type="button"
              className="composer-upload-btn composer-tool-button"
              aria-label="添加对话附件"
              title="添加对话附件"
              aria-busy={uploading || undefined}
              disabled={uploading}
              onClick={() => attachmentFileRef.current?.click()}
            >
              <Plus size={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="composer-send-btn"
              aria-label="发送"
              title="发送"
              aria-busy={sending || uploading || undefined}
              disabled={!value.trim() || sendLocked}
              onClick={onSend}
            >
              <ArrowUp size={18} aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
      <Modal
        open={Boolean(previewAttachment)}
        title={previewAttachment?.name ?? "文件预览"}
        onClose={closePreview}
        large
      >
        <div className="composer-file-preview" aria-busy={previewLoading || undefined}>
          {previewLoading ? (
            <div className="composer-file-preview-loading">
              <Spinner /> 正在加载预览
            </div>
          ) : null}
          {previewAttachment &&
          previewAttachment.previewUrl &&
          hasNativePreview(previewAttachment) ? (
            previewAttachment.kind === "image" ? (
              <img
                src={previewAttachment.previewUrl}
                alt={previewAttachment.name}
                onLoad={() => setPreviewLoading(false)}
              />
            ) : previewAttachment.kind === "video" ? (
              <video
                src={previewAttachment.previewUrl}
                controls
                onLoadedData={() => setPreviewLoading(false)}
              />
            ) : previewAttachment.kind === "audio" ? (
              <audio
                src={previewAttachment.previewUrl}
                controls
                onCanPlay={() => setPreviewLoading(false)}
              />
            ) : (
              <iframe
                src={previewAttachment.previewUrl}
                title={previewAttachment.name}
                onLoad={() => setPreviewLoading(false)}
              />
            )
          ) : documentPreview ? (
            <div className="composer-document-preview">
              <pre>{documentPreview.content}</pre>
              {documentPreview.truncated ? <p>内容较长，当前仅展示前 80,000 个字符。</p> : null}
            </div>
          ) : previewError ? (
            <p className="composer-file-preview-unavailable">{previewError}</p>
          ) : !previewLoading ? (
            <p className="composer-file-preview-unavailable">当前文件暂时无法在浏览器中预览。</p>
          ) : null}
        </div>
      </Modal>
    </div>
  );
});

export default Composer;
