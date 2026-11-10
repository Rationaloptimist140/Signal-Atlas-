"use client";

import { Plus, Swords } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { api, errorMessage } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import { formatCompact, timeAgo } from "@/lib/utils";
import { normaliseRepoFullName, validateRepoFullName, validateRequired } from "@/lib/validation";
import { ProvenanceBadge } from "@/components/intel";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Field, Input, Notice, PageHeader, Skeleton } from "@/components/ui";

type CompetitorSummary = {
  id: number; name: string; description: string | null; website: string | null; repository_count: number; total_stars: number; changes_30d: number;
  latest_change_at: string | null; repositories: { id: number; full_name: string; data_source: "live_github" | "demo_fixture" }[];
};
type List = { items: CompetitorSummary[]; limit: number | null; used: number };

export default function CompetitorsPage() {
  const { canEdit } = useSession();
  const { data, error, isLoading, mutate } = useApi<List>("/competitors");
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState({ name: "", website: "", repo: "" });
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const next = {
      name: validateRequired(values.name, "Name"),
      website: values.website && !/^https?:\/\//i.test(values.website) ? "Start with http:// or https://" : null,
      repo: values.repo ? validateRepoFullName(values.repo) : null,
    };
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;
    setBusy(true);
    setFormError(null);
    try {
      const created = await api<{ id: number }>("/competitors", { method: "POST", body: { name: values.name.trim(), website: values.website.trim() || null } });
      if (values.repo) {
        try {
          await api(`/competitors/${created.id}/repositories`, { method: "POST", body: { full_name: normaliseRepoFullName(values.repo) } });
        } catch (err) {
          setFormError(`Competitor created, but the repository could not be attached: ${errorMessage(err)}`);
          await mutate();
          return;
        }
      }
      setOpen(false);
      setValues({ name: "", website: "", repo: "" });
      await mutate();
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Engine 5" title="Competitor Intelligence" description="Monitor the public repositories of companies and products you compete with: releases, dependency changes, stack changes and growth."
        actions={canEdit && <Button variant="primary" onClick={() => setOpen(true)}><Plus className="h-4 w-4" />Add competitor</Button>} />
      {data && data.limit !== null && <Notice>Monitoring <span className="num text-ink">{data.used}</span> of <span className="num text-ink">{data.limit}</span> competitors included in your plan.</Notice>}
      {error ? <Card><ErrorState message={errorMessage(error)} onRetry={() => mutate()} /></Card>
        : isLoading && !data ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-48 rounded-xl" />)}</div>
        : !data?.items.length ? <Card><EmptyState icon={<Swords className="h-5 w-5" />} title="No competitors monitored yet"
            description="Add a competitor and attach its public GitHub repositories. Signal Atlas will detect new releases, dependency changes and unusual growth."
            action={canEdit && <Button variant="primary" onClick={() => setOpen(true)}><Plus className="h-4 w-4" />Add competitor</Button>} /></Card>
        : <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{data.items.map((c) => (
          <Card key={c.id} className="transition-colors hover:border-primary/40"><Link href={`/competitors/${c.id}`} className="block p-5">
            <div className="flex items-start justify-between gap-3"><h3 className="text-base font-semibold text-ink">{c.name}</h3>{c.changes_30d > 0 && <Badge tone="accent">{c.changes_30d} change{c.changes_30d === 1 ? "" : "s"} / 30d</Badge>}</div>
            {c.description && <p className="mt-1 line-clamp-2 text-xs text-ink-muted">{c.description}</p>}
            <dl className="mt-4 grid grid-cols-3 gap-2 text-xs">
              <div><dt className="text-ink-faint">Repositories</dt><dd className="num mt-0.5 text-sm text-ink">{c.repository_count}</dd></div>
              <div><dt className="text-ink-faint">Total stars</dt><dd className="num mt-0.5 text-sm text-ink">{formatCompact(c.total_stars)}</dd></div>
              <div><dt className="text-ink-faint">Last change</dt><dd className="mt-0.5 text-sm text-ink">{c.latest_change_at ? timeAgo(c.latest_change_at) : "—"}</dd></div>
            </dl>
            <ul className="mt-4 space-y-1 border-t border-line pt-3">{c.repositories.length ? c.repositories.map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-2 text-xs text-ink-muted"><span className="truncate">{r.full_name}</span><ProvenanceBadge source={r.data_source} /></li>))
              : <li className="text-xs text-warning">No repositories attached yet</li>}</ul>
          </Link></Card>))}</div>}

      <Dialog open={open} onOpenChange={setOpen} title="Add competitor" description="Only public repositories are monitored, using read-only GitHub requests.">
        <form onSubmit={submit} className="space-y-4" noValidate>
          {formError && <Notice tone="danger">{formError}</Notice>}
          <Field label="Company or product name" htmlFor="c-name" error={errors.name}><Input id="c-name" value={values.name} onChange={(e) => setValues({ ...values, name: e.target.value })} autoFocus /></Field>
          <Field label="Website (optional)" htmlFor="c-web" error={errors.website}><Input id="c-web" value={values.website} onChange={(e) => setValues({ ...values, website: e.target.value })} placeholder="https://" /></Field>
          <Field label="First repository (optional)" htmlFor="c-repo" error={errors.repo} hint="owner/repository — more can be added later"><Input id="c-repo" value={values.repo} onChange={(e) => setValues({ ...values, repo: e.target.value })} placeholder="supabase/supabase" /></Field>
          <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" variant="primary" loading={busy}>Add competitor</Button></div>
        </form>
      </Dialog>
    </div>
  );
}
