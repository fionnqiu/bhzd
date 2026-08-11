import { useEffect, useId, useState, type CSSProperties, type ReactNode } from "react";
import { CheckCircle2, ChevronDown, Circle, CircleDotDashed, Sparkles } from "lucide-react";
import "./agent-presentation.css";

export type AgentOrbPhase = "preparing" | "retrieving" | "generating" | "finalizing";

export interface AgentTaskStep {
  id: string;
  title: string;
  status: string;
}

interface AgentAvatarProps {
  streaming?: boolean;
  className?: string;
  label?: string;
  decorative?: boolean;
}

interface AgentOrbProps {
  phase?: AgentOrbPhase;
  label?: string;
  pill?: boolean;
  className?: string;
}

interface AgentTaskListProps {
  steps: readonly AgentTaskStep[];
  title?: string;
  defaultOpen?: boolean;
  className?: string;
  testId?: string;
}

interface AgentThinkingReasoningProps {
  label: string;
  phase?: AgentOrbPhase;
  completed?: boolean;
  durationLabel?: string | null;
  children?: ReactNode;
  className?: string;
  testId?: string;
}

type TaskState = "done" | "active" | "pending";

const ORB_DOTS = Array.from({ length: 9 }, (_, index) => index);

/**
 * The server's plan statuses vary across historical and live runs.  Collapse
 * them into three visible states so a learner sees progress, not orchestration
 * details or provider-specific status text.
 */
function taskState(status: string): TaskState {
  if (["completed", "done", "success"].includes(status)) return "done";
  if (["running", "in_progress", "active", "waiting_confirmation"].includes(status)) {
    return "active";
  }
  return "pending";
}

function orbPhaseLabel(phase: AgentOrbPhase): string {
  return (
    {
      preparing: "正在整理",
      retrieving: "正在检索",
      generating: "正在生成",
      finalizing: "正在完成",
    }[phase] ?? "正在处理"
  );
}

/**
 * Shared assistant identity keeps the teacher and student streams recognisable
 * as one product while each host page still controls its local layout.
 */
export function AgentAvatar({
  streaming = false,
  className,
  label = "标航智导",
  decorative = false,
}: AgentAvatarProps) {
  return (
    <span
      className={["agent-avatar", className].filter(Boolean).join(" ")}
      data-streaming={streaming || undefined}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : label}
      aria-hidden={decorative || undefined}
    >
      <Sparkles className="agent-avatar-spark" size={15} strokeWidth={2.25} aria-hidden="true" />
    </span>
  );
}

/**
 * A small DOM-only lattice inspired by AIcss Orbs.  It represents only a
 * known lifecycle phase and remains readable when reduced motion is enabled.
 */
export function AgentOrb({
  phase = "preparing",
  label,
  pill = false,
  className,
}: AgentOrbProps) {
  const text = label ?? orbPhaseLabel(phase);
  return (
    <span
      className={["agent-orb", `agent-orb-${phase}`, pill ? "agent-orb-pill" : "", className]
        .filter(Boolean)
        .join(" ")}
    >
      <span className="agent-orb-glyph" role={pill ? undefined : "img"} aria-label={pill ? undefined : text}>
        {ORB_DOTS.map((index) => (
          <span
            key={index}
            className="agent-orb-dot"
            style={{ "--agent-orb-index": index } as CSSProperties}
          />
        ))}
      </span>
      {pill ? <span className="agent-orb-pill-label">{text}</span> : null}
    </span>
  );
}

/**
 * A compact, scrollbar-free projection of a server-issued plan.  The content
 * folds with CSS grid rather than an internal scroll surface so the transcript
 * remains the only place a reader scrolls through work history.
 */
export function AgentTaskList({
  steps,
  title = "执行清单",
  defaultOpen = true,
  className,
  testId,
}: AgentTaskListProps) {
  const [open, setOpen] = useState(defaultOpen);
  const contentId = useId();
  const completed = steps.filter((step) => taskState(step.status) === "done").length;

  if (steps.length === 0) return null;

  return (
    <section
      className={["agent-task-list", className].filter(Boolean).join(" ")}
      data-testid={testId}
      aria-label={title}
    >
      <button
        type="button"
        className="agent-task-list-head"
        aria-expanded={open}
        aria-controls={contentId}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="agent-task-list-title">
          <AgentOrb phase={completed === steps.length ? "finalizing" : "generating"} />
          <span>{title}</span>
        </span>
        <span className="agent-task-list-count">
          {completed}/{steps.length}
        </span>
        <ChevronDown className={open ? undefined : "is-collapsed"} size={16} aria-hidden="true" />
      </button>
      <div
        id={contentId}
        className="agent-task-list-fold"
        data-open={open || undefined}
        aria-hidden={!open}
      >
        <div className="agent-task-list-inner">
          <ol className="agent-task-list-items">
            {steps.map((step) => {
              const state = taskState(step.status);
              const Icon =
                state === "done" ? CheckCircle2 : state === "active" ? CircleDotDashed : Circle;
              return (
                <li key={step.id} className={`agent-task-list-item is-${state}`}>
                  <Icon size={16} aria-hidden="true" />
                  <span>{step.title}</span>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </section>
  );
}

/**
 * This borrows the AIcss Thinking + Reasoning interaction language without
 * accepting model thought.  Callers may only supply an already-safe lifecycle
 * label and optional visible execution content.
 */
export function AgentThinkingReasoning({
  label,
  phase = "preparing",
  completed = false,
  durationLabel,
  children,
  className,
  testId,
}: AgentThinkingReasoningProps) {
  const [open, setOpen] = useState(!completed);
  const contentId = useId();
  const collapsible = children !== undefined && children !== null;

  useEffect(() => {
    if (!completed) setOpen(true);
  }, [completed]);

  const content = (
    <>
      <AgentOrb phase={phase} />
      <span className="agent-thinking-copy">
        <span className="agent-thinking-kicker">{completed ? "处理完成" : "处理中"}</span>
        <span className="agent-thinking-label">{label}</span>
      </span>
      {durationLabel ? <span className="agent-thinking-duration">{durationLabel}</span> : null}
    </>
  );

  return (
    <section
      className={[
        "agent-thinking-reasoning",
        completed ? "is-completed" : "is-active",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      data-testid={testId}
      role={collapsible ? undefined : "status"}
    >
      {collapsible ? (
        <button
          type="button"
          className="agent-thinking-head"
          aria-expanded={open}
          aria-controls={contentId}
          onClick={() => setOpen((value) => !value)}
        >
          {content}
          <ChevronDown className={open ? undefined : "is-collapsed"} size={16} aria-hidden="true" />
        </button>
      ) : (
        <div className="agent-thinking-head">{content}</div>
      )}
      {collapsible ? (
        <div
          id={contentId}
          className="agent-thinking-fold"
          data-open={open || undefined}
          aria-hidden={!open}
        >
          <div className="agent-thinking-inner">{children}</div>
        </div>
      ) : null}
    </section>
  );
}
