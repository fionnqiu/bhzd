import { useEffect, useRef, useState } from "react";

import type { TeachingRepository } from "../../data/repository";
import { diagnoseFile } from "../../diagnostics/diagnose";
import type {
  DiagnosticContext,
  DiagnosticFileLike,
  DiagnosticReport,
  DiagnosticSeverity,
} from "../../diagnostics/types";
import type { GraphEngine } from "../../graph/graphEngine";
import { DiagnosticReportView } from "./DiagnosticReportView";

const ACCEPTED_EXTENSIONS = [
  ".json",
  ".textgrid",
  ".xml",
  ".png",
  ".jpg",
  ".jpeg",
] as const;

const acceptedFileName = (name: string): boolean =>
  ACCEPTED_EXTENSIONS.some((extension) => name.toLowerCase().endsWith(extension));

const imageFileName = (name: string): boolean =>
  [".png", ".jpg", ".jpeg"].some((extension) =>
    name.toLowerCase().endsWith(extension),
  );

const imageExplanationReport = (): DiagnosticReport => ({
  status: "explanation_only",
  format: "image",
  masteryImpact: false,
  score: null,
  issues: [
    {
      code: "screenshot_explanation_only",
      severity: "minor",
      message: "截图仅用于本地辅助讲解，不会自动诊断或计分。",
      ruleRefs: [],
      capabilityRefs: [],
      remediation: ["请上传 JSON、TextGrid 或 XML 标注导出文件以进行结构化诊断。"],
    },
  ],
});

export interface DiagnosticMasteryEntry {
  capabilityId: string;
  severity: DiagnosticSeverity;
}

export type DiagnosticMasteryInput =
  | {
      kind: "exercise";
      capabilityIds: readonly string[];
      score: number;
    }
  | {
      kind: "diagnostic";
      entries: readonly DiagnosticMasteryEntry[];
    };

export interface DiagnosticViewProps {
  dataType: string | null;
  targetUnitId: string | null;
  repository?: TeachingRepository;
  graphEngine?: GraphEngine;
  masteryForNode?(nodeId: string): number | null;
  diagnose?: (
    file: DiagnosticFileLike | null | undefined,
    context?: DiagnosticContext | null,
  ) => Promise<DiagnosticReport>;
  onApplyMastery?(input: DiagnosticMasteryInput): void;
}

const targetCapabilityIdsFor = (
  repository: TeachingRepository | undefined,
  targetUnitId: string | null,
): string[] => {
  if (repository === undefined || targetUnitId === null) {
    return [];
  }

  try {
    const capabilityRefs = repository.getUnit(targetUnitId)?.exercise
      .capability_refs;
    return Array.isArray(capabilityRefs)
      ? [
          ...new Set(
            capabilityRefs.filter(
              (capabilityId): capabilityId is string =>
                typeof capabilityId === "string" && capabilityId.trim().length > 0,
            ),
          ),
        ]
      : [];
  } catch {
    return [];
  }
};

const diagnosticEntriesFor = (
  report: DiagnosticReport,
  repository: TeachingRepository | undefined,
  targetUnitId: string | null,
): DiagnosticMasteryEntry[] => {
  const fallbackCapabilityIds = targetCapabilityIdsFor(repository, targetUnitId);
  const seenEntries = new Set<string>();

  return report.issues.flatMap((issue) => {
    const issueCapabilityIds = [
      ...new Set(
        issue.capabilityRefs.filter(
          (capabilityId): capabilityId is string =>
            typeof capabilityId === "string" && capabilityId.trim().length > 0,
        ),
      ),
    ];
    const capabilityIds =
      issueCapabilityIds.length > 0 ? issueCapabilityIds : fallbackCapabilityIds;

    return capabilityIds.flatMap((capabilityId) => {
      const entryKey = `${capabilityId}\u0000${issue.severity}`;
      if (seenEntries.has(entryKey)) {
        return [];
      }
      seenEntries.add(entryKey);
      return [{ capabilityId, severity: issue.severity }];
    });
  });
};

