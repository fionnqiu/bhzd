/**
 * 嵌入工具结果卡（PRD-01 §3.2"嵌入式工具结果" + NF19 两级展示）。
 *
 * tool.call.completed 的 result 按工具名分派渲染：
 * - task.preview → 任务卡（任务名称/描述/学习内容/练习）
 * - task.create → 同步回执卡（确认门落地后的回执，链到任务列表）
 * - course.search → 课程单元列表
 * - graph.reason → 节点 chips + PRE 路径 + "在图谱中查看"
 * - rag.answer → 答案 + 引用（rag.search 只是召回计数，细节合并进此卡）
 * - diagnostic.preview → 诊断报告摘要（与上传诊断共用同一渲染）
 * 内联卡默认紧凑（长列表截断 top N），"查看详情"打开 Drawer 专注视图。
 */
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { BadgeHelp, ExternalLink } from "lucide-react";
import { Button, Card, CitationCard, Drawer, Tag } from "../../../components";
import type {
  Citation,
  DiagnosticReport,
  RagAnswer,
} from "../../../api/types";
import { dataTypeLabel, toolLabel } from "./constants";
import type { EmbeddedCardData } from "./types";

/* ---------------------------------------------------------- 任务卡 */

interface TaskCardShape {
  title?: string;
  goal?: string;
  description?: string;
  knowledge_points?: { title?: string; content?: string }[];
  exercises?: { question?: string; type?: string }[];
}

