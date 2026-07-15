import type { GraphDocument, TeachingUnit } from "../../data/contracts";
import type { DeepReadonly } from "../../data/repository";
import type { GraphEngine } from "../../graph/graphEngine";
import type { LearningProfileSnapshot } from "../../state/profileStore";
import { GraphCanvas, type GraphRepository } from "./GraphCanvas";
import { ProgressPanel } from "./ProgressPanel";

export interface GraphWorkspaceProps {
  repository: GraphRepository;
  profileSnapshot: LearningProfileSnapshot;
  scenarioId: string | null;
  initialNodeId: string | null;
  graphEngine: GraphEngine;
  graphDocument: GraphDocument;
  onSelectNode(nodeId: string | null): void;
  onOpenUnit(unit: DeepReadonly<TeachingUnit>): void;
}

export default function GraphWorkspace({
  repository,
  profileSnapshot,
  scenarioId,
  initialNodeId,
  graphEngine,
  graphDocument,
  onSelectNode,
  onOpenUnit,
}: GraphWorkspaceProps) {
  return (
    <>
      <GraphCanvas
        graphDocument={graphDocument}
        graphEngine={graphEngine}
        repository={repository}
        profileSnapshot={profileSnapshot}
        scenarioId={scenarioId}
        initialNodeId={initialNodeId}
        onSelectNode={onSelectNode}
        onOpenUnit={onOpenUnit}
      />
      <ProgressPanel
        graphEngine={graphEngine}
        profileSnapshot={profileSnapshot}
        targetNodeId={initialNodeId}
        selectedScenarioId={scenarioId}
        nodes={graphDocument.nodes}
      />
    </>
  );
}
