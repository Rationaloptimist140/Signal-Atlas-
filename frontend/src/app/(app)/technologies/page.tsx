"use client";

import { Sparkles } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { errorMessage } from "@/lib/api";
import { useIntel } from "@/lib/session";
import type { Repository } from "@/lib/types";
import { CATEGORY_COLORS, cn, formatCompact } from "@/lib/utils";
import { EcosystemCard } from "@/components/dashboard-sections";
import { ProvenanceBadge, ScoreRing } from "@/components/intel";
import { Badge, Card, CardHeader, EmptyState, ErrorState, LoadingRows, Notice, PageHeader, Skeleton } from "@/components/ui";

type Tech = { slug: string; name: string; category: string; category_label: string; repositories: number; total_stars: number; new_repositories_12m: number; frontier: boolean };
type TechList = { items: Tech[]; categories: { key: string; label: string }[]; note: string };
type TechDetail = { technology: { slug: string; name: string; category_label: string; frontier: boolean }; top_repositories: Repository[]; new_repositories_12m: Repository[] };

function RepoList({ repos }: { repos: Repository[] }) {
  if (!repos.length) return <EmptyState title="No repositories yet" />;
  return (
    <ul className="divide-y divide-line">{repos.map((repo) => (
      <li key={repo.id}><Link href={`/repositories/${repo.id}`} className="flex items-center gap-3 px-5 py-2.5 hover:bg-white/[0.03]">
        <ScoreRing score={repo.score} size={34} />
        <span className="min-w-0 flex-1"><span className="block truncate text-sm text-ink">{repo.full_name}</span><span className="block truncate text-xs text-ink-faint">{repo.description ?? "No description"}</span></span>
        <span className="num shrink-0 text-xs text-ink-muted">★ {formatCompact(repo.stars)}</span><ProvenanceBadge source={repo.data_source} /></Link></li>))}</ul>
  );
}

function TechnologyExplorer() {
  const params = useSearchParams();
  const [category, setCategory] = useState("");
  const [selected, setSelected] = useState<string | null>(params.get("technology"));
  const { data, error, isLoading, mutate } = useIntel<TechList>("/technologies", { category });
  const { data: detail, isLoading: detailLoading } = useIntel<TechDetail>(selected ? `/technologies/${selected}` : null);
  const active = data?.items.filter((t) => t.repositories > 0) ?? [];

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Explore" title="Explore Technologies" description="Technology areas across the tracked ecosystem, with the projects leading each one." />
      <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Technology category">
        {[{ key: "", label: "All categories" }, ...(data?.categories ?? [])].map((c) => (
          <button key={c.key} role="radio" aria-checked={category === c.key} onClick={() => setCategory(c.key)}
            className={cn("flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors", category === c.key ? "border-primary/50 bg-primary-soft text-ink" : "border-line text-ink-muted hover:border-line-strong hover:text-ink")}>
            {c.key && <span className="h-1.5 w-1.5 rounded-full" style={{ background: CATEGORY_COLORS[c.key] }} />}{c.label}
          </button>))}
      </div>
      <div className="grid gap-6 xl:grid-cols-[1.2fr_1fr]">
        <Card>
          <CardHeader title="Technology areas" description={data?.note} />
          {isLoading && !data ? <LoadingRows rows={8} /> : error ? <ErrorState message={errorMessage(error)} onRetry={() => mutate()} />
            : !active.length ? <EmptyState title="No classified repositories yet" description="Technologies appear as repositories are tracked and classified." />
            : <ul className="grid gap-px bg-line sm:grid-cols-2">{active.map((tech) => (
              <li key={tech.slug} className="bg-card"><button onClick={() => setSelected(tech.slug)} aria-pressed={selected === tech.slug}
                className={cn("flex w-full flex-col gap-2 px-5 py-4 text-left transition-colors hover:bg-white/[0.03]", selected === tech.slug && "bg-primary-soft")}>
                <span className="flex items-center justify-between gap-2"><span className="flex items-center gap-2 text-sm font-medium text-ink"><span className="h-2 w-2 rounded-full" style={{ background: CATEGORY_COLORS[tech.category] }} />{tech.name}</span>
                  {tech.frontier && <Badge tone="primary" title="Listed as a frontier area in the Signal Atlas taxonomy"><Sparkles className="h-3 w-3" />Frontier</Badge>}</span>
                <span className="flex gap-4 text-xs text-ink-muted"><span><span className="num text-ink">{tech.repositories}</span> repos</span><span><span className="num text-ink">{formatCompact(tech.total_stars)}</span> stars</span>
                  <span><span className="num text-ink">{tech.new_repositories_12m}</span> new in 12m</span></span>
              </button></li>))}</ul>}
        </Card>
        <Card>
          {!selected ? <EmptyState title="Select a technology" description="Choose a technology area to see its leading and newest repositories." />
            : detailLoading && !detail ? <div className="space-y-3 p-5"><Skeleton className="h-6 w-48" /><Skeleton className="h-64 w-full" /></div>
            : detail ? (<>
              <CardHeader title={detail.technology.name} description={detail.technology.category_label} action={<Link href={`/repositories?technology=${detail.technology.slug}`} className="text-xs text-primary-bright hover:underline">All repositories →</Link>} />
              <p className="border-b border-line px-5 py-2 text-2xs font-semibold uppercase tracking-wider text-ink-faint">Leading by stars</p><RepoList repos={detail.top_repositories.slice(0, 8)} />
              <p className="border-y border-line px-5 py-2 text-2xs font-semibold uppercase tracking-wider text-ink-faint">Created in the last 12 months</p><RepoList repos={detail.new_repositories_12m.slice(0, 6)} />
            </>) : <EmptyState title="Technology not found" />}
        </Card>
      </div>
      <Notice>Assignments are inferred by keyword classification of topics, names and descriptions. A repository can belong to several technologies.</Notice>
      <EcosystemCard height={480} />
    </div>
  );
}

export default function TechnologiesPage() {
  return <Suspense><TechnologyExplorer /></Suspense>;
}
