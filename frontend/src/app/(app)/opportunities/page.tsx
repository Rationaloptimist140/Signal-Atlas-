"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { errorMessage } from "@/lib/api";
import { useIntel } from "@/lib/session";
import type { Opportunity, Page } from "@/lib/types";
import { CATEGORY_COLORS, CATEGORY_LABELS, categoryLabel, cn, formatCompact } from "@/lib/utils";
import { OpportunityRadar } from "@/components/charts";
import { ConfidenceBadge, OpportunityCard, ProvenanceBadge, RiskBadge, ScoreRing } from "@/components/intel";
import { Card, CardHeader, EmptyState, ErrorState, Notice, PageHeader, Pagination, Segmented, Select, Skeleton, Td, Th } from "@/components/ui";

export default function OpportunitiesPage() {
  const router = useRouter();
  const [filters, setFilters] = useState({ category: "", risk: "", maturity: "", confidence: "", min_score: "", sort: "score" });
  const [view, setView] = useState<"cards" | "table">("cards");
  const [page, setPage] = useState(1);
  const set = (key: keyof typeof filters, value: string) => { setFilters((f) => ({ ...f, [key]: value })); setPage(1); };
  const { data, error, isLoading, mutate } = useIntel<Page<Opportunity>>("/opportunities", { ...filters, page, page_size: 24 });

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Engine 4" title="Opportunity Discovery" description="Open-source projects with the strongest structural signals for a commercial offering — ranked, evidenced and risk-assessed."
        actions={<Segmented label="View" value={view} onChange={setView} options={[{ value: "cards", label: "Cards" }, { value: "table", label: "Table" }]} />} />
      <Notice tone="warning" title="Hypotheses, not validated opportunities.">
        A high score means the public signals are strong. It does not mean customers will pay. Each opportunity lists its evidence, confidence, missing data and risks so you can decide what to validate.
      </Notice>

      <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Filter by sector">
        {[["", "All sectors"], ...Object.entries(CATEGORY_LABELS)].map(([key, label]) => (
          <button key={key} role="radio" aria-checked={filters.category === key} onClick={() => set("category", key)}
            className={cn("flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors", filters.category === key ? "border-primary/50 bg-primary-soft text-ink" : "border-line text-ink-muted hover:border-line-strong hover:text-ink")}>
            {key && <span className="h-1.5 w-1.5 rounded-full" style={{ background: CATEGORY_COLORS[key] }} />}{label}
          </button>))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Select value={filters.min_score} onChange={(e) => set("min_score", e.target.value)} className="h-8 w-auto text-xs" aria-label="Minimum score"><option value="">Any score</option><option value="50">Score 50+</option><option value="65">Score 65+</option><option value="75">Score 75+</option></Select>
        <Select value={filters.risk} onChange={(e) => set("risk", e.target.value)} className="h-8 w-auto text-xs" aria-label="Risk"><option value="">Any risk</option><option value="low">Low risk</option><option value="medium">Medium risk</option><option value="high">High risk</option></Select>
        <Select value={filters.maturity} onChange={(e) => set("maturity", e.target.value)} className="h-8 w-auto text-xs" aria-label="Technology maturity"><option value="">Any maturity</option><option value="experimental">Experimental</option><option value="emerging">Emerging</option><option value="established">Established</option><option value="mature">Mature</option></Select>
        <Select value={filters.confidence} onChange={(e) => set("confidence", e.target.value)} className="h-8 w-auto text-xs" aria-label="Confidence"><option value="">Any confidence</option><option value="high">High confidence</option><option value="medium">Medium confidence</option><option value="low">Low confidence</option></Select>
        <Select value={filters.sort} onChange={(e) => set("sort", e.target.value)} className="h-8 w-auto text-xs" aria-label="Sort"><option value="score">Sort: score</option><option value="recent">Sort: recently updated</option><option value="stars">Sort: stars</option></Select>
        <span className="ml-auto text-xs text-ink-muted"><span className="num text-ink">{data?.total ?? "—"}</span> opportunities</span>
      </div>

      {error ? <Card><ErrorState message={errorMessage(error)} onRetry={() => mutate()} /></Card>
        : isLoading && !data ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-72 rounded-xl" />)}</div>
        : !data?.items.length ? <Card><EmptyState title="No opportunities match" description="Loosen the filters, or track and sync more repositories. Hypotheses are generated for original, non-archived repositories scoring 30 or more." /></Card>
        : (<>
          <Card><CardHeader title="Opportunity radar" description="Development momentum against commercial potential · bubble size = total score · colour = risk" />
            <div className="p-3"><OpportunityRadar opportunities={data.items} onSelect={(id) => router.push(`/opportunities/${id}`)} height={300} /></div></Card>
          {view === "cards" ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{data.items.map((o) => <OpportunityCard key={o.id} opportunity={o} />)}</div> : (
            <Card><div className="overflow-x-auto scrollbar-thin"><table className="w-full min-w-[900px]">
              <thead className="bg-surface/60"><tr><Th className="text-center">Score</Th><Th>Project</Th><Th>Sector</Th><Th>Maturity</Th><Th>Risk</Th><Th>Confidence</Th><Th className="text-right">Stars</Th><Th>Action</Th></tr></thead>
              <tbody className="divide-y divide-line">{data.items.map((o) => (
                <tr key={o.id} className="hover:bg-white/[0.02]"><Td><div className="flex justify-center"><ScoreRing score={o.score} size={36} /></div></Td>
                  <Td><Link href={`/opportunities/${o.id}`} className="font-medium text-ink hover:text-primary-bright">{o.repository_full_name}</Link><span className="ml-2 align-middle"><ProvenanceBadge source={o.data_source} /></span></Td>
                  <Td className="text-xs text-ink-muted">{categoryLabel(o.category)}</Td><Td className="text-xs capitalize text-ink-muted">{o.maturity}</Td><Td><RiskBadge level={o.risk_level} /></Td>
                  <Td><ConfidenceBadge level={o.confidence} /></Td><Td className="num text-right">{formatCompact(o.stars)}</Td><Td className="text-xs capitalize text-ink">{o.recommended_action}</Td></tr>))}</tbody></table></div></Card>
          )}
          <Card><Pagination page={page} pageSize={24} total={data.total} onChange={setPage} /></Card>
        </>)}
    </div>
  );
}
