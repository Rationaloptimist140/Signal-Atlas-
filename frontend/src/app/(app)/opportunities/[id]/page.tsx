"use client";

import { ArrowLeft, FileText, Sparkles } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { api, errorMessage } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import type { Analysis, Opportunity, Score, Statement } from "@/lib/types";
import { cn, formatNumber, timeAgo } from "@/lib/utils";
import { MetricRadar } from "@/components/charts";
import { BasisTag, CategoryChip, ConfidenceBadge, ExternalA, ProvenanceBadge, RiskBadge, SaveButton, ScoreBreakdown, ScoreRing } from "@/components/intel";
import { Badge, Button, Card, CardHeader, ErrorState, Notice, PageHeader, Skeleton } from "@/components/ui";

type Detail = {
  opportunity: Opportunity; category_label: string | null; analysis: Analysis; score: Score | null;
  repository: { id: number; full_name: string; html_url: string | null; description: string | null; stars: number; forks: number; last_synced_at: string | null; sync_level: string };
  validation_note: string;
};
type Caps = { llm_configured: boolean; llm_provider: string | null; ai_enrichment_in_plan: boolean; setup_hint: string | null };

function StatementList({ items }: { items: Statement[] }) {
  return (
    <ul className="divide-y divide-line">{items.map((item, index) => (
      <li key={index} className="flex items-start gap-3 px-5 py-3">
        <span className="mt-0.5 shrink-0"><BasisTag basis={item.basis} /></span>
        <span className="min-w-0 text-sm leading-relaxed text-ink/90">{item.text} {item.source_url && <ExternalA href={item.source_url} className="text-xs">Source</ExternalA>}</span>
        {item.severity && <Badge tone={item.severity === "high" ? "danger" : item.severity === "medium" ? "warning" : "success"} className="ml-auto shrink-0">{item.severity}</Badge>}
      </li>))}</ul>
  );
}

