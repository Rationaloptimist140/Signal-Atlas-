"use client";

import { CheckCircle2, CircleDashed, Database, FlaskConical, Github } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useSWRConfig } from "swr";
import { api, errorMessage } from "@/lib/api";
import { useIntel, useSession } from "@/lib/session";
import type { Dashboard, Opportunity, Page } from "@/lib/types";
import { CATEGORY_LABELS, cn } from "@/lib/utils";
import { AdoptionBars, CategoryLegend, CategoryLines, OpportunityRadar } from "@/components/charts";
import { EcosystemMap, type GraphEdge, type GraphNode } from "@/components/ecosystem-map";
import { ProvenanceBadge, RiskBadge, ScoreRing } from "@/components/intel";
import { Button, Card, CardHeader, EmptyState, ErrorState, LoadingRows, Notice, Select, Skeleton, Tabs } from "@/components/ui";

type Momentum = {
  categories: { key: string; label: string }[];
  developer_activity: { series: Record<string, number | string>[]; unit: string; basis: string };
  repository_growth: { series: Record<string, number | string>[]; unit: string; cohort_size: number; has_history: boolean; basis: string; note: string | null };
  technology_adoption: { category: string; label: string; repositories: number; stars: number }[];
  trending_categories: { category: string; label: string; signals_30d: number }[];
};

