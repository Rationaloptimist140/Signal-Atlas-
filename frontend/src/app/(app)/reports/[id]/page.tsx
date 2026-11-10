"use client";

import { ArrowLeft, Printer } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";
import { errorMessage } from "@/lib/api";
import { useApi } from "@/lib/session";
import type { Fact, Report, ReportStatement } from "@/lib/types";
import { formatDate, titleCase } from "@/lib/utils";
import { BasisTag, ConfidenceBadge, ExternalA, GeneratedByTag, ProvenanceBadge, ScoreBreakdown } from "@/components/intel";
import { Badge, Button, Card, CardHeader, ErrorState, Notice, PageHeader, Skeleton, Spinner } from "@/components/ui";

function FactTable({ facts }: { facts: Fact[] }) {
  return (
    <div className="overflow-x-auto"><table className="w-full text-sm"><tbody className="divide-y divide-line">{facts.map((fact) => (
      <tr key={fact.id}><td className="num w-12 px-5 py-2.5 align-top text-xs text-ink-faint">{fact.id}</td><td className="px-2 py-2.5 align-top text-ink-muted">{fact.label}</td>
        <td className="px-5 py-2.5 text-right align-top"><span className="num text-ink">{fact.value}</span>{fact.source_url && <ExternalA href={fact.source_url} className="ml-2 text-xs">Source</ExternalA>}
          {fact.explanation && <p className="mt-0.5 text-2xs text-ink-faint">{fact.explanation}</p>}</td></tr>))}</tbody></table></div>
  );
}

function Statements({ items, empty }: { items: ReportStatement[]; empty: string }) {
  if (!items.length) return <p className="px-5 py-4 text-sm text-ink-muted">{empty}</p>;
  return (
    <ul className="divide-y divide-line">{items.map((item, index) => (
      <li key={index} className="px-5 py-3"><p className="text-sm leading-relaxed text-ink/90">{item.text}</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5"><GeneratedByTag by={item.generated_by} />{item.confidence && <ConfidenceBadge level={item.confidence} />}
          {item.references?.map((ref) => <span key={ref} className="num rounded border border-line px-1 text-2xs text-ink-faint" title="Fact this statement relies on">{ref}</span>)}</div></li>))}</ul>
  );
}

function Section({ step, title, basis, description, children }: { step: number; title: string; basis: string; description: string; children: ReactNode }) {
  return <Card><CardHeader title={<span className="flex flex-wrap items-center gap-2"><span className="num text-ink-faint">{step}</span>{title}<BasisTag basis={basis} /></span>} description={description} />{children}</Card>;
}

