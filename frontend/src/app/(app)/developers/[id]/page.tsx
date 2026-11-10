"use client";

import { ArrowLeft, Building2, MapPin, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import type { Developer } from "@/lib/types";
import { categoryLabel, formatDate, formatNumber, timeAgo } from "@/lib/utils";
import { Avatar, ProvenanceBadge, SaveButton, StatCard } from "@/components/intel";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Notice, PageHeader, ProgressBar, Skeleton, Td, Th } from "@/components/ui";

type Profile = {
  public_profile: { developer: Developer; note: string };
  contribution_activity: { repositories: { repository_id: number; full_name: string; primary_language: string | null; category: string | null; stars: number; contributions: number }[]; tracked_contributions: number; note: string };
  owned_repositories: { repository_id: number; full_name: string }[];
  inferred: { languages: { language: string; share: number }[]; specialisations: { category: string; label: string; share: number }[]; emerging: boolean; note: string };
  collaboration_network: { collaborators: { developer_id: number; login: string; avatar_url: string | null; shared_repositories: number }[]; note: string };
  influence_indicators: { followers: number | null; public_repos: number | null; stars_on_contributed_repositories: number; account_age_days: number | null; disclaimer: string };
  provenance: { data_source: string; is_demo: boolean; sync_level: string; last_synced_at: string | null };
};

function InferredBadge() {
  return <Badge tone="primary" title="Derived by Signal Atlas, not stated by the developer">Inferred analysis</Badge>;
}
function PublicBadge() {
  return <Badge tone="success" title="Taken from the public GitHub profile or API">Public data</Badge>;
}

