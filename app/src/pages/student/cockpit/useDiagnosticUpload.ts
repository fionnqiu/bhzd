/**
 * 诊断上传流程 hook（PRD-01 §3.4.3 + PRD-06 §9.1）。
 *
 * 为什么独立成 hook：上传 → 报告卡 → 保存摘要确认 这条链路与运行状态机
 * 无关，塞进 useCockpitRun 只会让两个状态机互相踩状态。
 * 客户端先拦截类型/大小（≤20MB，PRD-06 §9.1），避免无效请求；
 * 真正的格式嗅探与规则诊断永远在后端确定性引擎（PRD-06 §6.1）。
 */
import { useCallback, useRef, useState } from "react";
import { ApiRequestError, api } from "../../../api/client";
import type {
  DiagnosticUploadResponse,
  SaveSummaryResponse,
} from "../../../api/types";
import { useToast } from "../../../components";
import { MAX_UPLOAD_BYTES } from "./Composer";

const ALLOWED_EXTENSIONS = [".json", ".textgrid", ".xml"];

export function useDiagnosticUpload(scenarioId: string) {
  const toast = useToast();
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [report, setReport] = useState<DiagnosticUploadResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scenarioRef = useRef(scenarioId);
  scenarioRef.current = scenarioId;

  const upload = useCallback(
    async (file: File) => {
      setError(null);
      // 客户端预检（服务端仍会再校验；这里是为了即刻反馈）
      const lower = file.name.toLowerCase();
      if (!ALLOWED_EXTENSIONS.some((ext) => lower.endsWith(ext))) {
        setError("仅支持 JSON / TextGrid / VOC XML 标注文件");
        return;
      }
      if (file.size > MAX_UPLOAD_BYTES) {
        setError("文件超过 20MB 上限，请拆分或压缩后再上传");
        return;
      }
      setUploading(true);
      try {
        const form = new FormData();
        form.append("file", file);
        // 场景元数据缺失时由引擎按通用规则诊断（PRD-06 §7.3）
        if (scenarioRef.current) form.append("scenario_id", scenarioRef.current);
        const result = await api.postForm<DiagnosticUploadResponse>(
          "/api/diagnostics",
          form,
        );
        // 埋点 diagnostic_uploaded 由后端路由写入（避免前后端重复计数）
        setReport(result);
      } catch (err) {
        setError(
          err instanceof ApiRequestError
            ? err.message
            : "上传失败，请检查网络后重试",
        );
      } finally {
        setUploading(false);
      }
    },
    [],
  );

  /** 保存诊断摘要（确认弹窗通过后调用； mastery_preview 已在报告里展示过） */
  const saveSummary = useCallback(async (): Promise<boolean> => {
    if (!report) return false;
    setSaving(true);
    try {
      await api.post<SaveSummaryResponse>("/api/diagnostics/save-summary", {
        diagnostic_token: report.diagnostic_token,
      });
      toast.success("诊断摘要已保存，掌握度已更新");
      setReport(null);
      return true;
    } catch (err) {
      toast.error(
        err instanceof ApiRequestError ? err.message : "保存失败，请稍后重试",
      );
      return false;
    } finally {
      setSaving(false);
    }
  }, [report, toast]);

  const dismiss = useCallback(() => {
    setReport(null);
    setError(null);
  }, []);

  return { uploading, saving, report, error, upload, saveSummary, dismiss };
}