const masteryInputFor = (
  report: DiagnosticReport,
  repository: TeachingRepository | undefined,
  targetUnitId: string | null,
): DiagnosticMasteryInput | null => {
  if (
    report.status !== "complete" ||
    !report.masteryImpact ||
    typeof report.score !== "number" ||
    !Number.isFinite(report.score) ||
    report.score < 0 ||
    report.score > 1
  ) {
    return null;
  }

  if (report.issues.length === 0) {
    const capabilityIds = targetCapabilityIdsFor(repository, targetUnitId);
    return capabilityIds.length > 0
      ? { kind: "exercise", capabilityIds, score: report.score }
      : null;
  }

  const entries = diagnosticEntriesFor(report, repository, targetUnitId);
  return entries.length > 0 ? { kind: "diagnostic", entries } : null;
};

interface DiagnosticViewContext {
  readonly dataType: string | null;
  readonly targetUnitId: string | null;
}

const sameDiagnosticViewContext = (
  left: DiagnosticViewContext,
  right: DiagnosticViewContext,
): boolean =>
  left.dataType === right.dataType && left.targetUnitId === right.targetUnitId;

export function DiagnosticView({
  dataType,
  targetUnitId,
  repository,
  graphEngine,
  masteryForNode,
  diagnose = diagnoseFile,
  onApplyMastery,
}: DiagnosticViewProps) {
  const [report, setReport] = useState<DiagnosticReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const uploadRequestRef = useRef(0);
  const mountedRef = useRef(true);
  const latestContextRef = useRef<DiagnosticViewContext>({
    dataType,
    targetUnitId,
  });
  latestContextRef.current = { dataType, targetUnitId };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      uploadRequestRef.current += 1;
    };
  }, []);

  useEffect(() => {
    setReport(null);
    setError(null);
  }, [dataType, targetUnitId]);

  const handleFile = async (file: File | null) => {
    const requestId = ++uploadRequestRef.current;
    const requestContext = { dataType, targetUnitId };
    if (file === null) {
      return;
    }
    if (dataType === null || dataType.trim().length === 0) {
      setError("请先选择数据类型后再上传标注导出文件。");
      return;
    }
    if (!acceptedFileName(file.name)) {
      setError("仅支持 .json、.TextGrid、.xml、.png、.jpg、.jpeg 标注导出文件。");
      return;
    }

    setError(null);
    if (imageFileName(file.name)) {
      setReport(imageExplanationReport());
      return;
    }

    try {
      const nextReport = await diagnose(file, {
        dataType,
        targetUnitId,
        repository,
      });
      if (
        requestId !== uploadRequestRef.current ||
        !mountedRef.current ||
        !sameDiagnosticViewContext(requestContext, latestContextRef.current)
      ) {
        return;
      }
      setReport(nextReport);
      const masteryInput = masteryInputFor(nextReport, repository, targetUnitId);
      if (masteryInput !== null) {
        onApplyMastery?.(masteryInput);
      }
    } catch {
      if (
        requestId === uploadRequestRef.current &&
        mountedRef.current &&
        sameDiagnosticViewContext(requestContext, latestContextRef.current)
      ) {
        setError("本地诊断暂时无法完成，请保留当前文件并稍后重试。");
      }
    }
  };

  return (
    <section className="diagnostic-view" aria-labelledby="diagnostic-view-title">
      <h2 id="diagnostic-view-title">标注诊断</h2>
      <p>
        当前数据类型：{dataType ?? "未选择"}；目标单元：{targetUnitId ?? "未选择"}
      </p>
      <label htmlFor="diagnostic-upload">上传标注导出文件</label>
      <input
        id="diagnostic-upload"
        type="file"
        accept={ACCEPTED_EXTENSIONS.join(",")}
        onChange={(event) => {
          void handleFile(event.currentTarget.files?.[0] ?? null);
        }}
      />
      <p>支持 .json、.TextGrid、.xml、.png、.jpg、.jpeg；文件仅在当前浏览器内存中解析。</p>
      {error !== null ? <p role="alert">{error}</p> : null}
      {report?.status === "explanation_only" ? (
        <p className="diagnostic-view__image-mode" role="status">
          辅助讲解模式
        </p>
      ) : null}
      {report !== null ? (
        <DiagnosticReportView
          report={report}
          graphEngine={graphEngine}
          repository={repository}
          masteryForNode={masteryForNode}
        />
      ) : null}
    </section>
  );
}

export { DiagnosticReportView } from "./DiagnosticReportView";
