"use client";

import { Bookmark, BookmarkCheck, ChevronDown, ExternalLink, FlaskConical, Radio, ShieldAlert, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { mutate as globalMutate } from "swr";
import { api, errorMessage, UPGRADE_EVENT, type ApiErrorDetail } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import type { Basis, Confidence, DataSource, Evidence, Metric, Opportunity, Score, Signal, Watchlist } from "@/lib/types";
import { categoryLabel, cn, formatCompact, scoreTone, timeAgo, titleCase } from "@/lib/utils";
import { Badge, Button, Card, Dialog, Notice, ProgressBar } from "@/components/ui";

// ----------------------------------------------------------------------------- provenance & epistemic labels

export function ProvenanceBadge({ source, className }: { source: DataSource | string | null | undefined; className?: string }) {
  if (source === "demo_fixture") {
    return <Badge tone="warning" className={className} title="Fictional demonstration data - not a real project"><FlaskConical className="h-3 w-3" />Demo data</Badge>;
  }
  if (source === "live_github") {
    return <Badge tone="success" className={className} title="Collected from the public GitHub API by this instance"><Radio className="h-3 w-3" />Live GitHub</Badge>;
  }
  return null;
}

export function ConfidenceBadge({ level }: { level: Confidence | string | null | undefined }) {
  if (!level) return null;
  const tone = level === "high" ? "success" : level === "medium" ? "accent" : "neutral";
  return <Badge tone={tone} title="How much data supports this figure">{level} confidence</Badge>;
}

const BASIS_META: Record<string, { label: string; tone: "success" | "accent" | "primary" | "warning"; hint: string }> = {
  verified_fact: { label: "Verified fact", tone: "success", hint: "Copied from GitHub public data" },
  verified: { label: "Verified", tone: "success", hint: "Copied from GitHub public data" },
  calculated_metric: { label: "Calculated", tone: "accent", hint: "Computed by Signal Atlas from verified facts" },
  calculated: { label: "Calculated", tone: "accent", hint: "Computed by Signal Atlas from verified facts" },
  interpretation: { label: "Interpretation", tone: "primary", hint: "A reading of the facts - not a fact itself" },
  inferred: { label: "Inferred", tone: "primary", hint: "Inferred by classification rules - not a GitHub field" },
  hypothesis: { label: "Hypothesis", tone: "warning", hint: "Unverified idea - not validated by market evidence" },
};

export function BasisTag({ basis }: { basis: Basis | string }) {
  const meta = BASIS_META[basis] ?? { label: titleCase(basis), tone: "primary" as const, hint: "" };
  return <Badge tone={meta.tone} title={meta.hint}>{meta.label}</Badge>;
}

export function GeneratedByTag({ by }: { by: "rules" | "ai" | string }) {
  return by === "ai"
    ? <Badge tone="primary" title="Written by an AI model from the fact sheet; figures are checked against verified facts"><Sparkles className="h-3 w-3" />AI</Badge>
    : <Badge tone="neutral" title="Produced by the deterministic rules engine">Rules</Badge>;
}

export function RiskBadge({ level }: { level: string | null | undefined }) {
  if (!level) return null;
  const tone = level === "low" ? "success" : level === "medium" ? "warning" : "danger";
  return <Badge tone={tone}><ShieldAlert className="h-3 w-3" />{level} risk</Badge>;
}

export function CategoryChip({ category }: { category: string | null | undefined }) {
  return <span className="inline-flex items-center rounded-md bg-white/5 px-1.5 py-0.5 text-xs text-ink-muted">{categoryLabel(category)}</span>;
}

export function ExternalA({ href, children, className }: { href: string | null | undefined; children: ReactNode; className?: string }) {
  if (!href) return <span className={className}>{children}</span>;
  return <a href={href} target="_blank" rel="noopener noreferrer" className={cn("inline-flex items-center gap-1 text-accent hover:underline", className)}>{children}<ExternalLink className="h-3 w-3 shrink-0" /></a>;
}

// ----------------------------------------------------------------------------- score visuals

const TONE_STROKE = { success: "#10B981", accent: "#22D3EE", warning: "#F59E0B", muted: "#64748B" } as const;

export function ScoreRing({ score, size = 56, label }: { score: number | null | undefined; size?: number; label?: string }) {
  const radius = (size - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const value = score ?? 0;
  const tone = scoreTone(score);
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={`${label ?? "Score"} ${score === null || score === undefined ? "not available" : Math.round(value) + " out of 100"}`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="rgba(148,163,184,0.14)" strokeWidth={4} />
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={TONE_STROKE[tone]} strokeWidth={4} strokeLinecap="round"
          strokeDasharray={circumference} strokeDashoffset={circumference * (1 - value / 100)} style={{ transition: "stroke-dashoffset 600ms ease" }} />
      </svg>
      <span className="num absolute inset-0 flex items-center justify-center font-semibold text-ink" style={{ fontSize: size * 0.3 }}>
        {score === null || score === undefined ? "—" : Math.round(value)}
      </span>
    </div>
  );
}

export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (!evidence.length) return null;
  return (
    <ul className="space-y-1.5">
      {evidence.map((item, index) => (
        <li key={index} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          <BasisTag basis={item.kind} />
          <span className="text-ink-muted">{item.label}:</span>
          {item.source_url ? <ExternalA href={item.source_url} className="num">{item.value}</ExternalA> : <span className="num text-ink">{item.value}</span>}
        </li>
      ))}
    </ul>
  );
}

function MetricRow({ metric }: { metric: Metric }) {
  const [open, setOpen] = useState(false);
  const tone = scoreTone(metric.score);
  return (
    <div className="border-b border-line last:border-0">
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full items-center gap-4 px-5 py-3 text-left hover:bg-white/[0.02]">
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <span className="truncate text-sm text-ink">{metric.label}</span>
            <span className="flex shrink-0 items-center gap-3">
              <span className="num text-2xs text-ink-faint">weight {metric.weight}%</span>
              <span className="num w-9 text-right text-sm font-semibold text-ink">{metric.score === null ? "n/a" : Math.round(metric.score)}</span>
            </span>
          </div>
          <ProgressBar value={metric.score ?? 0} tone={tone === "muted" ? "primary" : tone} className="mt-2" />
        </div>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-ink-faint transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="space-y-3 bg-surface/60 px-5 py-4 animate-fade-in">
          <p className="text-xs leading-relaxed text-ink-muted">{metric.explanation}</p>
          <EvidenceList evidence={metric.evidence} />
          {metric.missing.length > 0 && (
            <div>
              <p className="mb-1 text-2xs font-semibold uppercase tracking-wider text-warning">Missing data</p>
              <ul className="list-disc space-y-0.5 pl-4 text-xs text-ink-muted">{metric.missing.map((m, i) => <li key={i}>{m}</li>)}</ul>
            </div>
          )}
          <p className="num text-2xs text-ink-faint">Metric confidence {(metric.confidence * 100).toFixed(0)}%</p>
        </div>
      )}
    </div>
  );
}

