import graphJson from "../../../data/graph/annotation-capability-graph.json";
import teachingUnitsJson from "../../../data/curriculum/teaching-units.json";
import sourceRegistryJson from "../../../data/sources/source-registry.json";
import medicalJson from "../../../data/scenarios/medical.json";
import customerServiceJson from "../../../data/scenarios/customer-service.json";
import inVehicleJson from "../../../data/scenarios/in-vehicle.json";
import contentSafetyJson from "../../../data/scenarios/content-safety.json";

import type {
  GraphDocument,
  ScenarioDocument,
  SourceRegistryDocument,
  TeachingUnitDocument,
} from "./contracts";

export const graph = graphJson as GraphDocument;
export const teachingUnits = teachingUnitsJson as TeachingUnitDocument;
export const sourceRegistry = sourceRegistryJson as SourceRegistryDocument;
export const scenarios = [
  medicalJson,
  customerServiceJson,
  inVehicleJson,
  contentSafetyJson,
] as ScenarioDocument[];
