"use client";

import { Check, Minus } from "lucide-react";
import type { ReactNode } from "react";
import type { Plan } from "@/lib/types";
import { cn, formatNumber } from "@/lib/utils";
import { Badge, Card, Segmented } from "@/components/ui";

export type Interval = "month" | "year";

export function IntervalToggle({ value, onChange }: { value: Interval; onChange: (value: Interval) => void }) {
  return <Segmented<Interval> label="Billing interval" value={value} onChange={onChange} options={[{ value: "month", label: "Monthly" }, { value: "year", label: "Annual" }]} />;
}

export function planPrice(plan: Plan, interval: Interval): { headline: string; suffix: string; note: string | null } {
  const price = interval === "month" ? plan.price_gbp_month : plan.price_gbp_year;
  if (price === null) return { headline: "Custom", suffix: "", note: null };
  if (price === 0) return { headline: "£0", suffix: "", note: null };
  if (interval === "year" && plan.price_gbp_month) {
    const saving = plan.price_gbp_month * 12 - price;
    return { headline: `£${price}`, suffix: "/ year", note: saving > 0 ? `Save £${saving} against monthly billing` : null };
  }
  return { headline: `£${price}`, suffix: "/ month", note: null };
}

const limit = (value: number | null) => (value === null ? "Unlimited" : formatNumber(value));

function Row({ included = true, children }: { included?: boolean; children: ReactNode }) {
  return (
    <li className={cn("flex items-start gap-2", included ? "text-ink/90" : "text-ink-faint")}>
      {included ? <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" /> : <Minus className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
      <span>{children}</span>
    </li>
  );
}

export function PlanCards({ plans, interval, currentKey, renderAction }: { plans: Plan[]; interval: Interval; currentKey?: string; renderAction: (plan: Plan) => ReactNode }) {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {plans.map((plan) => {
        const price = planPrice(plan, interval);
        const current = currentKey === plan.key;
        const featured = plan.key === "pro" && !currentKey;
        return (
          <Card key={plan.key} className={cn("flex flex-col p-6", (current || featured) && "border-primary/60 shadow-glow")} data-plan={plan.key}>
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-ink">{plan.name}</h3>
              {current ? <Badge tone="primary">Current plan</Badge> : featured ? <Badge tone="accent">Recommended</Badge> : null}
            </div>
            <p className="mt-4 flex items-baseline gap-1.5"><span className="num text-3xl font-semibold tracking-tight text-ink">{price.headline}</span><span className="text-xs text-ink-faint">{price.suffix}</span></p>
            <p className="mt-1 h-4 text-2xs text-success">{price.note}</p>
            <p className="mt-2 text-sm text-ink-muted">{plan.tagline}</p>
            <ul className="mt-5 flex-1 space-y-2 text-sm">
              <Row><span className="num">{limit(plan.reports_per_month)}</span> AI reports / month</Row>
              <Row><span className="num">{limit(plan.watchlist_items)}</span> watched items</Row>
              <Row><span className="num">{limit(plan.competitors)}</span> competitor{plan.competitors === 1 ? "" : "s"} monitored</Row>
              <Row><span className="num">{limit(plan.live_syncs_per_month)}</span> live GitHub requests / month</Row>
              <Row included={plan.api_requests_per_month !== 0}>{plan.api_requests_per_month === 0 ? "No API access" : <><span className="num">{limit(plan.api_requests_per_month)}</span> API calls / month</>}</Row>
              <Row included={plan.ai_enrichment}>AI-enriched reports</Row>
              <Row included={plan.custom_scoring_weights}>Custom scoring weights</Row>
            </ul>
            <div className="mt-6">{renderAction(plan)}</div>
          </Card>
        );
      })}
    </div>
  );
}