export function TaskCardBody({ card }: { card: TaskCardShape }) {
  return (
    <div className="task-card">
      <strong>{card.title ?? "标注练习任务"}</strong>
      {card.description ?? card.goal ? (
        <p className="text-sm text-secondary mt-2">{card.description ?? card.goal}</p>
      ) : null}
      {card.knowledge_points?.length ? (
        <div className="mt-3">
          <strong className="text-sm">学习内容</strong>
          <ul className="task-card-steps">
            {card.knowledge_points.map((point, index) => (
              <li key={`${point.title ?? "point"}-${index}`}>{point.title ?? point.content}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {card.exercises?.length ? (
        <div className="mt-3">
          <strong className="text-sm">练习</strong>
          <ul className="task-card-steps">
            {card.exercises.map((exercise, index) => (
              <li key={`${exercise.question ?? "exercise"}-${index}`}>{exercise.question}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------- 诊断报告 */

/** 诊断报告摘要（diagnostic.preview 工具卡与上传诊断结果共用，保证两处口径一致） */
export function DiagnosticReportContent({
  report,
  maxErrors = 5,
}: {
  report: DiagnosticReport;
  maxErrors?: number;
}) {
  const errors = report.errors ?? [];
  const shown = errors.slice(0, maxErrors);
  return (
    <div className="diag-report">
      <div className="flex gap-2" style={{ flexWrap: "wrap" }}>
        <Tag>格式 {report.file_format}</Tag>
        <Tag>样本 {report.sample_count}</Tag>
        <span className="badge badge-danger">严重 {report.severity_counts?.major ?? 0}</span>
        <span className="badge badge-warning">轻微 {report.severity_counts?.minor ?? 0}</span>
      </div>
      {report.notice ? <p className="text-sm text-muted mt-2">{report.notice}</p> : null}
      {shown.length ? (
        <ul className="diag-errors">
          {shown.map((err, i) => (
            <li key={i}>
              <span className={`badge badge-${err.severity === "major" ? "danger" : "warning"}`}>
                {err.severity === "major" ? "严重" : "轻微"}
              </span>{" "}
              <strong>{err.error_type}</strong>
              <span className="text-sm text-muted">
                {" "}
                {err.rule}；建议：{err.suggestion}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-success mt-2">未发现规则性问题，标注质量良好。</p>
      )}
      {errors.length > shown.length ? (
        <p className="text-xs text-muted">其余 {errors.length - shown.length} 个问题见详情。</p>
      ) : null}
      {report.plan?.weak_caps?.length ? (
        <p className="text-sm mt-2">
          薄弱能力：
          {report.plan.weak_caps.map((c) => c.cap_name || c.cap_id).join("、")}
        </p>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------- 卡片分派 */

function CardBody({ card }: { card: EmbeddedCardData }) {
  const result = (card.result ?? {}) as Record<string, unknown>;

  switch (card.tool) {
    case "task.preview": {
      const stages = Array.isArray(result.stages)
        ? result.stages.filter((stage): stage is TaskCardShape => !!stage && typeof stage === "object")
        : [];
      // A staged Agent request creates independent tasks, so its preview must
      // expose each resulting task card instead of collapsing them into one.
      return stages.length > 0 ? (
        <div className="flex flex-col gap-3">
          {stages.map((stage, index) => (
            <TaskCardBody key={`${stage.title ?? "task"}-${index}`} card={stage} />
          ))}
        </div>
      ) : (
        <TaskCardBody card={(result.card ?? {}) as TaskCardShape} />
      );
    }
    case "task.create": {
      const count = typeof result.count === "number" ? result.count : 1;
      return (
        <div>
          <p className="text-success">
            {count > 1
              ? `已同步 ${count} 个分阶段学习任务。`
              : `学习任务「${String(result.title ?? "")}」已同步。`}
          </p>
          <Link className="text-sm" to="/tasks">
            前往学习任务查看 →
          </Link>
        </div>
      );
    }
    case "course.search": {
      const units = (result.units ?? []) as {
        unit_id: string;
        title: string;
        modality?: string | null;
        est_minutes?: number;
      }[];
      if (!units.length) return <p className="text-muted">未检索到匹配的教学单元。</p>;
      return (
        <ul className="course-list">
          {units.map((u) => (
            <li key={u.unit_id}>
              <strong>{u.title}</strong>
              <span className="text-xs text-muted">
                {" "}
                {dataTypeLabel(u.modality)} · 约 {u.est_minutes ?? 0} 分钟
              </span>
            </li>
          ))}
        </ul>
      );
    }
    case "graph.reason": {
      const nodes = (result.nodes ?? []) as { id: string; label?: string; type?: string }[];
      const action = result.action as string | undefined;
      const firstId = nodes[0]?.id;
      if (!nodes.length) return <p className="text-muted">图谱中未找到相关节点。</p>;
      return (
        <div>
          {action === "pre_path" ? (
            <ol className="graph-path">
              {nodes.map((n) => (
                <li key={n.id}>{n.label ?? n.id}</li>
              ))}
            </ol>
          ) : (
            <div className="flex gap-1" style={{ flexWrap: "wrap" }}>
              {nodes.map((n) => (
                <Tag key={n.id}>{n.label ?? n.id}</Tag>
              ))}
            </div>
          )}
          {firstId ? (
            <Link className="text-sm mt-2" to={`/graph?node=${encodeURIComponent(firstId)}`}>
              在图谱中查看 →
            </Link>
          ) : null}
        </div>
      );
    }
    case "rag.answer": {
      const answer = result as unknown as RagAnswer;
      return (
        <div className="rag-answer">
          {answer.refused ? (
            <p className="text-warning">
              <BadgeHelp size={14} /> {answer.answer}
            </p>
          ) : (
            <p>{answer.answer}</p>
          )}
          {answer.steps?.length ? (
            <ol className="confirm-steps">
              {answer.steps.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          ) : null}
          {answer.citations?.length ? (
            <div className="mt-2">
              {answer.citations.map((c: Citation, i: number) => (
                <CitationCard key={`${c.document_id}-${i}`} citation={c} index={i + 1} />
              ))}
            </div>
          ) : null}
        </div>
      );
    }
    case "rag.search": {
      const hitCount = (result.hit_count ?? 0) as number;
      const latency = result.latency_ms as number | undefined;
      return (
        <p className="text-sm text-muted">
          资料召回 {hitCount} 条{latency != null ? `（${latency}ms）` : ""}
          ，细节见规范问答结果。
        </p>
      );
    }
    case "diagnostic.preview": {
      const report = result.report as DiagnosticReport | undefined;
      if (!report) return <p className="text-muted">诊断结果不可用。</p>;
      return (
        <>
          <DiagnosticReportContent report={report} />
          <Link className="text-sm mt-2" to="/">
            返回 Agent 查看诊断结果 →
          </Link>
        </>
      );
    }
    default:
      // 未收录工具（教师/管理员域写操作回执等）：如实展示工具名，不臆造结构
      return <p className="text-sm text-muted">{toolLabel(card.tool)}已完成。</p>;
  }
}

const CARD_TITLES: Record<string, string> = {
  "task.preview": "任务卡预览",
  "task.create": "已同步到学习任务",
  "course.search": "推荐教学单元",
  "graph.reason": "图谱定位",
  "rag.answer": "规范解答",
  "rag.search": "资料召回",
  "diagnostic.preview": "诊断报告",
};

/** 单张嵌入卡：内联紧凑展示 + Drawer 专注视图（NF19） */
export default function EmbeddedCard({ card }: { card: EmbeddedCardData }) {
  const [focusOpen, setFocusOpen] = useState(false);
  const title = CARD_TITLES[card.tool] ?? toolLabel(card.tool);
  const actions: ReactNode = (
    <Button variant="ghost" size="sm" onClick={() => setFocusOpen(true)}>
      <ExternalLink size={14} />
      查看详情
    </Button>
  );
  return (
    <>
      <Card title={title} actions={actions} className="embedded-card" data-testid={`embedded-${card.tool}`}>
        <CardBody card={card} />
      </Card>
      <Drawer open={focusOpen} title={title} onClose={() => setFocusOpen(false)}>
        <CardBody card={card} />
      </Drawer>
    </>
  );
}