export function ScoreBreakdown({ score }: { score: Score }) {
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-5 border-b border-line px-5 py-4">
        <ScoreRing score={score.total} size={72} label="Business potential score" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold text-ink">Business potential score</h2>
            <ConfidenceBadge level={score.confidence} />
            {score.custom_weights && <Badge tone="primary">Custom weights</Badge>}
          </div>
          <p className="mt-1 text-xs text-ink-muted">
            Data coverage <span className="num text-ink">{Math.round(score.coverage * 100)}%</span> · data{" "}
            <span className="text-ink">{score.data_freshness.status.replace("_", " ")}</span>
            {score.data_freshness.last_synced_at && <> · synced {timeAgo(score.data_freshness.last_synced_at)}</>}
            {score.custom_weights && <> · default-weight score <span className="num text-ink">{score.default_total}</span></>}
          </p>
          {score.coverage < 0.995 && score.raw_total !== undefined && (
            <p className="mt-1 text-2xs text-ink-faint">
              Mean of scored metrics <span className="num">{score.raw_total}</span>, damped towards a neutral 50 because {Math.round((1 - score.coverage) * 100)}% of the weighting has no data yet.
            </p>
          )}
        </div>
      </div>
      <div>{score.metrics.map((metric) => <MetricRow key={metric.key} metric={metric} />)}</div>
      <div className="border-t border-line px-5 py-3"><p className="text-2xs leading-relaxed text-ink-faint">{score.methodology_note}</p></div>
    </Card>
  );
}

// ----------------------------------------------------------------------------- feed & cards

const SIGNAL_LABELS: Record<string, string> = {
  star_surge: "Star surge", unusual_growth: "Unusual growth", commit_acceleration: "Commit acceleration", breakout_new_project: "Breakout project",
  contributor_growth: "Contributor growth", release_burst: "Release burst", category_momentum: "Category momentum", emerging_cluster: "Emerging cluster",
};

