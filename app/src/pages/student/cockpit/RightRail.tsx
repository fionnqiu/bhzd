/**
 * 对话画布中的引用来源区。
 *
 * 确认门已移入对话流主线（ChatStream 的 run-flow 分组，与步骤流、工具结果卡
 * 同属一条执行流水线），这里只保留引用：收到真实来源后出现，详情经显式点击
 * 打开二级抽屉，抽屉不参与默认桌面布局。
 */
import { useState } from "react";
import { CitationCard, Drawer } from "../../../components";
import type { Citation } from "../../../api/types";
import type { CockpitRun } from "./useCockpitRun";

export interface RightRailProps {
  run: CockpitRun;
}

export default function RightRail({ run }: RightRailProps) {
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);

  if (run.citations.length === 0) return null;

  return (
    <section
      className="cockpit-runtime-context"
      aria-label="引用来源"
      data-testid="cockpit-status-panel"
    >
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
