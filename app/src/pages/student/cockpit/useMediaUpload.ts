/** Short-lived media/document upload state for the Agent Composer. */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiRequestError, api } from "../../../api/client";
import { useToast } from "../../../components";
import type { RunAttachmentPreviewResponse, RunAttachmentResponse } from "../../../api/types";
import { MAX_UPLOAD_BYTES } from "./Composer";

export const MAX_MEDIA_ATTACHMENTS = 10;
export const MAX_MEDIA_TOTAL_BYTES = 100 * 1024 * 1024;

const MEDIA_MIME_PREFIXES = ["image/", "video/", "audio/"] as const;
const MEDIA_EXTENSIONS: Record<string, string> = {
  ".avif": "image/avif",
  ".bmp": "image/bmp",
  ".gif": "image/gif",
  ".jpeg": "image/jpeg",
  ".jpg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
  ".m4a": "audio/mp4",
  ".mp3": "audio/mpeg",
  ".ogg": "audio/ogg",
  ".wav": "audio/wav",
  ".mov": "video/quicktime",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
};
const DOCUMENT_EXTENSIONS: Record<string, string> = {
  ".pdf": "application/pdf",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".csv": "text/csv",
  ".tsv": "text/tab-separated-values",
  ".txt": "text/plain",
  ".md": "text/markdown",
  ".markdown": "text/markdown",
  ".log": "text/plain",
  ".json": "application/json",
  ".xml": "application/xml",
  ".yaml": "application/yaml",
  ".yml": "application/yaml",
  ".html": "text/html",
  ".htm": "text/html",
  ".css": "text/css",
  ".js": "text/javascript",
  ".jsx": "text/javascript",
  ".ts": "text/typescript",
  ".tsx": "text/typescript",
  ".py": "text/x-python",
  ".java": "text/x-java-source",
  ".go": "text/x-go",
  ".rs": "text/rust",
  ".sql": "application/sql",
  ".sh": "application/x-sh",
  ".ps1": "text/plain",
};

let pendingSequence = 0;

export interface PendingMediaAttachment {
  id: string;
  selectionOrder: number;
  name: string;
  kind: RunAttachmentResponse["kind"];
  size: number;
}

export interface MediaAttachment extends RunAttachmentResponse {
  /** Stable browser identity remains unique even if a mocked or stale response repeats a token. */
  clientId: string;
  selectionOrder: number;
  previewUrl: string | null;
}

function fileExtension(file: File): string {
  const match = /\.[^.]+$/.exec(file.name.toLowerCase());
  return match?.[0] ?? "";
}

function inferredMimeType(file: File): string {
  const extension = fileExtension(file);
  // Extension wins for developer files whose browser MIME is often empty or
  // misleading (for example `.ts` may be reported as video/mp2t).
  return DOCUMENT_EXTENSIONS[extension] ?? MEDIA_EXTENSIONS[extension] ?? file.type.toLowerCase();
}

function attachmentKind(file: File, mimeType: string): RunAttachmentResponse["kind"] | null {
  if (DOCUMENT_EXTENSIONS[fileExtension(file)]) return "document";
  if (mimeType.startsWith("image/")) return "image";
  if (mimeType.startsWith("video/")) return "video";
  if (mimeType.startsWith("audio/")) return "audio";
  return null;
}

function isSupportedFile(file: File, mimeType: string): boolean {
  return Boolean(attachmentKind(file, mimeType));
}