export function signalLabel(type: string) {
  return SIGNAL_LABELS[type] ?? titleCase(type);
}

export function SignalCard({ signal, compact }: { signal: Signal; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const firstLink = signal.evidence.find((e) => e.source_url)?.source_url;
  return (
    <article className="border-b border-line px-5 py-4 last:border-0">
      <div className="flex items-start gap-3">
        <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-accent shadow-[0_0_10px_rgba(34,211,238,0.8)]" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-1.5">
            <Badge tone="accent">{signalLabel(signal.signal_type)}</Badge>
            <Badge tone="neutral">{signal.time_window}</Badge>
            <ConfidenceBadge level={signal.confidence} />
            <ProvenanceBadge source={signal.data_source} />
          </div>
          <h3 className="text-sm font-medium leading-snug text-ink">
            {signal.repository_id ? <Link href={`/repositories/${signal.repository_id}`} className="hover:text-primary-bright">{signal.title}</Link> : signal.title}
          </h3>
          {!compact && <p className="mt-1 text-xs leading-relaxed text-ink-muted"><span className="font-medium text-ink/80">Why it matters: </span>{signal.summary}</p>}
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-ink-faint">
            <span>Detected {timeAgo(signal.detected_at)}</span>
            {signal.category && <span>{categoryLabel(signal.category)}</span>}
            {firstLink && <ExternalA href={firstLink}>Evidence</ExternalA>}
            <button onClick={() => setOpen((v) => !v)} className="text-ink-muted underline-offset-2 hover:text-ink hover:underline" aria-expanded={open}>
              {open ? "Hide" : "Show"} evidence ({signal.evidence.length})
            </button>
          </div>
          {open && <div className="mt-3 rounded-lg border border-line bg-surface/60 p-3 animate-fade-in"><EvidenceList evidence={signal.evidence} /></div>}
        </div>
      </div>
    </article>
  );
}

export function OpportunityCard({ opportunity }: { opportunity: Opportunity }) {
  const top = [...opportunity.metrics].filter((m) => m.score !== null).sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).slice(0, 3);
  return (
    <Card className="group flex flex-col transition-colors hover:border-primary/40">
      <Link href={`/opportunities/${opportunity.id}`} className="flex flex-1 flex-col p-5">
        <div className="flex items-start gap-4">
          <ScoreRing score={opportunity.score} label="Opportunity score" />
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold text-ink group-hover:text-primary-bright">{opportunity.repository_full_name}</h3>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              <CategoryChip category={opportunity.category} />
              <RiskBadge level={opportunity.risk_level} />
              <ProvenanceBadge source={opportunity.data_source} />
            </div>
          </div>
        </div>
        <dl className="mt-4 grid grid-cols-3 gap-2 text-xs">
          <div><dt className="text-ink-faint">Maturity</dt><dd className="mt-0.5 capitalize text-ink">{opportunity.maturity}</dd></div>
          <div><dt className="text-ink-faint">Confidence</dt><dd className="mt-0.5 capitalize text-ink">{opportunity.confidence}</dd></div>
          <div><dt className="text-ink-faint">Stars</dt><dd className="num mt-0.5 text-ink">{formatCompact(opportunity.stars)}</dd></div>
        </dl>
        <div className="mt-4 space-y-2">
          {top.map((metric) => (
            <div key={metric.key} className="flex items-center gap-3 text-xs">
              <span className="w-40 shrink-0 truncate text-ink-muted">{metric.label}</span>
              <ProgressBar value={metric.score ?? 0} tone="primary" />
              <span className="num w-7 text-right text-ink">{Math.round(metric.score ?? 0)}</span>
            </div>
          ))}
        </div>
        <div className="mt-4 flex items-center justify-between border-t border-line pt-3 text-xs">
          <span className="text-ink-faint">Recommended action</span>
          <span className={cn("font-medium capitalize", opportunity.recommended_action === "investigate" ? "text-success" : opportunity.recommended_action === "monitor" ? "text-accent" : "text-ink-muted")}>
            {opportunity.recommended_action ?? "—"}
          </span>
        </div>
      </Link>
    </Card>
  );
}