export default function DeveloperDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { canEdit } = useSession();
  const { data, error, isLoading, mutate } = useApi<Profile>(`/developers/${id}`);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "danger" | "accent"; text: string } | null>(null);

  async function refresh() {
    setBusy(true);
    setMessage(null);
    try {
      const result = await api<{ status: string; message: string }>(`/developers/${id}/sync`, { method: "POST" });
      setMessage({ tone: result.status === "succeeded" ? "success" : "accent", text: result.message });
      await mutate();
    } catch (err) {
      setMessage({ tone: "danger", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  if (isLoading && !data) return <div className="space-y-4"><Skeleton className="h-12 w-72" /><Skeleton className="h-96 w-full" /></div>;
  if (error || !data) return <Card><ErrorState message={error ? errorMessage(error) : "Developer not found."} onRetry={() => mutate()} /></Card>;
  const dev = data.public_profile.developer;
  const influence = data.influence_indicators;

  return (
    <div className="space-y-6">
      <Link href="/developers" className="inline-flex items-center gap-1.5 text-xs text-ink-muted hover:text-ink"><ArrowLeft className="h-3.5 w-3.5" />Developer Intelligence</Link>
      <div className="flex items-center gap-4"><Avatar src={dev.avatar_url} login={dev.login} size={56} />
        <div className="min-w-0 flex-1"><PageHeader title={dev.name ? `${dev.name} (${dev.login})` : dev.login}
          description={<span className="flex flex-wrap items-center gap-2"><ProvenanceBadge source={dev.data_source} /><Badge>{dev.account_type}</Badge>{data.inferred.emerging && <Badge tone="accent" title="Inferred: account under two years old with 50+ commits to tracked repositories">Emerging contributor</Badge>}
            {dev.company && <span className="inline-flex items-center gap-1"><Building2 className="h-3.5 w-3.5" />{dev.company}</span>}{dev.location && <span className="inline-flex items-center gap-1"><MapPin className="h-3.5 w-3.5" />{dev.location}</span>}
            <span className="text-ink-faint">· profile {dev.sync_level === "full" ? `refreshed ${timeAgo(dev.last_synced_at)}` : "not yet refreshed"}</span></span>}
          actions={<>{dev.html_url && <a href={dev.html_url} target="_blank" rel="noopener noreferrer"><Button>View on GitHub</Button></a>}<SaveButton itemType="developer" itemId={dev.id} size="md" />
            {canEdit && !data.provenance.is_demo && <Button onClick={refresh} loading={busy}><RefreshCw className="h-4 w-4" />Refresh profile</Button>}</>} /></div></div>
      {message && <Notice tone={message.tone}>{message.text}</Notice>}
      {data.provenance.is_demo && <Notice tone="warning" title="Demonstration fixture.">This developer is fictional.</Notice>}
      {dev.bio && <p className="max-w-3xl text-sm text-ink-muted">{dev.bio}</p>}

      <section aria-label="Influence indicators">
        <div className="mb-2 flex items-center gap-2"><h2 className="text-sm font-semibold text-ink">Influence indicators</h2><PublicBadge /></div>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard label="Followers" value={formatNumber(influence.followers)} hint={influence.followers === null ? "Refresh the profile to load" : undefined} />
          <StatCard label="Public repositories" value={formatNumber(influence.public_repos)} />
          <StatCard label="Commits to tracked repos" value={formatNumber(data.contribution_activity.tracked_contributions)} />
          <StatCard label="Stars on contributed repos" value={formatNumber(influence.stars_on_contributed_repositories)} />
        </div>
        <Notice className="mt-3" tone="warning" title="Visibility is not ability.">{influence.disclaimer}</Notice>
      </section>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Card><CardHeader title={<span className="flex items-center gap-2">Contribution history <PublicBadge /></span>} description={data.contribution_activity.note} />
          {data.contribution_activity.repositories.length ? <div className="overflow-x-auto"><table className="w-full"><thead className="bg-surface/60"><tr><Th>Repository</Th><Th>Category</Th><Th>Language</Th><Th className="text-right">Commits</Th></tr></thead>
            <tbody className="divide-y divide-line">{data.contribution_activity.repositories.map((r) => (
              <tr key={r.repository_id} className="hover:bg-white/[0.02]"><Td><Link href={`/repositories/${r.repository_id}`} className="text-ink hover:text-primary-bright">{r.full_name}</Link>
                {data.owned_repositories.some((o) => o.repository_id === r.repository_id) && <Badge tone="primary" className="ml-2">Owner</Badge>}</Td>
                <Td className="text-xs text-ink-muted">{categoryLabel(r.category)}</Td><Td className="text-xs text-ink-muted">{r.primary_language ?? "—"}</Td><Td className="num text-right">{formatNumber(r.contributions)}</Td></tr>))}</tbody></table></div>
            : <EmptyState title="No tracked contributions" description="This developer has no recorded commits to repositories tracked by Signal Atlas." />}</Card>

        <div className="space-y-6">
          <Card><CardHeader title={<span className="flex items-center gap-2">Technical specialisation <InferredBadge /></span>} description={data.inferred.note} />
            <div className="space-y-5 p-5">
              <div><p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-ink-faint">Languages</p>
                {data.inferred.languages.length ? <ul className="space-y-2.5">{data.inferred.languages.map((l) => (
                  <li key={l.language}><div className="mb-1 flex justify-between text-xs"><span className="text-ink">{l.language}</span><span className="num text-ink-muted">{Math.round(l.share * 100)}%</span></div><ProgressBar value={l.share * 100} tone="accent" /></li>))}</ul> : <p className="text-sm text-ink-muted">Not enough data.</p>}</div>
              <div><p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-ink-faint">Areas</p>
                {data.inferred.specialisations.length ? <ul className="space-y-2.5">{data.inferred.specialisations.map((s) => (
                  <li key={s.category}><div className="mb-1 flex justify-between text-xs"><span className="text-ink">{s.label}</span><span className="num text-ink-muted">{Math.round(s.share * 100)}%</span></div><ProgressBar value={s.share * 100} /></li>))}</ul> : <p className="text-sm text-ink-muted">Not enough data.</p>}</div>
            </div></Card>
          <Card><CardHeader title={<span className="flex items-center gap-2">Collaboration network <InferredBadge /></span>} description={data.collaboration_network.note} />
            {data.collaboration_network.collaborators.length ? <ul className="divide-y divide-line">{data.collaboration_network.collaborators.map((c) => (
              <li key={c.developer_id}><Link href={`/developers/${c.developer_id}`} className="flex items-center justify-between gap-3 px-5 py-2.5 hover:bg-white/[0.03]">
                <span className="flex items-center gap-2.5 text-sm text-ink"><Avatar src={c.avatar_url} login={c.login} size={24} />{c.login}</span>
                <span className="num text-xs text-ink-faint">{c.shared_repositories} shared repo{c.shared_repositories === 1 ? "" : "s"}</span></Link></li>))}</ul>
              : <EmptyState title="No co-contributors found" />}</Card>
          <Card><CardHeader title={<span className="flex items-center gap-2">Public profile <PublicBadge /></span>} description={data.public_profile.note} />
            <dl className="grid grid-cols-2 gap-4 p-5 text-sm">
              <div><dt className="text-xs text-ink-faint">Account created</dt><dd className="mt-0.5 text-ink">{formatDate(dev.created_at_github)}</dd></div>
              <div><dt className="text-xs text-ink-faint">Following</dt><dd className="num mt-0.5 text-ink">{formatNumber(dev.following)}</dd></div>
            </dl></Card>
        </div>
      </div>
    </div>
  );
}