function Block({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return <Card><CardHeader title={title} description={description} />{children}</Card>;
}

export default function OpportunityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { canEdit } = useSession();
  const { data, error, isLoading, mutate } = useApi<Detail>(`/opportunities/${id}`);
  const { data: caps } = useApi<Caps>("/reports-capabilities");
  const [busy, setBusy] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  async function generate() {
    setBusy(true);
    setReportError(null);
    try {
      const report = await api<{ id: number }>("/reports/generate", { method: "POST", body: { report_type: "opportunity", subject_id: Number(id) } });
      router.push(`/reports/${report.id}`);
    } catch (err) {
      setReportError(errorMessage(err));
      setBusy(false);
    }
  }

  if (isLoading && !data) return <div className="space-y-4"><Skeleton className="h-12 w-96" /><Skeleton className="h-40 w-full" /><Skeleton className="h-96 w-full" /></div>;
  if (error || !data) return <Card><ErrorState message={error ? errorMessage(error) : "Opportunity not found."} onRetry={() => mutate()} /></Card>;
  const { opportunity: o, analysis: a, repository: repo, score } = data;
  const action = a.recommended_action;

  return (
    <div className="space-y-6">
      <Link href="/opportunities" className="inline-flex items-center gap-1.5 text-xs text-ink-muted hover:text-ink"><ArrowLeft className="h-3.5 w-3.5" />Opportunity Discovery</Link>
      <PageHeader eyebrow="Commercial opportunity hypothesis" title={repo.full_name}
        description={<span className="flex flex-wrap items-center gap-2"><CategoryChip category={o.category} /><RiskBadge level={o.risk_level} /><ConfidenceBadge level={o.confidence} /><Badge>{o.maturity}</Badge><ProvenanceBadge source={o.data_source} />
          <span className="text-ink-faint">· data synced {timeAgo(repo.last_synced_at)}</span></span>}
        actions={<><Link href={`/repositories/${repo.id}`}><Button>Repository profile</Button></Link><SaveButton itemType="opportunity" itemId={o.id} size="md" />
          {canEdit && <Button variant="primary" onClick={generate} loading={busy}><Sparkles className="h-4 w-4" />Generate intelligence report</Button>}</>} />
      {reportError && <Notice tone="danger">{reportError}</Notice>}
      <Notice tone="warning" title="Unvalidated.">{data.validation_note}</Notice>

      <Card className="grid gap-0 lg:grid-cols-[auto_1fr_1fr]">
        <div className="flex flex-col items-center justify-center gap-2 border-b border-line p-6 lg:border-b-0 lg:border-r">
          <ScoreRing score={o.score} size={104} label="Opportunity score" /><p className="text-2xs font-semibold uppercase tracking-wider text-ink-faint">Opportunity score</p>
        </div>
        <div className="border-b border-line p-5 lg:border-b-0 lg:border-r">
          <p className="mb-2 flex items-center gap-2 text-2xs font-semibold uppercase tracking-wider text-ink-faint">Recommended action <BasisTag basis="interpretation" /></p>
          <p className={cn("text-lg font-semibold capitalize", action.key === "investigate" ? "text-success" : action.key === "monitor" ? "text-accent" : "text-ink-muted")}>{action.key}</p>
          <p className="mt-1 text-sm leading-relaxed text-ink-muted">{action.text}</p>
          <dl className="mt-4 grid grid-cols-3 gap-3 text-xs">
            <div><dt className="text-ink-faint">Stars</dt><dd className="num mt-0.5 text-sm text-ink">{formatNumber(repo.stars)}</dd></div>
            <div><dt className="text-ink-faint">Forks</dt><dd className="num mt-0.5 text-sm text-ink">{formatNumber(repo.forks)}</dd></div>
            <div><dt className="text-ink-faint">Licence</dt><dd className="num mt-0.5 text-sm text-ink">{o.license_spdx ?? "None"}</dd></div>
          </dl>
        </div>
        <div className="p-2">{score && <MetricRadar metrics={score.metrics} height={230} />}</div>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <div className="space-y-6">
          <Block title="Market opportunity" description="The problem, who might pay, and observable demand">
            <StatementList items={[a.problem, ...a.target_customers]} />
            <p className="border-y border-line bg-surface/50 px-5 py-2 text-2xs font-semibold uppercase tracking-wider text-ink-faint">Demand indicators</p>
            <StatementList items={a.demand_indicators} />
          </Block>
          <Block title="Monetisation possibilities" description="Business models and applications worth testing">
            <StatementList items={[...a.monetisation, ...a.commercial_applications]} />
            <p className="border-y border-line bg-surface/50 px-5 py-2 text-2xs font-semibold uppercase tracking-wider text-ink-faint">Enterprise applications</p>
            <StatementList items={a.enterprise_applications} />
          </Block>
          <Block title="Competitive landscape" description="Adjacent tracked projects and ways to differentiate">
            {a.adjacent_projects.length ? <ul className="divide-y divide-line">{a.adjacent_projects.map((p) => (
              <li key={p.repository_id} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
                <span className="flex items-center gap-2"><BasisTag basis="verified_fact" /><Link href={`/repositories/${p.repository_id}`} className="text-ink hover:text-primary-bright">{p.full_name}</Link></span>
                <span className="num text-xs text-ink-muted">★ {formatNumber(p.stars)}</span></li>))}</ul>
              : <p className="px-5 py-4 text-sm text-ink-muted">No other tracked repositories share this category yet.</p>}
            <p className="border-y border-line bg-surface/50 px-5 py-2 text-2xs text-ink-faint">Adjacency is inferred from classification. Closed-source and commercial competitors are not represented.</p>
            <StatementList items={a.differentiation} />
          </Block>
        </div>
        <div className="space-y-6">
          {score && <ScoreBreakdown score={score} />}
          <Block title="Technology maturity"><StatementList items={[a.technical_feasibility]} /></Block>
          <Block title="Risk assessment" description="Licensing and commercialisation risks">
            <StatementList items={[...a.licensing_risks, ...a.commercialisation_risks]} />
          </Block>
          <Block title="Recommended next steps">
            <ol className="list-decimal space-y-2 px-5 py-4 pl-10 text-sm leading-relaxed text-ink/90">{a.recommended_next_steps.map((step, i) => <li key={i}>{step}</li>)}</ol>
          </Block>
        </div>
      </div>

      <Card className="flex flex-col items-start justify-between gap-4 p-5 sm:flex-row sm:items-center">
        <div><p className="flex items-center gap-2 text-sm font-semibold text-ink"><FileText className="h-4 w-4 text-primary-bright" />Detailed intelligence report</p>
          <p className="mt-1 max-w-2xl text-xs text-ink-muted">
            Generates a saved report separating verified facts, calculated metrics, interpretations and hypotheses.{" "}
            {caps ? (caps.llm_configured && caps.ai_enrichment_in_plan ? `AI interpretations will be added by ${caps.llm_provider}; any figure not in the fact sheet is removed.`
              : caps.llm_configured ? "AI enrichment is available on paid plans; this report will use the rules engine."
              : "No AI provider is configured on this instance, so the report uses the deterministic rules engine.") : ""}</p></div>
        {canEdit && <Button variant="primary" onClick={generate} loading={busy}><Sparkles className="h-4 w-4" />Generate report</Button>}
      </Card>
      <p className="text-2xs leading-relaxed text-ink-faint">{a.disclaimer}</p>
    </div>
  );
}
