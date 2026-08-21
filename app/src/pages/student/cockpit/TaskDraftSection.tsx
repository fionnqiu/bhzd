/**
 * 任务草稿操作区（回答底部的交互入口 + 任务卡预览弹窗）。
 *
 * 交互契约（PRD 任务草稿链路）：
 * - Agent 生成学习任务后，回答底部出现「查看学习任务卡」按钮；
 * - 弹窗预览刚生成的任务卡；「同步到学习任务」直接落库（按钮点击即
 *   学生对该内容的显式确认，后端按草稿幂等写入，重复点击不产生重复任务）；
 * - 「继续修改」把修订话术预填到输入框，由学生补充后发起新一轮生成。
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { ListPlus, PencilLine } from "lucide-react";
import { Button, Modal } from "../../../components";
import type { TaskDraft } from "../../../api/types";
import { TaskCardBody } from "./EmbeddedCard";

export interface TaskDraftSectionProps {
  draft: TaskDraft;
  /** 返回是否同步成功；组件自身维护按钮 loading */
  onSync: () => Promise<boolean>;
  /** 预填输入框并聚焦（继续修改） */
  onRevise: () => void;
}

export default function TaskDraftSection({ draft, onSync, onRevise }: TaskDraftSectionProps) {
  const [open, setOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const synced = draft.status === "synced";
  const firstTaskId = draft.task_ids[0];

  const handleSync = async () => {
    if (syncing || synced) return;
    setSyncing(true);
    try {
      await onSync();
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="task-draft-section" data-testid="task-draft-section">
      <Button
        variant="secondary"
        size="sm"
        onClick={() => setOpen(true)}
        data-testid="task-draft-open"
      >
        <ListPlus size={14} aria-hidden="true" />
        {synced ? "查看学习任务卡（已同步）" : "查看学习任务卡"}
      </Button>
      <Modal
        open={open}
        title="学习任务卡预览"
        onClose={() => setOpen(false)}
        footer={
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setOpen(false);
                onRevise();
              }}
              data-testid="task-draft-revise"
            >
              <PencilLine size={14} aria-hidden="true" />
              继续修改
            </Button>
            <Button
              size="sm"
              loading={syncing}
              disabled={synced}
              onClick={() => void handleSync()}
              data-testid="task-draft-sync"
            >
              <ListPlus size={14} aria-hidden="true" />
              {synced ? "已同步" : syncing ? "正在同步..." : "同步到学习任务"}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          {draft.cards.map((card, index) => (
            <TaskCardBody key={`${card.title ?? "task"}-${index}`} card={card} />
          ))}
          {synced ? (
            <p className="text-success">
              已同步 {Math.max(draft.task_ids.length, 1)} 个学习任务。
              {firstTaskId ? (
                <>
                  {" "}
                  <Link className="text-sm" to="/tasks" onClick={() => setOpen(false)}>
                    前往学习任务查看 →
                  </Link>
                </>
              ) : null}
            </p>
          ) : (
            <p className="text-xs text-muted">
              同步后任务将出现在「学习任务」列表；如需调整可先点击「继续修改」。
            </p>
          )}
        </div>
      </Modal>
    </div>
  );
}
