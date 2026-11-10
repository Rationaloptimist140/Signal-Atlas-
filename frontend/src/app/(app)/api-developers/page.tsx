"use client";

import { Check, Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api, errorMessage } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import { formatDate, formatNumber, timeAgo } from "@/lib/utils";
import { validateRequired } from "@/lib/validation";
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, ErrorState, Field, Input, LoadingRows, Notice, PageHeader, ProgressBar, Select, Td, Th } from "@/components/ui";

type Keys = {
  items: { id: number; name: string; prefix: string; scopes: string; created_at: string; last_used_at: string | null; revoked: boolean }[];
  limit: number | null; api_access: boolean; requests_this_month: number; requests_limit: number | null; rate_per_minute: number;
};

const ENDPOINTS = [
  ["GET", "/api/v1/dashboard", "Intelligence summary"], ["GET", "/api/v1/repositories", "Search and filter tracked repositories"], ["GET", "/api/v1/repositories/{id}", "Repository profile, score and provenance"],
  ["GET", "/api/v1/developers", "Developers contributing to tracked repositories"], ["GET", "/api/v1/developers/{id}", "Developer profile (public data and labelled inferences)"],
  ["GET", "/api/v1/trends", "Emerging signals by daily, weekly or monthly window"], ["GET", "/api/v1/opportunities", "Ranked opportunity hypotheses"], ["GET", "/api/v1/opportunities/{id}", "Opportunity analysis with evidence and risks"],
  ["POST", "/api/v1/reports/generate", "Generate an intelligence report (write scope)"], ["GET", "/api/v1/competitors", "Competitors monitored by your organisation"], ["POST", "/api/v1/watchlists", "Create a watchlist (write scope)"],
];

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button size="sm" onClick={async () => { await navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
      {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}{copied ? "Copied" : "Copy"}
    </Button>
  );
}

