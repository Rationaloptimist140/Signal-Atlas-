"use client";

import { BookMarked, Plus, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { mutate as globalMutate } from "swr";
import { api, errorMessage } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import type { Watchlist } from "@/lib/types";
import { timeAgo } from "@/lib/utils";
import { validateRequired } from "@/lib/validation";
import { ProvenanceBadge } from "@/components/intel";
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, ErrorState, Field, Input, Notice, PageHeader, Skeleton } from "@/components/ui";

type List = { items: Watchlist[]; limit: number | null; used: number };

export default function WatchlistsPage() {
  const { canEdit } = useSession();
  const { data, error, isLoading, mutate } = useApi<List>("/watchlists");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => Promise.all([mutate(), globalMutate((key) => typeof key === "string" && key.startsWith("/watchlists/saved"))]);

  async function create(event: FormEvent) {
    event.preventDefault();
    const invalid = validateRequired(name, "Name");
    if (invalid) return setFormError(invalid);
    setBusy(true);
    setFormError(null);
    try {
      await api("/watchlists", { method: "POST", body: { name: name.trim() } });
      setOpen(false);
      setName("");
      await refresh();
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  async function act(action: () => Promise<unknown>) {
    setMessage(null);
    try {
      await action();
      await refresh();
    } catch (err) {
      setMessage(errorMessage(err));
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Watchlists" description="Saved repositories, opportunities and developers. Watched repositories are kept fully synced and raise notifications when they change."
        actions={canEdit && <Button variant="primary" onClick={() => setOpen(true)}><Plus className="h-4 w-4" />New watchlist</Button>} />
      {data && data.limit !== null && <Notice><span className="num text-ink">{data.used}</span> of <span className="num text-ink">{data.limit}</span> saved items used on your plan.</Notice>}
      {message && <Notice tone="danger">{message}</Notice>}
      {error ? <Card><ErrorState message={errorMessage(error)} onRetry={() => mutate()} /></Card>
        : isLoading && !data ? <Skeleton className="h-64 w-full rounded-xl" />
        : !data?.items.length ? <Card><EmptyState icon={<BookMarked className="h-5 w-5" />} title="No watchlists" description="Create a watchlist, then use Save on any repository, opportunity or developer." /></Card>
        : data.items.map((list) => (
          <Card key={list.id}>
            <CardHeader title={list.name} description={list.description ?? `${list.items.length} saved item${list.items.length === 1 ? "" : "s"}`}
              action={canEdit && <Button variant="ghost" size="sm" onClick={() => { if (window.confirm(`Delete "${list.name}" and its saved items?`)) void act(() => api(`/watchlists/${list.id}`, { method: "DELETE" })); }}><Trash2 className="h-3.5 w-3.5" />Delete</Button>} />
            {list.items.length ? <ul className="divide-y divide-line">{list.items.map((item) => (
              <li key={item.id} className="flex items-center gap-3 px-5 py-3 hover:bg-white/[0.02]">
                <Badge tone={item.item_type === "opportunity" ? "primary" : item.item_type === "developer" ? "warning" : "accent"}>{item.item_type}</Badge>
                <div className="min-w-0 flex-1">
                  {item.link ? <Link href={item.link} className="text-sm font-medium text-ink hover:text-primary-bright">{item.title}</Link> : <span className="text-sm text-ink-faint">{item.title}</span>}
                  {item.subtitle && <p className="truncate text-xs text-ink-muted">{item.subtitle}</p>}
                </div>
                <ProvenanceBadge source={item.data_source} />
                <span className="hidden text-2xs text-ink-faint sm:block">saved {timeAgo(item.created_at)}</span>
                {canEdit && <Button variant="ghost" size="icon" aria-label={`Remove ${item.title}`} onClick={() => act(() => api(`/watchlists/${list.id}/items/${item.id}`, { method: "DELETE" }))}><X className="h-4 w-4" /></Button>}
              </li>))}</ul>
              : <EmptyState title="Nothing saved here yet" description="Use the Save button on a repository, opportunity or developer."
                  action={<div className="flex gap-2"><Link href="/repositories"><Button size="sm">Browse repositories</Button></Link><Link href="/opportunities"><Button size="sm">Browse opportunities</Button></Link></div>} />}
          </Card>))}
      <Dialog open={open} onOpenChange={setOpen} title="New watchlist">
        <form onSubmit={create} className="space-y-4" noValidate>
          <Field label="Name" htmlFor="wl-name" error={formError}><Input id="wl-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. AI infrastructure thesis" autoFocus /></Field>
          <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" variant="primary" loading={busy}>Create watchlist</Button></div>
        </form>
      </Dialog>
    </div>
  );
}