export function GettingStarted() {
  const { isAdmin, canEdit } = useSession();
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadDemo() {
    setBusy(true);
    setError(null);
    try {
      await api("/system/demo/load", { method: "POST" });
      await mutate(() => true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <EmptyState icon={<Database className="h-5 w-5" />} title="Your terminal has no data yet"
        description="Signal Atlas never shows invented statistics. Pull verified public data from GitHub, or load clearly labelled fictional fixtures to explore the product."
        action={
          <div className="flex flex-col items-center gap-3">
            <div className="flex flex-wrap justify-center gap-2">
              {canEdit && <Link href="/repositories?github=1"><Button variant="primary"><Github className="h-4 w-4" />Search GitHub for live data</Button></Link>}
              {isAdmin && <Button onClick={loadDemo} loading={busy}><FlaskConical className="h-4 w-4" />Load demo fixtures</Button>}
            </div>
            {error && <p role="alert" className="text-xs text-danger">{error}</p>}
          </div>
        } />
    </Card>
  );
}

export function MomentumCard() {
  const { data, error, isLoading, mutate } = useIntel<Momentum>("/trends/momentum");
  const [tab, setTab] = useState<"activity" | "growth" | "adoption" | "trending">("activity");
  return (
    <Card className="flex flex-col">
      <CardHeader title="Technology momentum" description="Activity and growth across tracked repositories, by category" />
      <Tabs className="px-3" value={tab} onChange={setTab} tabs={[
        { value: "activity", label: "Developer activity" }, { value: "growth", label: "Repository growth" },
        { value: "adoption", label: "Technology adoption" }, { value: "trending", label: "Trending categories" }]} />
      <div className="flex-1 pt-4">
        {isLoading && !data ? <div className="px-5 pb-5"><Skeleton className="h-64 w-full" /></div>
          : error ? <ErrorState message={errorMessage(error)} onRetry={() => mutate()} />
          : !data ? null
          : tab === "activity" ? (
            data.developer_activity.series.length ? (
              <><div className="px-2"><CategoryLines data={data.developer_activity.series} categories={data.categories} xKey="week" /></div>
                <p className="px-5 py-2 text-2xs text-ink-faint">Weekly commits · {data.developer_activity.basis}</p><CategoryLegend categories={data.categories} /></>
            ) : <EmptyState title="No commit history yet" description="Commit activity appears after repositories receive a full sync (open a repository and choose Sync, or add it to a watchlist)." />
          ) : tab === "growth" ? (
            data.repository_growth.has_history ? (
              <><div className="px-2"><CategoryLines data={data.repository_growth.series} categories={data.categories} xKey="date" unit="%" /></div>
                <p className="px-5 py-2 text-2xs text-ink-faint">Star growth since the first day of the window · fixed cohort of {data.repository_growth.cohort_size} repositories · {data.repository_growth.basis}</p>
                <CategoryLegend categories={data.categories} /></>
            ) : <EmptyState title="Growth history is still accumulating" description={data.repository_growth.note ?? "Snapshots on at least two different days are needed."} />
          ) : tab === "adoption" ? (
            data.technology_adoption.length ? <div className="px-2 pb-4"><AdoptionBars data={data.technology_adoption} /></div> : <EmptyState title="No classified repositories yet" />
          ) : data.trending_categories.length ? (
            <ul className="space-y-3 px-5 pb-5">
              {data.trending_categories.map((row) => {
                const max = data.trending_categories[0].signals_30d || 1;
                return (
                  <li key={row.category}>
                    <div className="mb-1 flex justify-between text-xs"><span className="text-ink">{row.label}</span><span className="num text-ink-muted">{row.signals_30d} signals / 30d</span></div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.07]"><div className="h-full rounded-full bg-gradient-to-r from-primary to-accent" style={{ width: `${(row.signals_30d / max) * 100}%` }} /></div>
                  </li>
                );
              })}
            </ul>
          ) : <EmptyState title="No trend signals in the last 30 days" description="Signals are detected as snapshots and commit history accumulate." />}
      </div>
    </Card>
  );
}

export function OpportunityRadarCard() {
  const router = useRouter();
  const [category, setCategory] = useState("");
  const [risk, setRisk] = useState("");
  const [minScore, setMinScore] = useState("");
  const { data, error, isLoading, mutate } = useIntel<Page<Opportunity>>("/opportunities", { page_size: 40, category, risk, min_score: minScore });
  return (
    <Card>
      <CardHeader title="Opportunity radar" description="Hypotheses ranked by business potential score. Bubble size is the score; colour is risk."
        action={<Link href="/opportunities" className="text-xs text-primary-bright hover:underline">Open discovery →</Link>} />
      <div className="flex flex-wrap gap-2 border-b border-line px-5 py-3">
        <Select aria-label="Filter by technology category" value={category} onChange={(e) => setCategory(e.target.value)} className="h-8 w-auto text-xs">
          <option value="">All technologies</option>
          {Object.entries(CATEGORY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </Select>
        <Select aria-label="Filter by commercial potential" value={minScore} onChange={(e) => setMinScore(e.target.value)} className="h-8 w-auto text-xs">
          <option value="">Any score</option><option value="50">Score 50+</option><option value="65">Score 65+</option><option value="75">Score 75+</option>
        </Select>
        <Select aria-label="Filter by risk" value={risk} onChange={(e) => setRisk(e.target.value)} className="h-8 w-auto text-xs">
          <option value="">Any risk</option><option value="low">Low risk</option><option value="medium">Medium risk</option><option value="high">High risk</option>
        </Select>
      </div>
      {isLoading && !data ? <LoadingRows rows={5} /> : error ? <ErrorState message={errorMessage(error)} onRetry={() => mutate()} />
        : !data?.items.length ? <EmptyState title="No opportunities match these filters" description="Opportunity hypotheses are generated for scored, original, non-archived repositories." />
        : (
          <div className="grid gap-0 xl:grid-cols-[1.15fr_1fr]">
            <div className="border-b border-line p-3 xl:border-b-0 xl:border-r"><OpportunityRadar opportunities={data.items} onSelect={(id) => router.push(`/opportunities/${id}`)} /></div>
            <ol className="max-h-[350px] overflow-y-auto scrollbar-thin">
              {data.items.slice(0, 12).map((o, index) => (
                <li key={o.id}>
                  <Link href={`/opportunities/${o.id}`} className="flex items-center gap-3 border-b border-line px-5 py-2.5 last:border-0 hover:bg-white/[0.03]">
                    <span className="num w-5 text-xs text-ink-faint">{index + 1}</span>
                    <ScoreRing score={o.score} size={36} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-ink">{o.repository_full_name}</span>
                      <span className="mt-0.5 flex flex-wrap items-center gap-1.5"><RiskBadge level={o.risk_level} /><ProvenanceBadge source={o.data_source} /></span>
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
          </div>
        )}
    </Card>
  );
}

export function EcosystemCard({ height = 520 }: { height?: number }) {
  const [category, setCategory] = useState("");
  const { data, error, isLoading, mutate } = useIntel<{ nodes: GraphNode[]; edges: GraphEdge[]; note: string }>("/ecosystem/graph", { limit: 24, category });
  return (
    <Card>
      <CardHeader title="Technology ecosystem map" description="How tracked repositories connect through technologies, organisations, shared contributors and dependencies"
        action={
          <Select aria-label="Ecosystem category" value={category} onChange={(e) => setCategory(e.target.value)} className="h-8 w-auto text-xs">
            <option value="">All categories</option>
            {Object.entries(CATEGORY_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </Select>
        } />
      {isLoading && !data ? <div className="p-5"><Skeleton className="w-full" /><Skeleton className="mt-2 h-80 w-full" /></div>
        : error ? <ErrorState message={errorMessage(error)} onRetry={() => mutate()} />
        : !data?.nodes.length ? <EmptyState title="Nothing to map yet" description="The map fills in as repositories are tracked and fully synced." />
        : <><EcosystemMap nodes={data.nodes} edges={data.edges} height={height} /><p className="border-t border-line px-5 py-2.5 text-2xs text-ink-faint">{data.note} Drag to pan, scroll to zoom, click a repository or developer to open it.</p></>}
    </Card>
  );
}

export function SetupChecklist({ setup }: { setup: Dashboard["setup"] }) {
  const items = [
    { done: setup.github_token_configured, label: "GitHub server token", detail: "Raises the API limit from 60 to 5,000 requests/hour and unlocks issue and pull-request totals.", env: "GITHUB_TOKEN" },
    { done: setup.github_oauth_configured, label: "GitHub OAuth", detail: "Lets users sign in with GitHub and use their own read-only quota.", env: "GITHUB_OAUTH_CLIENT_ID / _SECRET" },
    { done: setup.llm_configured, label: "AI enrichment provider", detail: "Adds AI interpretations to reports. The rules engine works without it.", env: "LLM_PROVIDER + API key" },
  ];
  if (items.every((i) => i.done)) return null;
  return (
    <Card>
      <CardHeader title="Setup requirements" description="Optional integrations that are not configured on this instance" action={<Link href="/settings?tab=integrations" className="text-xs text-primary-bright hover:underline">Details →</Link>} />
      <ul className="divide-y divide-line">
        {items.map((item) => (
          <li key={item.label} className="flex items-start gap-3 px-5 py-3">
            {item.done ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" /> : <CircleDashed className="mt-0.5 h-4 w-4 shrink-0 text-warning" />}
            <div className="min-w-0">
              <p className="text-sm text-ink">{item.label} <span className={cn("ml-1 text-2xs font-semibold uppercase tracking-wider", item.done ? "text-success" : "text-warning")}>{item.done ? "Configured" : "Not configured"}</span></p>
              <p className="mt-0.5 text-xs text-ink-muted">{item.detail} {!item.done && <code className="num text-ink-faint">{item.env}</code>}</p>
            </div>
          </li>
        ))}
      </ul>
      <div className="px-5 pb-4"><Notice>All features work without these; affected figures are shown as “not available” rather than estimated.</Notice></div>
    </Card>
  );
}
