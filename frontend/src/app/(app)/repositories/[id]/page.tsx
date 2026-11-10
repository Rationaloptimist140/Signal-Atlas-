"use client";

import { ArrowLeft, Eye, FileText, GitFork, GitPullRequest, RefreshCw, Star, Users } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useSWRConfig } from "swr";
import { api, errorMessage } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import type { Repository, Score } from "@/lib/types";
import { categoryLabel, formatDate, formatNumber, timeAgo } from "@/lib/utils";
import { CommitBars, ScoreHistory, StarArea } from "@/components/charts";
import { BasisTag, ExternalA, MissingData, ProvenanceBadge, SaveButton, ScoreBreakdown, StatCard } from "@/components/intel";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, LoadingRows, Notice, PageHeader, ProgressBar, Skeleton, Tabs, Td, Th } from "@/components/ui";

type Detail = {
  repository: Repository; category_label: string | null;
  languages: { name: string; bytes: number; share: number }[];
  technologies: { slug: string; name: string; category: string; confidence: number; method: string }[];
  score: Score | null; opportunity_id: number | null; parent: { full_name: string; repository_id: number | null } | null;
  licence: { spdx: string | null; name: string | null; assessment: string; commercial_friendliness: number; note: string };
  provenance: { data_source: string; is_demo: boolean; sync_level: string; last_synced_at: string | null; missing_data: string[] };
};
type TabKey = "overview" | "activity" | "contributors" | "dependencies" | "forks" | "releases" | "licence" | "opportunity";

function Section<T>({ path, children }: { path: string; children: (data: T) => React.ReactNode }) {
  const { data, error, isLoading, mutate } = useApi<T>(path);
  if (isLoading && !data) return <Card><LoadingRows rows={5} /></Card>;
  if (error) return <Card><ErrorState message={errorMessage(error)} onRetry={() => mutate()} /></Card>;
  return data ? <>{children(data)}</> : null;
}