export function StatCard({ label, value, hint, icon }: { label: string; value: ReactNode; hint?: string; icon?: ReactNode }) {
  return (
    <Card className="p-4" title={hint}>
      <div className="flex items-center justify-between text-ink-faint">
        <span className="text-2xs font-semibold uppercase tracking-wider">{label}</span>
        {icon}
      </div>
      <p className="num mt-2 text-2xl font-semibold tracking-tight text-ink">{value}</p>
      {hint && <p className="mt-1 line-clamp-2 text-2xs leading-snug text-ink-faint">{hint}</p>}
    </Card>
  );
}

// ----------------------------------------------------------------------------- save to watchlist

export function SaveButton({ itemType, itemId, size = "sm" }: { itemType: "repository" | "opportunity" | "developer"; itemId: number; size?: "sm" | "md" }) {
  const { canEdit } = useSession();
  const { data: saved, mutate } = useApi<{ saved: Record<string, { item_row_id: number; watchlist_id: number }> }>("/watchlists/saved", { item_type: itemType });
  const { data: lists } = useApi<{ items: Watchlist[] }>("/watchlists");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const entry = saved?.saved[String(itemId)];

  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      if (entry) {
        await api(`/watchlists/${entry.watchlist_id}/items/${entry.item_row_id}`, { method: "DELETE" });
      } else {
        const watchlistId = lists?.items[0]?.id;
        if (!watchlistId) throw new Error("Create a watchlist first.");
        await api(`/watchlists/${watchlistId}/items`, { method: "POST", body: { item_type: itemType, item_id: itemId } });
      }
      await Promise.all([mutate(), globalMutate("/watchlists")]);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!canEdit) return null;
  return (
    <span className="inline-flex items-center gap-2">
      <Button size={size} variant={entry ? "secondary" : "outline"} onClick={toggle} loading={busy} aria-pressed={!!entry} title={error ?? undefined}>
        {entry ? <BookmarkCheck className="h-4 w-4 text-primary-bright" /> : <Bookmark className="h-4 w-4" />}
        {entry ? "Saved" : "Save"}
      </Button>
      {error && <span role="alert" className="text-xs text-danger">{error}</span>}
    </span>
  );
}

// ----------------------------------------------------------------------------- upgrade prompt

export function UpgradeDialog() {
  const [detail, setDetail] = useState<ApiErrorDetail | null>(null);
  useEffect(() => {
    const handler = (event: Event) => setDetail((event as CustomEvent<ApiErrorDetail>).detail);
    window.addEventListener(UPGRADE_EVENT, handler);
    return () => window.removeEventListener(UPGRADE_EVENT, handler);
  }, []);
  return (
    <Dialog open={!!detail} onOpenChange={(open) => !open && setDetail(null)} title="Upgrade to continue" description={detail?.message}
      footer={<><Button variant="ghost" onClick={() => setDetail(null)}>Not now</Button><Link href="/settings?tab=billing" onClick={() => setDetail(null)}><Button variant="primary">View plans</Button></Link></>}>
      {detail && (
        <div className="space-y-3 text-sm text-ink-muted">
          <p>You are on the <span className="font-medium capitalize text-ink">{detail.current_plan}</span> plan
            {detail.suggested_plan && <>; the <span className="font-medium capitalize text-ink">{detail.suggested_plan}</span> plan raises this limit</>}.</p>
          {detail.limit !== null && detail.limit !== undefined && detail.used !== null && detail.used !== undefined && <ProgressBar value={detail.used} max={detail.limit} tone="warning" />}
          <Notice>Online payments are not live yet while pricing is validated, so plan changes are applied manually.</Notice>
        </div>
      )}
    </Dialog>
  );
}

export function MissingData({ items, title = "Data not yet collected" }: { items: string[]; title?: string }) {
  if (!items.length) return null;
  return (
    <Notice tone="warning" title={title}>
      <ul className="mt-1 list-disc space-y-0.5 pl-4">{items.map((item, index) => <li key={index}>{item}</li>)}</ul>
    </Notice>
  );
}

export function Avatar({ src, login, size = 28 }: { src: string | null; login: string; size?: number }) {
  return src
    ? <img src={src} alt="" width={size} height={size} style={{ width: size, height: size }} className="shrink-0 rounded-full border border-line" loading="lazy" referrerPolicy="no-referrer" />
    : <span style={{ width: size, height: size, fontSize: size * 0.4 }} className="flex shrink-0 items-center justify-center rounded-full border border-line bg-gradient-to-br from-primary/30 to-accent/20 font-semibold text-white">{login[0]?.toUpperCase()}</span>;
}