function revokePreviewUrl(url: string | null): void {
  // Some embedded browsers expose object URL creation without a matching
  // revoker. Use the normal release path where available without crashing UI.
  if (url && typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(url);
}

/**
 * Upload several one-shot Agent files without placing binary data in durable
 * conversation state. The refs make selection limits correct before React has
 * rendered a network response, which matters for a rapidly chosen batch.
 */
export function useMediaUpload(endpoint = "/api/runs/attachments") {
  const toast = useToast();
  const [uploadingAttachments, setUploadingAttachments] = useState<PendingMediaAttachment[]>([]);
  const [attachments, setAttachments] = useState<MediaAttachment[]>([]);
  const attachmentsRef = useRef<MediaAttachment[]>([]);
  const uploadingRef = useRef<PendingMediaAttachment[]>([]);
  const retainedImagePreviewUrlsRef = useRef(new Set<string>());

  const updateAttachments = useCallback((next: MediaAttachment[]) => {
    attachmentsRef.current = next;
    setAttachments(next);
  }, []);

  const removePending = useCallback((id: string) => {
    const next = uploadingRef.current.filter((attachment) => attachment.id !== id);
    uploadingRef.current = next;
    setUploadingAttachments(next);
  }, []);

  const upload = useCallback(
    async (selected: File[] | FileList) => {
      const files = Array.from(selected);
      const occupied = [...attachmentsRef.current, ...uploadingRef.current];
      let totalSize = occupied.reduce((sum, attachment) => sum + attachment.size, 0);
      let remaining = MAX_MEDIA_ATTACHMENTS - occupied.length;
      const accepted: Array<{ file: File; mimeType: string; pending: PendingMediaAttachment }> = [];
      let rejectedByLimit = 0;
      let rejectedBySize = 0;

      for (const file of files) {
        const mimeType = inferredMimeType(file);
        const kind = attachmentKind(file, mimeType);
        if (!isSupportedFile(file, mimeType) || !kind) {
          toast.error(`暂不支持文件「${file.name}」的类型`);
          continue;
        }
        if (file.size > MAX_UPLOAD_BYTES) {
          rejectedBySize += 1;
          continue;
        }
        if (remaining <= 0) {
          rejectedByLimit += 1;
          continue;
        }
        if (totalSize + file.size > MAX_MEDIA_TOTAL_BYTES) {
          rejectedBySize += 1;
          continue;
        }
        pendingSequence += 1;
        accepted.push({
          file,
          mimeType,
          pending: {
            id: `pending-${pendingSequence}`,
            selectionOrder: pendingSequence,
            name: file.name,
            kind,
            size: file.size,
          },
        });
        remaining -= 1;
        totalSize += file.size;
      }

      if (rejectedByLimit) toast.error(`一次最多添加 ${MAX_MEDIA_ATTACHMENTS} 个文件`);
      if (rejectedBySize) toast.error("单个文件不能超过 20MB，附件总量不能超过 100MB");
      if (!accepted.length) return;

      const nextPending = [...uploadingRef.current, ...accepted.map(({ pending }) => pending)];
      uploadingRef.current = nextPending;
      setUploadingAttachments(nextPending);
      await Promise.all(
        accepted.map(async ({ file, mimeType, pending }) => {
          try {
            const form = new FormData();
            // Browsers may omit MIME for uncommon extensions; recreating just
            // that File keeps multipart validation aligned with its extension.
            // Extension inference is authoritative for the accepted formats.
            // Some browsers report a generic or misleading MIME type, which
            // would otherwise pass the UI filter but be rejected by the server.
            const payload =
              file.type.toLowerCase() === mimeType
                ? file
                : new File([file], file.name, { type: mimeType });
            form.append("file", payload);
            const result = await api.postForm<RunAttachmentResponse>(endpoint, form);
            const previewUrl =
              typeof URL.createObjectURL === "function" ? URL.createObjectURL(payload) : null;
            // Upload requests resolve independently. Keep the learner's selected
            // order stable instead of letting completion timing reorder the turn.
            updateAttachments(
              [
                ...attachmentsRef.current,
                { ...result, clientId: pending.id, selectionOrder: pending.selectionOrder, previewUrl },
              ].sort((left, right) => left.selectionOrder - right.selectionOrder),
            );
          } catch (err) {
            const message =
              err instanceof ApiRequestError ? err.message : "文件上传失败，请检查网络后重试";
            toast.error(`${file.name}：${message}`);
          } finally {
            removePending(pending.id);
          }
        }),
      );
    },
    [endpoint, removePending, toast, updateAttachments],
  );

  const remove = useCallback(
    (token: string) => {
      const current = attachmentsRef.current.find(
        (attachment) => attachment.attachment_token === token,
      );
      if (!current) return;
      revokePreviewUrl(current.previewUrl);
      updateAttachments(
        attachmentsRef.current.filter((attachment) => attachment.attachment_token !== token),
      );
      // Removal is optimistic for responsiveness; the owner-scoped endpoint
      // releases cache quota but a transient network failure still expires safely.
      void api.delete(`${endpoint}/${encodeURIComponent(token)}`).catch(() => undefined);
    },
    [endpoint, updateAttachments],
  );

  const dismissAll = useCallback(() => {
    const removed = attachmentsRef.current;
    for (const attachment of removed) {
      revokePreviewUrl(attachment.previewUrl);
      void api
        .delete(`${endpoint}/${encodeURIComponent(attachment.attachment_token)}`)
        .catch(() => undefined);
    }
    updateAttachments([]);
  }, [endpoint, updateAttachments]);

  const consume = useCallback(() => {
    // Run creation owns the tokens from this point onward. Images need to keep
    // their local object URL until the persisted message returns its protected
    // thumbnail; other media has no outgoing preview surface and can release now.
    for (const attachment of attachmentsRef.current) {
      if (attachment.kind === "image" && attachment.previewUrl) {
        retainedImagePreviewUrlsRef.current.add(attachment.previewUrl);
      } else {
        revokePreviewUrl(attachment.previewUrl);
      }
    }
    updateAttachments([]);
  }, [updateAttachments]);

  const releasePersistedImagePreviews = useCallback((previewUrls: readonly string[]) => {
    for (const previewUrl of previewUrls) {
      if (!retainedImagePreviewUrlsRef.current.delete(previewUrl)) continue;
      revokePreviewUrl(previewUrl);
    }
  }, []);

  const loadDocumentPreview = useCallback(
    (token: string) =>
      api.get<RunAttachmentPreviewResponse>(`${endpoint}/${encodeURIComponent(token)}/preview`),
    [endpoint],
  );

  useEffect(
    () => () => {
      const previewUrls = new Set<string>();
      for (const attachment of attachmentsRef.current) {
        if (attachment.previewUrl) previewUrls.add(attachment.previewUrl);
      }
      for (const previewUrl of retainedImagePreviewUrlsRef.current) {
        previewUrls.add(previewUrl);
      }
      for (const previewUrl of previewUrls) {
        revokePreviewUrl(previewUrl);
      }
    },
    [],
  );

  return {
    uploading: uploadingAttachments.length > 0,
    uploadingAttachments,
    attachments,
    upload,
    remove,
    dismissAll,
    consume,
    releasePersistedImagePreviews,
    loadDocumentPreview,
  };
}
