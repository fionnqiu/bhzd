import { useId } from "react";

import {
  DOMAIN_LABELS,
  type Domain,
} from "../../app/AppContext";
import { Button } from "../../components/Button";
import { Panel } from "../../components/Panel";

const DOMAIN_CODES: Readonly<Record<Domain, string>> = {
  text: "TX",
  image: "IM",
  audio: "AU",
  video: "VD",
};

const DOMAIN_ORDER = Object.keys(DOMAIN_LABELS) as Domain[];

export interface ConsumableUnitSummary {
  readonly data_type: string;
}

export interface ConsumableUnitSource {
  listConsumableUnits(): readonly ConsumableUnitSummary[];
}

export type DomainCounts = Readonly<Record<Domain, number>>;

export const countConsumableUnitsByDomain = (
  units: readonly ConsumableUnitSummary[],
): DomainCounts => {
  const counts: Record<Domain, number> = {
    text: 0,
    image: 0,
    audio: 0,
    video: 0,
  };

  for (const unit of units) {
    if (Object.hasOwn(counts, unit.data_type)) {
      counts[unit.data_type as Domain] += 1;
    }
  }

  return counts;
};

interface DashboardProps {
  counts: DomainCounts;
  selectedDomain: Domain;
  onSelectDomain(domain: Domain): void;
}

export function Dashboard({
  counts,
  selectedDomain,
  onSelectDomain,
}: DashboardProps) {
  const headingId = useId();

  return (
    <Panel tone="dark" className="domain-panel" aria-labelledby={headingId}>
      <div className="panel-heading">
        <p className="eyebrow">COURSE BEARINGS / 04</p>
        <h2 id={headingId}>选择课程域</h2>
        <p>从一种数据形态出发，所有工作模式沿用同一航向。</p>
      </div>

      <div className="domain-grid" aria-label="课程域">
        {DOMAIN_ORDER.map((domain, index) => {
          const label = DOMAIN_LABELS[domain];
          const count = counts[domain];
          const selected = selectedDomain === domain;

          return (
            <Button
              key={domain}
              variant="card"
              className="domain-card"
              aria-label={`${label}课程，${count} 个可学习单元`}
              aria-pressed={selected}
              onClick={() => onSelectDomain(domain)}
            >
              <span className="domain-card__index" aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="domain-card__code" aria-hidden="true">
                {DOMAIN_CODES[domain]}
              </span>
              <strong>{label}</strong>
              <span>{count} 个可学习单元</span>
              <span className="domain-card__bearing" aria-hidden="true">
                {selected ? "ACTIVE BEARING" : "OPEN COURSE"}
              </span>
            </Button>
          );
        })}
      </div>
    </Panel>
  );
}
