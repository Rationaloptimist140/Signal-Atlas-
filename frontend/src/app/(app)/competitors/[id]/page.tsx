"use client";

import { ArrowLeft, FileText, Plus, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { api, errorMessage } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import type { Repository } from "@/lib/types";
import { formatDate, formatNumber, timeAgo } from "@/lib/utils";
import { normaliseRepoFullName, validateRepoFullName } from "@/lib/validation";
import { ExternalA, ProvenanceBadge, ScoreRing } from "@/components/intel";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Input, Notice, PageHeader, Skeleton, Td, Th } from "@/components/ui";

type Row = { repository_id: number; full_name: string; stars: number; forks: number; contributors: number | null; primary_language: string | null; pushed_at: string | null; score: number | null;
  stars_30d_change: number | null; latest_release: { tag_name: string; published_at: string | null; html_url: string | null } | null; sync_level: string; data_source: "live_github" | "demo_fixture" };
type Change = { id: number; repository_id: number; repository_full_name: string; event_type: string; title: string; details: { added?: string[]; removed?: string[]; notes_excerpt?: string; from?: string; to?: string }; evidence_url: string | null; occurred_at: string };
type Detail = { competitor: { id: number; name: string; description: string | null; website: string | null; created_at: string }; repositories: Repository[]; comparison: Row[]; changes: Change[]; monitoring_note: string };

function changeMeaning(change: Change): string {
  if (change.event_type === "release") return "A new release signals shipped functionality. Read the notes for features that overlap with your roadmap.";
  if (change.event_type === "dependency_change") return "New runtime dependencies often reveal features under development; removed ones can indicate a rewrite or a change of vendor.";
  if (change.event_type === "stack_change") return "A change of primary language suggests a significant re-architecture.";
  return "A change was detected on this repository.";
}

