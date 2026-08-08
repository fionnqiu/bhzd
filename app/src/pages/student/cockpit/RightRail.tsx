/**
 * 对话画布中的按需运行上下文。
 *
 * 这里不再承担一个常驻右栏：确认门必须与当前对话一起可见，引用只在
 * 收到真实来源后出现。引用详情仍可通过显式点击打开二级抽屉，但抽屉
 * 不参与默认桌面布局，也不会遮住需要用户决策的确认操作。
 */
import { useState } from "react";
import { CitationCard, Drawer } from "../../../components";
import type { Citation } from "../../../api/types";
import ConfirmationGate from "./ConfirmationGate";
import type { CockpitRun } from "./useCockpitRun";

export interface RightRailProps {
  run: CockpitRun;
}

export default function RightRail({ run }: RightRailProps) {
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  const hasContext = Boolean(run.confirmation || run.citations.length > 0);

  if (!hasContext) return null;

  return (
    <section
      className="cockpit-runtime-context"
      aria-label="当前运行上下文"
      data-testid="cockpit-status-panel"
    >
      {run.confirmation ? (
        <ConfirmationGate
          confirmation={run.confirmation}
          confirming={run.confirming}
          onConfirm={run.confirm}
          onCancel={run.cancel}
        />
      ) : null}

      {run.citations.length > 0 ? (
        <section className="runtime-context-section" data-testid="citation-section">
          <div className="runtime-context-heading">
            <h2>引用来源</h2>
            <span>{run.citations.length} 条</span>
          </div>
          <div className="runtime-citations">
            {run.citations.map((citation, index) => (
              <CitationCard
                key={`${citation.document_id}-${index}`}
                citation={citation}
                index={index + 1}
                onClick={() => setActiveCitation(citation)}
              />
            ))}
          </div>
        </section>
      ) : null}

      {/* Details are intentionally secondary and user-triggered; they never
          become a second permanent navigation surface. */}
      <Drawer
        open={activeCitation !== null}
        title="引用详情"
        onClose={() => setActiveCitation(null)}
      >
        {activeCitation ? <CitationCard citation={activeCitation} /> : null}
      </Drawer>
    </section>
  );
}
