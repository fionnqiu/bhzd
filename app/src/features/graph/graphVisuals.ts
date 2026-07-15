import type { GraphEdge, GraphNode } from "../../data/contracts";
import type { MoveToOptions } from "vis-network";

import type {
  NetworkEdgeData,
  NetworkNodeData,
  NetworkOptions,
} from "./GraphCanvas";

export type GraphNodeShape =
  | "circle"
  | "diamond"
  | "hexagon"
  | "box"
  | "dot"
  | "star";

const NODE_SHAPES: Readonly<Record<string, GraphNodeShape>> = {
  CAP: "circle",
  KNG: "diamond",
  TSK: "hexagon",
  SCN: "box",
  RES: "dot",
  CERT: "star",
};

interface MasteryTone {
  background: string;
  border: string;
  borderWidth: number;
}

const MASTERY_TONES: Readonly<Record<string, MasteryTone>> = {
  unlearned: { background: "#E2E8F0", border: "#64748B", borderWidth: 1 },
  needs_work: { background: "#FEE2E2", border: "#E5484D", borderWidth: 2 },
  consolidating: { background: "#FFEDD5", border: "#FF8A3D", borderWidth: 3 },
  approaching_mastery: { background: "#CFFAFE", border: "#00C6FF", borderWidth: 4 },
  mastered: { background: "#DCFCE7", border: "#2EC27E", borderWidth: 5 },
};

export const graphNodeShape = (type: string): GraphNodeShape =>
  NODE_SHAPES[type] ?? "circle";

const masteryTone = (mastery: number | null): MasteryTone => {
  if (mastery === null) {
    return MASTERY_TONES.unlearned;
  }
  if (mastery < 0.4) {
    return MASTERY_TONES.needs_work;
  }
  if (mastery < 0.6) {
    return MASTERY_TONES.consolidating;
  }
  if (mastery < 0.8) {
    return MASTERY_TONES.approaching_mastery;
  }
  return MASTERY_TONES.mastered;
};

export const createGraphVisualNode = (
  node: GraphNode,
  mastery: number | null,
): NetworkNodeData & { shape: GraphNodeShape; color: MasteryTone } => {
  const tone = masteryTone(mastery);
  return {
    id: node.id,
    label: node.label,
    shape: graphNodeShape(node.type),
    color: tone,
    borderWidth: tone.borderWidth,
    title: `${node.label} · ${node.type} · 状态 ${node.status}`,
  };
};

export const createGraphVisualEdge = (
  edge: GraphEdge,
): NetworkEdgeData => ({
  id: edge.id,
  from: edge.source,
  to: edge.target,
  label: edge.relation,
  arrows: "to",
});

export const graphNetworkOptions = (
  reducedMotion: boolean,
  stabilized = false,
): NetworkOptions => ({
  autoResize: true,
  interaction: {
    hover: true,
    navigationButtons: true,
    keyboard: true,
  },
  nodes: {
    font: { color: "#10233F", face: "Arial", size: 14 },
    scaling: { min: 12, max: 28 },
  },
  edges: {
    color: { color: "#94A3B8", highlight: "#00C6FF" },
    smooth: reducedMotion
      ? false
      : { enabled: true, type: "dynamic", roundness: 0.5 },
  },
  physics: {
    enabled: !reducedMotion && !stabilized,
    stabilization: {
      enabled: !reducedMotion && !stabilized,
      iterations: 200,
    },
  },
  layout: { improvedLayout: true },
  ...(reducedMotion ? { interaction: { hover: true, keyboard: true } } : {}),
});

export const graphNetworkMoveOptions = (
  reducedMotion: boolean,
): MoveToOptions => ({
  scale: 1,
  animation: !reducedMotion,
});