export default function CompetitorDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { canEdit } = useSession();
  const { data, error, isLoading, mutate } = useApi<Detail>(`/competitors/${id}`);
  const [repo, setRepo] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function run(key: string, action: () => Promise<void>) {
    setBusy(key);
    setMessage(null);
    try {
      await action();
    } catch (err) {
      setMessage(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }
  const addRepo = (event: FormEvent) => {
    event.preventDefault();
    const invalid = validateRepoFullName(repo);
    if (invalid) return setMessage(invalid);
    void run("add", async () => { await api(`/competitors/${id}/repositories`, { method: "POST", body: { full_name: normaliseRepoFullName(repo) } }); setRepo(""); await mutate(); });
  };
  const removeRepo = (repositoryId: number) => run(`rm-${repositoryId}`, async () => { await api(`/competitors/${id}/repositories/${repositoryId}`, { method: "DELETE" }); await mutate(); });
  const report = () => run("report", async () => { const r = await api<{ id: number }>("/reports/generate", { method: "POST", body: { report_type: "competitor", subject_id: Number(id) } }); router.push(`/reports/${r.id}`); });
  const remove = () => { if (window.confirm("Stop monitoring this competitor?")) void run("delete", async () => { await api(`/competitors/${id}`, { method: "DELETE" }); router.push("/competitors"); }); };

  if (isLoading && !data) return <div className="space-y-4"><Skeleton className="h-12 w-72" /><Skeleton className="h-80 w-full" /></div>;
  if (error || !data) return <Card><ErrorState message={error ? errorMessage(error) : "Competitor not found."} onRetry={() => mutate()} /></Card>;

  return (
    <div className="space-y-6">
      <Link href="/competitors" className="inline-flex items-center gap-1.5 text-xs text-ink-muted hover:text-ink"><ArrowLeft className="h-3.5 w-3.5" />Competitor Intelligence</Link>
      <PageHeader title={data.competitor.name}
        description={<span className="flex flex-wrap items-center gap-3">{data.competitor.website && <ExternalA href={data.competitor.website}>{data.competitor.website}</ExternalA>}<span>Monitoring since {formatDate(data.competitor.created_at)}</span></span>}
        actions={canEdit && <><Button variant="primary" onClick={report} loading={busy === "report"} disabled={!data.comparison.length}><FileText className="h-4 w-4" />Generate change report</Button>
          <Button variant="danger" onClick={remove} loading={busy === "delete"}><Trash2 className="h-4 w-4" />Remove</Button></>} />
      {message && <Notice tone="danger">{message}</Notice>}

      <Card>
        <CardHeader title="Competitive comparison" description="Monitored repositories side by side" />
        {data.comparison.length ? <div className="overflow-x-auto scrollbar-thin"><table className="w-full min-w-[880px]">
          <thead className="bg-surface/60"><tr><Th>Repository</Th><Th className="text-right">Stars</Th><Th className="text-right">30-day change</Th><Th className="text-right">Contributors</Th><Th>Latest release</Th><Th>Last push</Th><Th className="text-center">Score</Th><Th /></tr></thead>
          <tbody className="divide-y divide-line">{data.comparison.map((row) => (
            <tr key={row.repository_id} className="hover:bg-white/[0.02]">
              <Td><Link href={`/repositories/${row.repository_id}`} className="font-medium text-ink hover:text-primary-bright">{row.full_name}</Link><span className="ml-2 inline-flex gap-1 align-middle"><ProvenanceBadge source={row.data_source} />{row.sync_level !== "full" && <Badge tone="warning">Sync pending</Badge>}</span></Td>
              <Td className="num text-right">{formatNumber(row.stars)}</Td>
              <Td className="num text-right">{row.stars_30d_change === null ? <span className="text-ink-faint" title="Needs a snapshot at least 30 days old">—</span> : <span className={row.stars_30d_change >= 0 ? "text-success" : "text-danger"}>{row.stars_30d_change >= 0 ? "+" : ""}{formatNumber(row.stars_30d_change)}</span>}</Td>
              <Td className="num text-right text-ink-muted">{formatNumber(row.contributors)}</Td>
              <Td className="text-xs">{row.latest_release ? <span><span className="num text-ink">{row.latest_release.tag_name}</span> <span className="text-ink-faint">{timeAgo(row.latest_release.published_at)}</span></span> : <span className="text-ink-faint">—</span>}</Td>
              <Td className="whitespace-nowrap text-xs text-ink-muted">{timeAgo(row.pushed_at)}</Td>
              <Td><div className="flex justify-center"><ScoreRing score={row.score} size={36} /></div></Td>
              <Td className="text-right">{canEdit && <Button variant="ghost" size="icon" onClick={() => removeRepo(row.repository_id)} loading={busy === `rm-${row.repository_id}`} aria-label={`Detach ${row.full_name}`}><X className="h-4 w-4" /></Button>}</Td>
            </tr>))}</tbody></table></div>
          : <EmptyState title="No repositories attached" description="Attach this competitor's public repositories to begin monitoring." />}
        {canEdit && (
          <form onSubmit={addRepo} className="flex flex-col gap-2 border-t border-line p-4 sm:flex-row">
            <Input value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="owner/repository" aria-label="Repository to attach" className="sm:max-w-sm" />
            <Button type="submit" loading={busy === "add"}><Plus className="h-4 w-4" />Attach repository</Button>
          </form>
        )}
      </Card>

      <Card>
        <CardHeader title="What changed" description="Detected changes, newest first, with why each might matter commercially" />
        {data.changes.length ? <ol className="divide-y divide-line">{data.changes.map((change) => (
          <li key={change.id} className="px-5 py-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-2"><Badge tone="accent">{change.event_type.replace("_", " ")}</Badge><span className="text-sm font-medium text-ink">{change.title}</span></span>
              <span className="flex items-center gap-3 text-xs text-ink-faint">{timeAgo(change.occurred_at)}{change.evidence_url && <ExternalA href={change.evidence_url}>Source</ExternalA>}</span>
            </div>
            {(change.details.added?.length || change.details.removed?.length) ? (
              <p className="num mt-2 text-xs text-ink-muted">{change.details.added?.length ? <span className="text-success">+ {change.details.added.join(", ")}</span> : null}{change.details.added?.length && change.details.removed?.length ? "   " : ""}
                {change.details.removed?.length ? <span className="text-danger">− {change.details.removed.join(", ")}</span> : null}</p>) : null}
            {change.details.notes_excerpt && <p className="mt-2 line-clamp-3 whitespace-pre-line text-xs text-ink-muted">{change.details.notes_excerpt}</p>}
            <p className="mt-2 text-xs leading-relaxed text-ink-faint"><span className="font-medium text-ink-muted">Why it might matter: </span>{changeMeaning(change)}</p>
          </li>))}</ol>
          : <EmptyState title="No changes detected yet" description={data.monitoring_note} />}
      </Card>
      <Notice>{data.monitoring_note}</Notice>
    </div>
  );
}