export default function ApiDevelopersPage() {
  const { isAdmin, me } = useSession();
  const { data, error, isLoading, mutate } = useApi<Keys>("/api-keys");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState("read");
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<{ key: string; name: string } | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const origin = typeof window !== "undefined" ? window.location.origin : "https://your-signal-atlas-host";

  async function create(event: FormEvent) {
    event.preventDefault();
    const invalid = validateRequired(name, "Name");
    if (invalid) return setFormError(invalid);
    setBusy(true);
    setFormError(null);
    try {
      const result = await api<{ key: string; name: string }>("/api-keys", { method: "POST", body: { name: name.trim(), scopes } });
      setCreated(result);
      setOpen(false);
      setName("");
      await mutate();
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  async function revoke(id: number, label: string) {
    if (!window.confirm(`Revoke "${label}"? Applications using it will stop working immediately.`)) return;
    try {
      await api(`/api-keys/${id}`, { method: "DELETE" });
      await mutate();
    } catch (err) {
      setMessage(errorMessage(err));
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="API & Developers" description="Programmatic access to Signal Atlas intelligence. Versioned REST API with OpenAPI documentation."
        actions={<><a href="/api/docs" target="_blank" rel="noopener noreferrer"><Button>OpenAPI docs</Button></a>{isAdmin && <Button variant="primary" onClick={() => setOpen(true)}><Plus className="h-4 w-4" />Create API key</Button>}</>} />
      {message && <Notice tone="danger">{message}</Notice>}
      {data && !data.api_access && <Notice tone="warning" title="API access is not included in the Free plan.">Keys can be created from the Pro plan upwards. You can explore the API documentation now.</Notice>}
      {created && (
        <Card className="border-success/40 p-5">
          <p className="text-sm font-semibold text-ink">API key “{created.name}” created</p>
          <p className="mt-1 text-xs text-warning">Copy it now. Only a hash is stored, so it cannot be shown again.</p>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center"><code className="num flex-1 overflow-x-auto rounded-lg border border-line bg-bg px-3 py-2 text-xs text-accent">{created.key}</code><CopyButton value={created.key} /><Button size="sm" variant="ghost" onClick={() => setCreated(null)}>Done</Button></div>
        </Card>
      )}

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader title="API keys" description={data?.limit !== null && data?.limit !== undefined ? `${data.items.filter((k) => !k.revoked).length} of ${data.limit} active keys` : "Keys authenticate as your organisation"} />
          {isLoading && !data ? <LoadingRows rows={3} /> : error ? <ErrorState message={errorMessage(error)} onRetry={() => mutate()} />
            : !data?.items.length ? <EmptyState icon={<KeyRound className="h-5 w-5" />} title="No API keys yet" description={isAdmin ? "Create a key to call the API from scripts and applications." : "Ask a workspace admin to create a key."} />
            : <div className="overflow-x-auto"><table className="w-full"><thead className="bg-surface/60"><tr><Th>Name</Th><Th>Key</Th><Th>Scope</Th><Th>Last used</Th><Th>Created</Th><Th /></tr></thead>
              <tbody className="divide-y divide-line">{data.items.map((key) => (
                <tr key={key.id} className={key.revoked ? "opacity-50" : ""}><Td className="text-ink">{key.name}</Td><Td className="num text-xs text-ink-muted">{key.prefix}_••••</Td>
                  <Td><Badge tone={key.scopes.includes("write") ? "warning" : "neutral"}>{key.scopes}</Badge></Td><Td className="text-xs text-ink-muted">{key.last_used_at ? timeAgo(key.last_used_at) : "never"}</Td>
                  <Td className="text-xs text-ink-muted">{formatDate(key.created_at)}</Td>
                  <Td className="text-right">{key.revoked ? <Badge tone="danger">Revoked</Badge> : isAdmin && <Button variant="ghost" size="icon" onClick={() => revoke(key.id, key.name)} aria-label={`Revoke ${key.name}`}><Trash2 className="h-4 w-4" /></Button>}</Td></tr>))}</tbody></table></div>}
        </Card>
        <Card>
          <CardHeader title="Usage this month" description={`${me?.plan.name ?? ""} plan`} />
          <div className="space-y-4 p-5">
            <div><div className="mb-1.5 flex justify-between text-xs"><span className="text-ink-muted">API requests</span><span className="num text-ink">{formatNumber(data?.requests_this_month)} / {data?.requests_limit === null ? "unlimited" : formatNumber(data?.requests_limit)}</span></div>
              <ProgressBar value={data?.requests_this_month ?? 0} max={data?.requests_limit || 1} tone="accent" /></div>
            <dl className="grid grid-cols-2 gap-4 text-sm"><div><dt className="text-xs text-ink-faint">Rate limit</dt><dd className="num mt-0.5 text-ink">{data?.rate_per_minute ? `${data.rate_per_minute} / minute` : "—"}</dd></div>
              <div><dt className="text-xs text-ink-faint">Metering</dt><dd className="mt-0.5 text-ink">Per accepted request</dd></div></dl>
            <Notice>Requests over the limit receive HTTP 429 with a Retry-After header; over the monthly quota, HTTP 402 with an upgrade payload.</Notice>
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader title="Quick start" description="Authenticate with the X-API-Key header (or Authorization: Bearer)" />
        <div className="space-y-4 p-5">
          <pre className="num overflow-x-auto rounded-lg border border-line bg-bg p-4 text-xs leading-relaxed text-ink-muted"><code>{`curl "${origin}/api/v1/opportunities?min_score=65&source=live" \\\n  -H "X-API-Key: sa_live_your_key"`}</code></pre>
          <p className="text-xs text-ink-muted">Every intelligence object carries <code className="num text-accent">data_source</code> (<code className="num">live_github</code> or <code className="num">demo_fixture</code>). Use <code className="num text-accent">source=live</code> to exclude demonstration fixtures.</p>
          <div className="overflow-x-auto"><table className="w-full"><thead className="bg-surface/60"><tr><Th>Method</Th><Th>Endpoint</Th><Th>Description</Th></tr></thead>
            <tbody className="divide-y divide-line">{ENDPOINTS.map(([method, path, description]) => (
              <tr key={method + path}><Td><Badge tone={method === "GET" ? "success" : "warning"}>{method}</Badge></Td><Td className="num text-xs text-ink">{path}</Td><Td className="text-xs text-ink-muted">{description}</Td></tr>))}</tbody></table></div>
        </div>
      </Card>

      <Dialog open={open} onOpenChange={setOpen} title="Create API key" description="The key is shown once. Store it in a secret manager, never in source code.">
        <form onSubmit={create} className="space-y-4" noValidate>
          <Field label="Name" htmlFor="key-name" error={formError}><Input id="key-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Research notebook" autoFocus /></Field>
          <Field label="Scope" htmlFor="key-scope" hint="Read-only keys cannot generate reports or change watchlists."><Select id="key-scope" value={scopes} onChange={(e) => setScopes(e.target.value)}><option value="read">Read only</option><option value="read write">Read and write</option></Select></Field>
          <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" variant="primary" loading={busy}>Create key</Button></div>
        </form>
      </Dialog>
    </div>
  );
}
