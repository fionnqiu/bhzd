import type { TaskCard } from "../../tasks/taskConverter";

export interface TaskCardViewProps {
  card: TaskCard;
  position: number;
}

interface IdListProps {
  label: string;
  values: readonly string[];
  emptyMessage: string;
}

function IdList({ label, values, emptyMessage }: IdListProps) {
  return (
    <section>
      <h4>{label}</h4>
      {values.length === 0 ? (
        <p>{emptyMessage}</p>
      ) : (
        <ul aria-label={label}>
          {values.map((value) => (
            <li key={value}>{value}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function TaskCardView({ card, position }: TaskCardViewProps) {
  const titleId = `task-card-${position}-title`;
  const cardLabelId = `task-card-${position}-label`;

  return (
    <article
      className="task-card"
      aria-labelledby={`${cardLabelId} ${titleId}`}
    >
      <p id={cardLabelId}>任务卡 {position}</p>
      <h3 id={titleId}>{card.name}</h3>
      <dl>
        <div>
          <dt>角色</dt>
          <dd>{card.role}</dd>
        </div>
        <div>
          <dt>场景</dt>
          <dd>{card.scene}</dd>
        </div>
      </dl>

      <section>
        <h4>目标</h4>
        <ul aria-label="目标">
          {card.objectives.map((objective) => (
            <li key={objective}>{objective}</li>
          ))}
        </ul>
      </section>

      <IdList
        label="能力路径"
        values={card.capabilityPath}
        emptyMessage="当前任务没有可展示的能力路径。"
      />
      <IdList
        label="能力 ID"
        values={card.capabilityIds}
        emptyMessage="当前任务没有能力 ID。"
      />
      <IdList
        label="知识 ID"
        values={card.knowledgeIds}
        emptyMessage="当前任务没有关联知识 ID。"
      />
      <IdList
        label="证书 ID"
        values={card.certificateIds}
        emptyMessage="当前任务没有关联证书 ID。"
      />

      <section>
        <h4>操作步骤</h4>
        <ol aria-label="操作步骤">
          {card.steps.map((step, index) => (
            <li key={`${index}-${step}`}>{step}</li>
          ))}
        </ol>
      </section>

      <IdList
        label="常见错误"
        values={card.commonErrors}
        emptyMessage="当前任务卡未提供常见错误。"
      />
      <IdList
        label="资源 ID"
        values={card.resourceIds}
        emptyMessage="当前任务没有关联资源 ID。"
      />

      <IdList
        label="自检清单"
        values={card.selfCheckItems}
        emptyMessage="当前任务没有可展示的自检项。"
      />
    </article>
  );
}