export default function RepositoryDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { canEdit } = useSession();
  const { mutate: mutateAll } = useSWRConfig();
  const { data, error, isLoading, mutate } = useApi<Detail>(`/repositories/${id}`);
  const [tab, setTab] = useState<TabKey>("overview");
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<{ tone: "success" | "danger" | "accent"; text: string } | null>(null);
  const [reportBusy, setReportBusy] = useState(false);

  async function sync() {
    setSyncing(true);
    setSyncMessage(null);
    try {
      const result = await api<{ status: string; message: string }>(`/repositories/${id}/sync`, { method: "POST" });
      setSyncMessage({ tone: result.status === "succeeded" ? "success" : "accent", text: result.message });
      await mutateAll((key) => typeof key === "string" && key.startsWith(`/repositories/${id}`));
    } catch (err) {
      setSyncMessage({ tone: "danger", text: errorMessage(err) });
    } finally {
      setSyncing(false);
    }
  }

  async function generateReport() {
    setReportBusy(true);
    try {
      const report = await api<{ id: number }>("/reports/generate", { method: "POST", body: { report_type: "repository", subject_id: Number(id) } });
      router.push(`/reports/${report.id}`);
    } catch (err) {
      setSyncMessage({ tone: "danger", text: errorMessage(err) });
      setReportBusy(false);
    }
  }

  if (isLoading && !data) return <div className="space-y-4"><Skeleton className="h-10 w-80" /><Skeleton className="h-28 w-full" /><Skeleton className="h-96 w-full" /></div>;
  if (error || !data) return <Card><ErrorState message={error ? errorMessage(error) : "Repository not found."} onRetry={() => mutate()} /></Card>;
  const repo = data.repository;
  const isDemo = data.provenance.is_demo;

  return (
    <div className="space-y-6">
      <Link href="/repositories" className="inline-flex items-center gap-1.5 text-xs text-ink-muted hover:text-ink"><ArrowLeft className="h-3.5 w-3.5" />Repository Intelligence</Link>
      <PageHeader title={repo.full_name}
        description={<span className="flex flex-wrap items-center gap-2"><ProvenanceBadge source={repo.data_source} /><Badge>{repo.sync_level === "full" ? "Full sync" : "Headline data only"}</Badge>
          {repo.archived && <Badge tone="danger">Archived</Badge>}{repo.is_fork && <Badge>Fork</Badge>}<span>{categoryLabel(repo.category)}</span>
          <span className="text-ink-faint">· synced {timeAgo(data.provenance.last_synced_at)}</span></span>}
        actions={<>
          {repo.html_url && <a href={repo.html_url} target="_blank" rel="noopener noreferrer"><Button>View on GitHub</Button></a>}
          <SaveButton itemType="repository" itemId={repo.id} size="md" />
          {canEdit && !isDemo && <Button onClick={sync} loading={syncing}><RefreshCw className="h-4 w-4" />Sync</Button>}
          {canEdit && <Button variant="primary" onClick={generateReport} loading={reportBusy}><FileText className="h-4 w-4" />Generate report</Button>}
        </>} />
      {repo.description && <p className="-mt-2 max-w-4xl text-sm leading-relaxed text-ink-muted">{repo.description}</p>}
      {syncMessage && <Notice tone={syncMessage.tone}>{syncMessage.text}</Notice>}
      {isDemo && <Notice tone="warning" title="Demonstration fixture.">This project and every figure on this page are fictional. It has no GitHub page and cannot be synced.</Notice>}
      {repo.sync_level !== "full" && !isDemo && <Notice tone="accent" title="Headline data only.">Commit activity, contributors, releases, forks and dependencies are collected by a full sync. {canEdit ? "Choose Sync, or save the repository to a watchlist." : ""}</Notice>}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatCard label="Stars" value={formatNumber(repo.stars)} icon={<Star className="h-4 w-4" />} />
        <StatCard label="Forks" value={formatNumber(repo.forks)} icon={<GitFork className="h-4 w-4" />} />
        <StatCard label="Watchers" value={formatNumber(repo.watchers)} icon={<Eye className="h-4 w-4" />} hint={repo.watchers === null ? "Collected by a full sync" : undefined} />
        <StatCard label="Contributors" value={formatNumber(repo.contributors_count)} icon={<Users className="h-4 w-4" />} hint={repo.contributors_count === null ? "Collected by a full sync" : undefined} />
        <StatCard label="Open issues + PRs" value={formatNumber(repo.open_issues)} icon={<GitPullRequest className="h-4 w-4" />} />
        <StatCard label="Score" value={data.score ? Math.round(data.score.total) : "—"} hint={data.score ? `${data.score.confidence} confidence` : "Not scored yet"} />
      </div>

      <Tabs<TabKey> value={tab} onChange={setTab} tabs={[
        { value: "overview", label: "Overview" }, { value: "activity", label: "Development activity" }, { value: "contributors", label: "Contributor network" },
        { value: "dependencies", label: "Dependencies" }, { value: "forks", label: "Fork family" }, { value: "releases", label: "Releases" },
        { value: "licence", label: "Licence & compliance" }, { value: "opportunity", label: "Commercial opportunity" }]} />

      {tab === "overview" && (
        <div className="grid gap-6 xl:grid-cols-[1fr_1.1fr]">
          <div className="space-y-6">
            <Card>
              <CardHeader title="Repository facts" description="Verified from the GitHub API" />
              <dl className="grid grid-cols-2 gap-x-6 gap-y-4 p-5 text-sm">
                {[["Owner", `${repo.owner_login}${repo.owner_type ? ` (${repo.owner_type})` : ""}`], ["Primary language", repo.primary_language ?? "—"], ["Licence", repo.license_spdx ?? "None detected"],
                  ["Created", formatDate(repo.created_at_github)], ["Last push", timeAgo(repo.pushed_at_github)], ["First seen by Signal Atlas", formatDate(repo.first_seen_at)]].map(([k, v]) => (
                  <div key={k}><dt className="text-xs text-ink-faint">{k}</dt><dd className="mt-0.5 text-ink">{v}</dd></div>
                ))}
                {repo.homepage && !isDemo && <div className="col-span-2"><dt className="text-xs text-ink-faint">Website</dt><dd className="mt-0.5"><ExternalA href={repo.homepage}>{repo.homepage}</ExternalA></dd></div>}
                {data.parent && <div className="col-span-2"><dt className="text-xs text-ink-faint">Forked from</dt><dd className="mt-0.5 text-ink">{data.parent.repository_id ? <Link className="text-accent hover:underline" href={`/repositories/${data.parent.repository_id}`}>{data.parent.full_name}</Link> : data.parent.full_name}</dd></div>}
              </dl>
              {repo.topics.length > 0 && <div className="flex flex-wrap gap-1.5 border-t border-line px-5 py-4">{repo.topics.map((t) => <span key={t} className="rounded-md bg-white/5 px-2 py-0.5 text-xs text-ink-muted">{t}</span>)}</div>}
            </Card>
            <Card>
              <CardHeader title="Technology classification" description="Inferred from topics, name and description — not a GitHub field" />
              {data.technologies.length ? (
                <ul className="divide-y divide-line">{data.technologies.map((t) => (
                  <li key={t.slug} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
                    <Link href={`/technologies?technology=${t.slug}`} className="text-ink hover:text-primary-bright">{t.name}</Link>
                    <span className="flex items-center gap-2 text-xs text-ink-faint"><BasisTag basis="inferred" /><span>{t.method.replace("keyword:", "matched on ")}</span><span className="num">{Math.round(t.confidence * 100)}%</span></span>
                  </li>))}</ul>
              ) : <EmptyState title="No technology matched" description="The classifier found no known technology keywords for this repository." />}
            </Card>
            {data.languages.length > 0 && (
              <Card>
                <CardHeader title="Languages" description="Share of code by bytes (GitHub linguist)" />
                <ul className="space-y-3 p-5">{data.languages.slice(0, 8).map((l) => (
                  <li key={l.name}><div className="mb-1 flex justify-between text-xs"><span className="text-ink">{l.name}</span><span className="num text-ink-muted">{(l.share * 100).toFixed(1)}%</span></div><ProgressBar value={l.share * 100} tone="accent" /></li>))}</ul>
              </Card>
            )}
          </div>
          <div className="space-y-6">
            {data.score ? <ScoreBreakdown score={data.score} /> : <Card><EmptyState title="Not scored yet" description="Scores are computed after the next intelligence run." /></Card>}
            <MissingData items={data.provenance.missing_data} />
          </div>
        </div>
      )}

      {tab === "activity" && (
        <Section<{ commit_activity: { week_start: string; commits: number }[]; commit_activity_available: boolean; snapshots: { date: string; stars: number }[]; snapshot_note: string;
          issues: { open: number | null; closed: number | null; open_prs: number | null; merged_prs: number | null; note: string | null };
          change_events: { id: number; event_type: string; title: string; evidence_url: string | null; occurred_at: string }[] }> path={`/repositories/${id}/activity`}>
          {(activity) => (
            <div className="grid gap-6 xl:grid-cols-2">
              <Card><CardHeader title="Commit frequency" description="Commits per week over the last year (GitHub statistics)" />
                {activity.commit_activity_available ? <div className="p-3"><CommitBars data={activity.commit_activity} /></div> : <EmptyState title="Commit history not collected yet" description="Collected during a full sync. GitHub computes these statistics lazily, so the first sync may need a retry." />}</Card>
              <Card><CardHeader title="Star history" description={activity.snapshot_note} />
                {activity.snapshots.length >= 2 ? <div className="p-3"><StarArea data={activity.snapshots} /></div> : <EmptyState title="One snapshot so far" description="A trend line appears once Signal Atlas has recorded stars on at least two different days." />}</Card>
              <Card><CardHeader title="Issues and pull requests" />
                <dl className="grid grid-cols-2 gap-4 p-5 sm:grid-cols-4">{[["Open issues + PRs", activity.issues.open], ["Closed issues", activity.issues.closed], ["Open PRs", activity.issues.open_prs], ["Merged PRs", activity.issues.merged_prs]].map(([k, v]) => (
                  <div key={k as string}><dt className="text-xs text-ink-faint">{k}</dt><dd className="num mt-1 text-xl font-semibold text-ink">{formatNumber(v as number | null)}</dd></div>))}</dl>
                {activity.issues.note && <div className="px-5 pb-5"><Notice tone="warning" title="Partly unavailable.">{activity.issues.note}</Notice></div>}</Card>
              <Card><CardHeader title="Detected changes" description="Releases, dependency and stack changes found since monitoring began" />
                {activity.change_events.length ? <ul className="divide-y divide-line">{activity.change_events.map((e) => (
                  <li key={e.id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm"><span className="min-w-0"><Badge tone="accent">{e.event_type.replace("_", " ")}</Badge><span className="ml-2 text-ink">{e.title}</span></span>
                    <span className="flex shrink-0 items-center gap-3 text-xs text-ink-faint">{timeAgo(e.occurred_at)}{e.evidence_url && <ExternalA href={e.evidence_url}>Source</ExternalA>}</span></li>))}</ul>
                  : <EmptyState title="No changes detected yet" description="Change detection compares each full sync with the previous one." />}</Card>
            </div>
          )}
        </Section>
      )}

      {tab === "contributors" && (
        <Section<{ total_contributors: number | null; contributors: { developer_id: number; login: string; name: string | null; avatar_url: string | null; contributions: number; share_of_listed: number }[]; top_contributor_share: number | null; note: string }> path={`/repositories/${id}/contributors`}>
          {(c) => (
            <Card><CardHeader title="Contributor network" description={c.note} action={c.total_contributors !== null && <span className="num text-xs text-ink-muted">{formatNumber(c.total_contributors)} total</span>} />
              {c.top_contributor_share !== null && c.top_contributor_share > 0.7 && <div className="px-5 pt-4"><Notice tone="warning" title="Key-person dependency."><BasisTag basis="calculated" /> One account made {Math.round(c.top_contributor_share * 100)}% of commits among the listed contributors.</Notice></div>}
              {c.contributors.length ? <table className="w-full"><thead className="bg-surface/60"><tr><Th>Developer</Th><Th className="text-right">Commits</Th><Th className="w-1/3">Share of listed</Th></tr></thead>
                <tbody className="divide-y divide-line">{c.contributors.map((d) => (
                  <tr key={d.developer_id} className="hover:bg-white/[0.02]"><Td><Link href={`/developers/${d.developer_id}`} className="flex items-center gap-2.5 text-ink hover:text-primary-bright">
                    {d.avatar_url ? <img src={d.avatar_url} alt="" width={24} height={24} className="h-6 w-6 rounded-full" loading="lazy" referrerPolicy="no-referrer" /> : <span className="flex h-6 w-6 items-center justify-center rounded-full bg-white/10 text-[10px]">{d.login[0]?.toUpperCase()}</span>}
                    {d.login}{d.name && <span className="text-xs text-ink-faint">{d.name}</span>}</Link></Td>
                    <Td className="num text-right">{formatNumber(d.contributions)}</Td><Td><ProgressBar value={d.share_of_listed * 100} /></Td></tr>))}</tbody></table>
                : <EmptyState title="Contributors not collected yet" description="Collected during a full sync." />}</Card>
          )}
        </Section>
      )}

      {tab === "dependencies" && (
        <Section<{ dependencies: { ecosystem: string; package_name: string; version_spec: string | null; dep_type: string; manifest_path: string; used_by_tracked_repositories: number }[]; analysed: boolean; note: string }> path={`/repositories/${id}/dependencies`}>
          {(d) => (
            <Card><CardHeader title="Dependencies" description={d.note} action={<span className="num text-xs text-ink-muted">{d.dependencies.length} declared</span>} />
              {d.dependencies.length ? <div className="overflow-x-auto"><table className="w-full"><thead className="bg-surface/60"><tr><Th>Package</Th><Th>Ecosystem</Th><Th>Version</Th><Th>Type</Th><Th>Manifest</Th><Th className="text-right">Used by tracked repos</Th></tr></thead>
                <tbody className="divide-y divide-line">{d.dependencies.map((dep) => (
                  <tr key={`${dep.ecosystem}-${dep.package_name}-${dep.dep_type}`}><Td className="num text-ink">{dep.package_name}</Td><Td><Badge>{dep.ecosystem}</Badge></Td><Td className="num text-xs text-ink-muted">{dep.version_spec ?? "—"}</Td>
                    <Td className="text-xs text-ink-muted">{dep.dep_type}</Td><Td className="num text-xs text-ink-faint">{dep.manifest_path}</Td><Td className="num text-right">{dep.used_by_tracked_repositories}</Td></tr>))}</tbody></table></div>
                : <EmptyState title={d.analysed ? "No supported manifest found" : "Dependencies not analysed yet"} description={d.analysed ? "This repository has no root-level package.json, requirements.txt, pyproject.toml, go.mod or Cargo.toml." : "Analysed during a full sync."} />}</Card>
          )}
        </Section>
      )}

      {tab === "forks" && (
        <Section<{ total_forks: number; is_fork: boolean; parent: { full_name: string; repository_id: number | null; html_url: string | null } | null; forks: { full_name: string; html_url: string | null; stars: number; pushed_at: string | null }[]; note: string }> path={`/repositories/${id}/forks`}>
          {(f) => (
            <Card><CardHeader title="Fork family tree" description={f.note} action={<span className="num text-xs text-ink-muted">{formatNumber(f.total_forks)} forks on GitHub</span>} />
              <div className="p-5">
                {f.parent && <div className="mb-3 flex items-center gap-2 text-sm"><Badge tone="primary">Parent</Badge>{f.parent.repository_id ? <Link href={`/repositories/${f.parent.repository_id}`} className="text-accent hover:underline">{f.parent.full_name}</Link> : <ExternalA href={f.parent.html_url}>{f.parent.full_name}</ExternalA>}</div>}
                <div className="flex items-center gap-2 text-sm"><Badge tone="accent">{f.is_fork ? "This fork" : "Root"}</Badge><span className="font-medium text-ink">{repo.full_name}</span></div>
                {f.forks.length ? <ul className="ml-3 mt-2 space-y-1.5 border-l border-line-strong pl-5">{f.forks.map((fork) => (
                  <li key={fork.full_name} className="relative flex items-center justify-between gap-3 text-sm before:absolute before:-left-5 before:top-1/2 before:h-px before:w-4 before:bg-line-strong">
                    {fork.html_url ? <ExternalA href={fork.html_url}>{fork.full_name}</ExternalA> : <span className="text-ink-muted">{fork.full_name}</span>}
                    <span className="num flex shrink-0 gap-4 text-xs text-ink-faint"><span>★ {formatNumber(fork.stars)}</span><span>pushed {timeAgo(fork.pushed_at)}</span></span></li>))}</ul>
                  : <p className="mt-4 text-sm text-ink-muted">{f.total_forks > 0 ? "Forks are collected during a full sync." : "This repository has no forks."}</p>}
              </div></Card>
          )}
        </Section>
      )}

      {tab === "releases" && (
        <Section<{ releases: { tag_name: string; name: string | null; published_at: string | null; prerelease: boolean; html_url: string | null; body_excerpt: string | null }[]; analysed: boolean }> path={`/repositories/${id}/releases`}>
          {(r) => (
            <Card><CardHeader title="Release history" description="Most recent 30 published releases" />
              {r.releases.length ? <ol className="divide-y divide-line">{r.releases.map((rel) => (
                <li key={rel.tag_name} className="px-5 py-3.5"><div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="flex items-center gap-2"><span className="num text-sm font-medium text-ink">{rel.tag_name}</span>{rel.name && rel.name !== rel.tag_name && <span className="text-sm text-ink-muted">{rel.name}</span>}{rel.prerelease && <Badge tone="warning">Pre-release</Badge>}</span>
                  <span className="flex items-center gap-3 text-xs text-ink-faint">{formatDate(rel.published_at)}{rel.html_url && <ExternalA href={rel.html_url}>Notes</ExternalA>}</span></div>
                  {rel.body_excerpt && <p className="mt-1.5 line-clamp-2 whitespace-pre-line text-xs text-ink-muted">{rel.body_excerpt}</p>}</li>))}</ol>
                : <EmptyState title={r.analysed ? "No published releases" : "Releases not collected yet"} description={r.analysed ? "This project does not use GitHub Releases." : "Collected during a full sync."} />}</Card>
          )}
        </Section>
      )}

      {tab === "licence" && (
        <Card><CardHeader title="Licence and compliance" description="Automated reading of the detected licence" />
          <div className="space-y-4 p-5">
            <div className="flex flex-wrap items-center gap-3"><span className="num text-2xl font-semibold text-ink">{data.licence.spdx ?? "No licence detected"}</span>{data.licence.name && <span className="text-sm text-ink-muted">{data.licence.name}</span>}<BasisTag basis={data.licence.spdx ? "verified_fact" : "interpretation"} /></div>
            <div><p className="mb-1.5 flex items-center gap-2 text-xs text-ink-faint"><BasisTag basis="interpretation" />Commercial reuse friendliness</p>
              <div className="flex items-center gap-3"><ProgressBar value={data.licence.commercial_friendliness} tone={data.licence.commercial_friendliness >= 70 ? "success" : data.licence.commercial_friendliness >= 40 ? "warning" : "danger"} className="max-w-sm" /><span className="num text-sm text-ink">{data.licence.commercial_friendliness}/100</span></div></div>
            <p className="text-sm leading-relaxed text-ink-muted">{data.licence.assessment}.</p>
            <Notice tone="warning" title="Not legal advice.">{data.licence.note} Licences can differ per directory and may change between versions; confirm with a qualified adviser before commercial use.</Notice>
          </div></Card>
      )}

      {tab === "opportunity" && (
        <div className="grid gap-6 xl:grid-cols-2">
          <Card><CardHeader title="Commercial opportunity analysis" />
            {data.opportunity_id ? (
              <div className="space-y-4 p-5"><p className="text-sm text-ink-muted">This repository meets the threshold for an opportunity hypothesis, with target customers, monetisation models, risks and next steps.</p>
                <div className="flex flex-wrap gap-2"><Link href={`/opportunities/${data.opportunity_id}`}><Button variant="primary">Open opportunity analysis</Button></Link>{canEdit && <Button onClick={generateReport} loading={reportBusy}><FileText className="h-4 w-4" />Generate report</Button>}</div>
                <Notice>Opportunities are unverified hypotheses. Popularity is not evidence of commercial demand.</Notice></div>
            ) : <EmptyState title="No opportunity hypothesis" description="Forks, archived repositories and repositories scoring under 30 are not turned into opportunity hypotheses." />}</Card>
          <Card><CardHeader title="Score history" description="Default-weight score over time" />
            <Section<Score> path={`/repositories/${id}/score`}>{(score) => score.history && score.history.length >= 2 ? <div className="p-3"><ScoreHistory data={score.history} height={200} /></div> : <EmptyState title="One score so far" description="History builds up as intelligence runs repeat." />}</Section></Card>
        </div>
      )}
    </div>
  );
}