export default function ReportDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: report, error, isLoading, mutate } = useApi<Report>(`/reports/${id}`, undefined, { refreshInterval: (latest) => (latest?.status === "enriching" ? 4000 : 0) });

  if (isLoading && !report) return <div className="space-y-4"><Skeleton className="h-12 w-2/3" /><Skeleton className="h-40 w-full" /><Skeleton className="h-96 w-full" /></div>;
  if (error || !report?.content) return <Card><ErrorState message={error ? errorMessage(error) : "Report not found."} onRetry={() => mutate()} /></Card>;
  const c = report.content;
  const legend = c.provenance.legend;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <Link href="/reports" className="inline-flex items-center gap-1.5 text-xs text-ink-muted hover:text-ink print:hidden"><ArrowLeft className="h-3.5 w-3.5" />Intelligence Reports</Link>
      <PageHeader eyebrow={`${titleCase(report.report_type)} report`} title={report.title}
        description={<span className="flex flex-wrap items-center gap-2"><ProvenanceBadge source={report.data_source} /><GeneratedByTag by={c.provenance.ai_enriched ? "ai" : "rules"} />
          <span>Generated {formatDate(c.provenance.generated_at)}</span>{c.provenance.model && <span className="num text-ink-faint">· {c.provenance.provider}/{c.provenance.model}</span>}</span>}
        actions={<Button onClick={() => window.print()} className="print:hidden"><Printer className="h-4 w-4" />Print / PDF</Button>} />

      {report.status === "enriching" && <Notice tone="accent"><span className="inline-flex items-center gap-2"><Spinner />AI enrichment is in progress. The rule-based report below is already complete; AI interpretations will appear automatically.</span></Notice>}
      {c.provenance.ai_error && <Notice tone="warning" title="AI enrichment unavailable.">{c.provenance.ai_error}</Notice>}
      {c.provenance.guardrails && c.provenance.guardrails.statements_removed > 0 && (
        <Notice tone="accent" title="Guardrail applied."><span className="num">{c.provenance.guardrails.statements_removed}</span> AI statement(s) were removed because they contained figures or monetary claims not present in the verified fact sheet.</Notice>
      )}
      {report.data_source === "demo_fixture" && <Notice tone="warning" title="Demonstration data.">This report describes a fictional fixture.</Notice>}

      <Card className="border-primary/30 p-6 shadow-glow">
        <p className="mb-2 flex items-center gap-2 text-2xs font-semibold uppercase tracking-wider text-primary-bright">Executive summary <GeneratedByTag by={c.executive_summary.generated_by} /></p>
        <p className="text-base leading-relaxed text-ink">{c.executive_summary.text}</p>
      </Card>

      <Section step={1} title="Verified facts" basis="verified_fact" description={legend.verified_facts}><FactTable facts={c.verified_facts} /></Section>
      <Section step={2} title="Calculated metrics" basis="calculated_metric" description={legend.calculated_metrics}><FactTable facts={c.calculated_metrics} /></Section>
      <Section step={3} title="Interpretations" basis="interpretation" description={legend.interpretations}><Statements items={c.interpretations} empty="No interpretations were generated." /></Section>
      <Section step={4} title="Unverified hypotheses" basis="hypothesis" description={legend.hypotheses}>
        <Statements items={[...c.hypotheses, ...c.commercial_use_cases]} empty="No hypotheses were generated for this report type." />
      </Section>

      {c.score && <ScoreBreakdown score={c.score} />}

      {c.analysis && (
        <Card><CardHeader title="Risk assessment" description="Licensing and commercialisation risks (rule-based interpretations)" />
          <ul className="divide-y divide-line">{[...c.analysis.licensing_risks, ...c.analysis.commercialisation_risks].map((risk, i) => (
            <li key={i} className="flex items-start gap-3 px-5 py-3"><span className="mt-0.5 shrink-0"><BasisTag basis={risk.basis} /></span><span className="text-sm leading-relaxed text-ink/90">{risk.text}</span>
              {risk.severity && <Badge tone={risk.severity === "high" ? "danger" : risk.severity === "medium" ? "warning" : "success"} className="ml-auto shrink-0">{risk.severity}</Badge>}</li>))}</ul></Card>
      )}

      {c.recommended_next_steps.length > 0 && (
        <Card><CardHeader title="Recommended next steps" />
          <ol className="space-y-2.5 px-5 py-4">{c.recommended_next_steps.map((step, i) => (
            <li key={i} className="flex items-start gap-3 text-sm leading-relaxed text-ink/90"><span className="num mt-0.5 text-xs text-ink-faint">{i + 1}.</span><span className="flex-1">{step.text}</span><GeneratedByTag by={step.generated_by} /></li>))}</ol></Card>
      )}

      {c.sources.length > 0 && (
        <Card><CardHeader title="Sources" /><ul className="space-y-1.5 px-5 py-4 text-sm">{c.sources.map((s) => <li key={s.url}><ExternalA href={s.url}>{s.label}</ExternalA></li>)}</ul></Card>
      )}
      <p className="text-2xs leading-relaxed text-ink-faint">{c.disclaimer}</p>
    </div>
  );
}
