"use client";

import { Github, Plus, Search, Star } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useSWRConfig } from "swr";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useIntel, useSession } from "@/lib/session";
import type { Page, Repository } from "@/lib/types";
import { categoryLabel, formatCompact, timeAgo } from "@/lib/utils";
import { normaliseRepoFullName, validateRepoFullName } from "@/lib/validation";
import { ProvenanceBadge, SaveButton, ScoreRing } from "@/components/intel";
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, ErrorState, Field, Input, LoadingRows, Notice, PageHeader, Pagination, Select, Td, Th } from "@/components/ui";

type Facets = { categories: { value: string; label: string; count: number }[]; languages: { value: string; count: number }[]; licenses: { value: string; count: number }[] };
type LiveResult = { items: Repository[]; total_on_github: number; fetched_at: string; authenticated_request: boolean };

function LiveGitHubSearch({ initial }: { initial: string }) {
  const { canEdit } = useSession();
  const { mutate } = useSWRConfig();
  const [query, setQuery] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<LiveResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(event?: FormEvent) {
    event?.preventDefault();
    if (query.trim().length < 2) return setError("Enter at least two characters.");
    setBusy(true);
    setError(null);
    try {
      setResult(await api<LiveResult>("/repositories/github-search", { params: { q: query.trim(), per_page: 20 } }));
      await mutate(() => true);
    } catch (err) {
      setResult(null);
      setError(err instanceof ApiError && err.detail.retry_at ? `${err.message} Limit resets ${timeAgo(err.detail.retry_at).replace(" ago", "")} from now.` : errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!canEdit) return null;
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><Github className="h-4 w-4" />Search public GitHub live</span>}
        description="Runs one read-only request against the GitHub Search API and adds the results to your tracked set. Supports GitHub qualifiers such as topic:llm stars:>500." />
      <form onSubmit={run} className="flex flex-col gap-2 p-5 sm:flex-row">
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. vector database language:rust stars:>1000" aria-label="GitHub search query" />
        <Button type="submit" variant="primary" loading={busy}><Search className="h-4 w-4" />Search GitHub</Button>
      </form>
      {error && <div className="px-5 pb-5"><Notice tone="danger">{error}</Notice></div>}
      {result && (
        <div className="border-t border-line">
          <p className="px-5 py-3 text-xs text-ink-muted">
            Stored <span className="num text-ink">{result.items.length}</span> of <span className="num text-ink">{result.total_on_github.toLocaleString("en-GB")}</span> matches on GitHub ·
            fetched {timeAgo(result.fetched_at)} · {result.authenticated_request ? "authenticated request" : "anonymous request (60 requests/hour limit)"}
          </p>
          <ul className="grid gap-px border-t border-line bg-line sm:grid-cols-2">
            {result.items.slice(0, 10).map((repo) => (
              <li key={repo.id} className="bg-card">
                <Link href={`/repositories/${repo.id}`} className="flex items-center justify-between gap-3 px-5 py-2.5 hover:bg-white/[0.03]">
                  <span className="truncate text-sm text-ink">{repo.full_name}</span>
                  <span className="num flex shrink-0 items-center gap-1 text-xs text-ink-muted"><Star className="h-3 w-3" />{formatCompact(repo.stars)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

function TrackDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    const invalid = validateRepoFullName(name);
    if (invalid) return setError(invalid);
    setBusy(true);
    setError(null);
    try {
      const repo = await api<Repository>("/repositories/track", { method: "POST", body: { full_name: normaliseRepoFullName(name) } });
      onOpenChange(false);
      router.push(`/repositories/${repo.id}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Track a repository" description="Fetches public metadata from GitHub and queues a full sync.">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Field label="Repository" htmlFor="track-name" error={error} hint="owner/repository or a github.com URL">
          <Input id="track-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="vercel/next.js" autoFocus />
        </Field>
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button><Button type="submit" variant="primary" loading={busy}>Track repository</Button></div>
      </form>
    </Dialog>
  );
}

function RepositoryExplorer() {
  const params = useSearchParams();
  const { canEdit } = useSession();
  const [filters, setFilters] = useState({ q: params.get("q") ?? "", category: params.get("category") ?? "", technology: params.get("technology") ?? "", language: "", license: "", activity: "", min_stars: "", min_contributors: "", sort: "stars" });
  const [page, setPage] = useState(1);
  const [trackOpen, setTrackOpen] = useState(false);
  const github = params.get("github");
  const [showLive, setShowLive] = useState(github !== null);
  const set = (key: keyof typeof filters) => (event: { target: { value: string } }) => { setFilters((f) => ({ ...f, [key]: event.target.value })); setPage(1); };

  useEffect(() => { const q = params.get("q"); if (q !== null) setFilters((f) => ({ ...f, q })); }, [params]);

  const { data: facets } = useIntel<Facets>("/repositories/facets");
  const { data, error, isLoading, mutate } = useIntel<Page<Repository>>("/repositories", { ...filters, page, page_size: 25 });
  const active = Object.entries(filters).filter(([key, value]) => key !== "sort" && value).length;

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Engine 1" title="Repository Intelligence" description="Search, filter and compare tracked public repositories. Every figure links back to GitHub."
        actions={canEdit && <><Button onClick={() => setShowLive((v) => !v)}><Github className="h-4 w-4" />{showLive ? "Hide" : "Search"} GitHub</Button><Button variant="primary" onClick={() => setTrackOpen(true)}><Plus className="h-4 w-4" />Track repository</Button></>} />
      {showLive && <LiveGitHubSearch initial={github && github !== "1" ? github : ""} />}

      <Card>
        <div className="grid gap-2 border-b border-line p-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
          <div className="relative sm:col-span-2">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
            <Input value={filters.q} onChange={set("q")} placeholder="Filter by name or description" className="pl-9" aria-label="Filter repositories" />
          </div>
          <Select value={filters.category} onChange={set("category")} aria-label="Technology category"><option value="">All categories</option>{facets?.categories.map((c) => <option key={c.value} value={c.value}>{c.label} ({c.count})</option>)}</Select>
          <Select value={filters.language} onChange={set("language")} aria-label="Programming language"><option value="">All languages</option>{facets?.languages.map((l) => <option key={l.value} value={l.value}>{l.value} ({l.count})</option>)}</Select>
          <Select value={filters.license} onChange={set("license")} aria-label="Licence type"><option value="">Any licence</option><option value="none">No licence detected</option>{facets?.licenses.map((l) => <option key={l.value} value={l.value}>{l.value} ({l.count})</option>)}</Select>
          <Select value={filters.activity} onChange={set("activity")} aria-label="Repository activity"><option value="">Any activity</option><option value="active_7d">Pushed in 7 days</option><option value="active_30d">Pushed in 30 days</option><option value="active_90d">Pushed in 90 days</option><option value="stale">Stale (180+ days)</option></Select>
          <Select value={filters.min_contributors} onChange={set("min_contributors")} aria-label="Contributor count"><option value="">Any contributors</option><option value="10">10+ contributors</option><option value="50">50+ contributors</option><option value="200">200+ contributors</option></Select>
          <Select value={filters.sort} onChange={set("sort")} aria-label="Sort by"><option value="stars">Sort: stars</option><option value="score">Sort: score</option><option value="recently_pushed">Sort: recently pushed</option><option value="newest">Sort: newest</option><option value="forks">Sort: forks</option><option value="contributors">Sort: contributors</option><option value="name">Sort: name</option></Select>
        </div>
        <div className="flex items-center justify-between px-5 py-2.5 text-xs text-ink-muted">
          <span><span className="num text-ink">{data ? data.total.toLocaleString("en-GB") : "—"}</span> repositories{filters.technology && <> · technology <Badge tone="accent">{filters.technology}</Badge></>}</span>
          {active > 0 && <button className="text-primary-bright hover:underline" onClick={() => { setFilters({ q: "", category: "", technology: "", language: "", license: "", activity: "", min_stars: "", min_contributors: "", sort: filters.sort }); setPage(1); }}>Clear {active} filter{active === 1 ? "" : "s"}</button>}
        </div>
        {isLoading && !data ? <LoadingRows rows={8} /> : error ? <ErrorState message={errorMessage(error)} onRetry={() => mutate()} />
          : !data?.items.length ? (
            <EmptyState title="No repositories match" description={active ? "Try removing a filter, or search GitHub live to add repositories." : "Nothing is tracked yet. Search GitHub live to pull in verified public data."}
              action={canEdit && <Button variant="primary" onClick={() => setShowLive(true)}><Github className="h-4 w-4" />Search GitHub</Button>} />
          ) : (
            <div className="overflow-x-auto scrollbar-thin">
              <table className="w-full min-w-[980px] border-t border-line">
                <thead className="bg-surface/60"><tr><Th>Repository</Th><Th>Category</Th><Th>Language</Th><Th>Licence</Th><Th className="text-right">Stars</Th><Th className="text-right">Contributors</Th><Th>Last push</Th><Th className="text-center">Score</Th><Th /></tr></thead>
                <tbody className="divide-y divide-line">
                  {data.items.map((repo) => (
                    <tr key={repo.id} className="hover:bg-white/[0.02]">
                      <Td className="max-w-[340px]">
                        <Link href={`/repositories/${repo.id}`} className="font-medium text-ink hover:text-primary-bright">{repo.full_name}</Link>
                        <span className="ml-2 inline-flex gap-1 align-middle"><ProvenanceBadge source={repo.data_source} />{repo.archived && <Badge tone="danger">Archived</Badge>}{repo.is_fork && <Badge>Fork</Badge>}</span>
                        <p className="mt-0.5 truncate text-xs text-ink-muted">{repo.description ?? "No description"}</p>
                      </Td>
                      <Td className="whitespace-nowrap text-xs text-ink-muted">{categoryLabel(repo.category)}</Td>
                      <Td className="whitespace-nowrap text-xs text-ink-muted">{repo.primary_language ?? "—"}</Td>
                      <Td className="whitespace-nowrap text-xs">{repo.license_spdx ? <span className="text-ink-muted">{repo.license_spdx}</span> : <span className="text-warning">None</span>}</Td>
                      <Td className="num text-right">{formatCompact(repo.stars)}</Td>
                      <Td className="num text-right text-ink-muted" >{repo.contributors_count === null ? <span title="Available after a full sync">—</span> : formatCompact(repo.contributors_count)}</Td>
                      <Td className="whitespace-nowrap text-xs text-ink-muted">{timeAgo(repo.pushed_at_github)}</Td>
                      <Td><div className="flex justify-center"><ScoreRing score={repo.score} size={36} /></div></Td>
                      <Td className="text-right"><SaveButton itemType="repository" itemId={repo.id} /></Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        {data && <Pagination page={page} pageSize={25} total={data.total} onChange={setPage} />}
      </Card>
      <TrackDialog open={trackOpen} onOpenChange={setTrackOpen} />
    </div>
  );
}

export default function RepositoriesPage() {
  return <Suspense><RepositoryExplorer /></Suspense>;
}
