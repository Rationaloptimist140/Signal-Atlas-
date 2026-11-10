"use client";

import { CheckCircle2, CircleDashed, FlaskConical, Github, RefreshCw } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useSWRConfig } from "swr";
import { api, errorMessage } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import { cn, formatDate, formatNumber, timeAgo } from "@/lib/utils";
import { validatePassword, validateRequired, validateWeights } from "@/lib/validation";
import { BillingTab } from "@/components/billing-tab";
import { Badge, Button, Card, CardHeader, ErrorState, Field, Input, LoadingRows, Notice, PageHeader, Tabs, Td, Th } from "@/components/ui";

type TabKey = "profile" | "integrations" | "scoring" | "billing" | "workspace" | "data";
type Feedback = { tone: "success" | "danger" | "accent" | "warning"; text: string } | null;
type OrgData = { organisation: { name: string; slug: string; created_at: string }; members: { id: number; email: string; full_name: string; role: string }[];
  integrations: { key: string; name: string; configured: boolean; detail: string; env: string[] }[] };
type Scoring = { weights: Record<string, number>; defaults: Record<string, number>; labels: Record<string, string>; custom: boolean; editable: boolean };
type SystemStatus = { jobs: Record<string, number>; live_repositories: number; demo_repositories: number; jobs_inline: boolean; recent_jobs: { id: number; job_type: string; status: string; attempts: number; finished_at: string | null; last_error: string | null }[] };

const GITHUB_MESSAGES: Record<string, Feedback> = {
  connected: { tone: "success", text: "GitHub account connected with read-only identity scopes." },
  already_linked: { tone: "danger", text: "That GitHub account is already linked to another Signal Atlas user." },
};

function ProfileTab() {
  const { me, refresh } = useSession();
  const [name, setName] = useState(me?.user.full_name ?? "");
  const [title, setTitle] = useState(me?.user.job_title ?? "");
  const [passwords, setPasswords] = useState({ current: "", next: "" });
  const [profileMsg, setProfileMsg] = useState<Feedback>(null);
  const [passwordMsg, setPasswordMsg] = useState<Feedback>(null);
  const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => { setName(me?.user.full_name ?? ""); setTitle(me?.user.job_title ?? ""); }, [me]);

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    const invalid = validateRequired(name, "Name");
    if (invalid) return setProfileMsg({ tone: "danger", text: invalid });
    setBusy("profile");
    try {
      await api("/auth/me", { method: "PATCH", body: { full_name: name.trim(), job_title: title.trim() } });
      await refresh();
      setProfileMsg({ tone: "success", text: "Profile updated." });
    } catch (err) {
      setProfileMsg({ tone: "danger", text: errorMessage(err) });
    } finally {
      setBusy(null);
    }
  }
  async function changePassword(event: FormEvent) {
    event.preventDefault();
    const invalid = validatePassword(passwords.next);
    if (invalid) return setPasswordMsg({ tone: "danger", text: invalid });
    setBusy("password");
    try {
      await api("/auth/change-password", { method: "POST", body: { current_password: passwords.current || "-", new_password: passwords.next } });
      setPasswords({ current: "", next: "" });
      setPasswordMsg({ tone: "success", text: "Password changed. Other sessions were signed out." });
    } catch (err) {
      setPasswordMsg({ tone: "danger", text: errorMessage(err) });
    } finally {
      setBusy(null);
    }
  }
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card><CardHeader title="Profile" description={me?.user.email} />
        <form onSubmit={saveProfile} className="space-y-4 p-5" noValidate>
          {profileMsg && <Notice tone={profileMsg.tone}>{profileMsg.text}</Notice>}
          <Field label="Full name" htmlFor="p-name"><Input id="p-name" value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Job title" htmlFor="p-title"><Input id="p-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Founder, Analyst" /></Field>
          <Button type="submit" variant="primary" loading={busy === "profile"}>Save profile</Button>
        </form></Card>
      <Card><CardHeader title="Password" description="Changing your password signs out all other sessions" />
        <form onSubmit={changePassword} className="space-y-4 p-5" noValidate>
          {passwordMsg && <Notice tone={passwordMsg.tone}>{passwordMsg.text}</Notice>}
          {me?.user.has_password && <Field label="Current password" htmlFor="p-current"><Input id="p-current" type="password" autoComplete="current-password" value={passwords.current} onChange={(e) => setPasswords({ ...passwords, current: e.target.value })} /></Field>}
          <Field label="New password" htmlFor="p-next" hint="At least 10 characters, with an upper-case letter and a digit."><Input id="p-next" type="password" autoComplete="new-password" value={passwords.next} onChange={(e) => setPasswords({ ...passwords, next: e.target.value })} /></Field>
          <Button type="submit" loading={busy === "password"}>{me?.user.has_password ? "Change password" : "Set password"}</Button>
        </form></Card>
    </div>
  );
}

function IntegrationsTab({ githubParam }: { githubParam: string | null }) {
  const { me, refresh } = useSession();
  const { data, error, isLoading, mutate } = useApi<OrgData>("/settings/organisation");
  const [msg, setMsg] = useState<Feedback>(githubParam ? GITHUB_MESSAGES[githubParam] ?? null : null);
  const [busy, setBusy] = useState(false);
  const github = me?.github;

  async function disconnect() {
    if (!window.confirm("Disconnect GitHub? The stored token will be deleted and the grant revoked.")) return;
    setBusy(true);
    try {
      await api("/auth/github", { method: "DELETE" });
      await refresh();
      setMsg({ tone: "success", text: "GitHub disconnected and the stored token deleted." });
    } catch (err) {
      setMsg({ tone: "danger", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-6">
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
      <Card><CardHeader title={<span className="flex items-center gap-2"><Github className="h-4 w-4" />Your GitHub account</span>} description="Used for sign-in and to run read-only requests on your own API quota" />
        <div className="space-y-4 p-5">
          {github?.connected ? (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">{github.avatar_url && <img src={github.avatar_url} alt="" width={36} height={36} className="h-9 w-9 rounded-full border border-line" referrerPolicy="no-referrer" />}
                <div><p className="text-sm font-medium text-ink">{github.login} <Badge tone="success" className="ml-1">Connected</Badge></p><p className="num text-xs text-ink-faint">Scopes granted: {github.scopes || "none (public data only)"}</p></div></div>
              <Button variant="danger" onClick={disconnect} loading={busy}>Disconnect</Button>
            </div>
          ) : github?.oauth_configured ? (
            <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-sm text-ink-muted">Not connected.</p>
              <a href="/api/v1/auth/github/start?mode=connect"><Button variant="primary"><Github className="h-4 w-4" />Connect GitHub</Button></a></div>
          ) : <Notice tone="warning" title="Setup required.">GitHub OAuth is not configured on this instance. An administrator must set <code className="num">GITHUB_OAUTH_CLIENT_ID</code> and <code className="num">GITHUB_OAUTH_CLIENT_SECRET</code> on the API service (see DEPLOYMENT.md).</Notice>}
          <Notice>Signal Atlas requests identity scopes only and never repository write access. The token is encrypted at rest, used only server-side, and never sent to your browser.</Notice>
        </div></Card>
      <Card><CardHeader title="Instance integrations" description="Configured through environment variables on the API service" />
        {isLoading && !data ? <LoadingRows rows={4} /> : error ? <ErrorState message={errorMessage(error)} onRetry={() => mutate()} />
          : <ul className="divide-y divide-line">{data?.integrations.map((item) => (
            <li key={item.key} className="flex items-start gap-3 px-5 py-4">{item.configured ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" /> : <CircleDashed className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />}
              <div className="min-w-0 flex-1"><p className="text-sm text-ink">{item.name} <Badge tone={item.configured ? "success" : "neutral"} className="ml-1">{item.configured ? "Configured" : "Not configured"}</Badge></p>
                <p className="mt-1 text-xs leading-relaxed text-ink-muted">{item.detail}</p>{item.env.length > 0 && <p className="num mt-1 text-2xs text-ink-faint">{item.env.join(" · ")}</p>}</div></li>))}</ul>}
      </Card>
    </div>
  );
}

function ScoringTab() {
  const { isAdmin } = useSession();
  const { mutate: mutateAll } = useSWRConfig();
  const { data, error, isLoading, mutate } = useApi<Scoring>("/settings/scoring");
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [msg, setMsg] = useState<Feedback>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data) setWeights(data.weights); }, [data]);
  if (isLoading && !data) return <Card><LoadingRows rows={7} /></Card>;
  if (error || !data) return <Card><ErrorState message={error ? errorMessage(error) : "Unavailable"} onRetry={() => mutate()} /></Card>;
  const total = Object.values(weights).reduce((sum, v) => sum + (Number.isFinite(v) ? v : 0), 0);
  const editable = data.editable && isAdmin;

  async function save(reset = false) {
    const invalid = reset ? null : validateWeights(weights);
    if (invalid) return setMsg({ tone: "danger", text: invalid });
    setBusy(true);
    try {
      if (reset) await api("/settings/scoring", { method: "DELETE" });
      else await api("/settings/scoring", { method: "PUT", body: { weights } });
      await mutate();
      await mutateAll((key) => typeof key === "string" && !key.startsWith("/settings"));
      setMsg({ tone: "success", text: reset ? "Weights reset to the defaults." : "Weights saved. Scores across the terminal now use your weighting." });
    } catch (err) {
      setMsg({ tone: "danger", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card><CardHeader title="Business potential scoring weights" description="Metric scores never change; weights only change how they combine into the 0–100 total for your organisation." action={data.custom && <Badge tone="primary">Custom</Badge>} />
      <div className="space-y-4 p-5">
        {!data.editable && <Notice tone="warning" title="Business plan feature.">Custom weights are available from the Business plan. The default weights below are in use.</Notice>}
        {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
        <ul className="space-y-3">{Object.keys(data.defaults).map((key) => (
          <li key={key} className="grid grid-cols-[1fr_auto] items-center gap-4 sm:grid-cols-[220px_1fr_88px]">
            <label htmlFor={`w-${key}`} className="text-sm text-ink">{data.labels[key]}<span className="num ml-2 text-2xs text-ink-faint">default {data.defaults[key]}%</span></label>
            <input type="range" min={0} max={100} step={1} value={weights[key] ?? 0} disabled={!editable} onChange={(e) => setWeights({ ...weights, [key]: Number(e.target.value) })}
              className="hidden accent-primary sm:block" aria-label={`${data.labels[key]} weight slider`} />
            <Input id={`w-${key}`} type="number" min={0} max={100} value={Number.isFinite(weights[key]) ? weights[key] : ""} disabled={!editable} onChange={(e) => setWeights({ ...weights, [key]: e.target.value === "" ? NaN : Number(e.target.value) })} className="num text-right" />
          </li>))}</ul>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          <p className={cn("num text-sm", Math.abs(total - 100) < 0.01 ? "text-success" : "text-danger")}>Total {total}% {Math.abs(total - 100) < 0.01 ? "✓" : "(must equal 100)"}</p>
          {editable && <div className="flex gap-2"><Button onClick={() => save(true)} disabled={busy || !data.custom}>Reset to defaults</Button><Button variant="primary" onClick={() => save()} loading={busy}>Save weights</Button></div>}
        </div>
      </div></Card>
  );
}

function WorkspaceTab() {
  const { isAdmin } = useSession();
  const { data, error, isLoading, mutate } = useApi<OrgData>("/settings/organisation");
  const { data: audit } = useApi<{ items: { id: number; action: string; target_type: string | null; created_at: string }[] }>(isAdmin ? "/settings/audit-log" : null);
  const [name, setName] = useState("");
  const [msg, setMsg] = useState<Feedback>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data) setName(data.organisation.name); }, [data]);
  async function save(event: FormEvent) {
    event.preventDefault();
    const invalid = validateRequired(name, "Workspace name");
    if (invalid) return setMsg({ tone: "danger", text: invalid });
    setBusy(true);
    try {
      await api("/settings/organisation", { method: "PATCH", body: { name: name.trim() } });
      await mutate();
      setMsg({ tone: "success", text: "Workspace renamed." });
    } catch (err) {
      setMsg({ tone: "danger", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }
  if (isLoading && !data) return <Card><LoadingRows /></Card>;
  if (error || !data) return <Card><ErrorState message={error ? errorMessage(error) : "Unavailable"} onRetry={() => mutate()} /></Card>;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="space-y-6">
        <Card><CardHeader title="Workspace" description={`Created ${formatDate(data.organisation.created_at)}`} />
          <form onSubmit={save} className="space-y-4 p-5" noValidate>{msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
            <Field label="Workspace name" htmlFor="org-name"><Input id="org-name" value={name} onChange={(e) => setName(e.target.value)} disabled={!isAdmin} /></Field>
            {isAdmin && <Button type="submit" variant="primary" loading={busy}>Save</Button>}</form></Card>
        <Card><CardHeader title="Members" description="Roles: owner, admin, analyst (can edit), viewer (read-only)" />
          <table className="w-full"><thead className="bg-surface/60"><tr><Th>Member</Th><Th>Role</Th></tr></thead><tbody className="divide-y divide-line">{data.members.map((m) => (
            <tr key={m.id}><Td><span className="text-ink">{m.full_name}</span><span className="block text-xs text-ink-faint">{m.email}</span></Td><Td><Badge tone={m.role === "owner" ? "primary" : "neutral"}>{m.role}</Badge></Td></tr>))}</tbody></table>
          <div className="p-5"><Notice>Inviting teammates needs an email provider and is on the roadmap (see TASKS.md).</Notice></div></Card>
      </div>
      <Card><CardHeader title="Audit log" description="Security-relevant events in this workspace" />
        {!isAdmin ? <p className="p-5 text-sm text-ink-muted">Visible to workspace admins.</p>
          : <ul className="max-h-[520px] divide-y divide-line overflow-y-auto scrollbar-thin">{audit?.items.map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-3 px-5 py-2.5 text-xs"><span className="num text-ink">{a.action}</span><span className="text-ink-faint">{timeAgo(a.created_at)}</span></li>))}</ul>}</Card>
    </div>
  );
}

function DataTab() {
  const { isAdmin } = useSession();
  const { mutate: mutateAll } = useSWRConfig();
  const { data, error, mutate } = useApi<SystemStatus>(isAdmin ? "/system/status" : null, undefined, { shouldRetryOnError: false });
  const [msg, setMsg] = useState<Feedback>(null);
  const [busy, setBusy] = useState<string | null>(null);
  async function run(key: string, path: string, method: string, success: string) {
    setBusy(key);
    setMsg(null);
    try {
      const result = await api<{ message?: string }>(path, { method });
      await mutateAll(() => true);
      setMsg({ tone: "success", text: result?.message ?? success });
    } catch (err) {
      setMsg({ tone: "danger", text: errorMessage(err) });
    } finally {
      setBusy(null);
    }
  }
  if (!isAdmin) return <Card><p className="p-5 text-sm text-ink-muted">Data tools are available to workspace admins.</p></Card>;
  if (error) return <Card><ErrorState message={errorMessage(error)} onRetry={() => mutate()} /></Card>;
  return (
    <div className="space-y-6">
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card><CardHeader title="Live GitHub data" description={`${formatNumber(data?.live_repositories)} live repositories stored`} />
          <div className="space-y-3 p-5"><p className="text-sm text-ink-muted">Runs the curated discovery queries against the public GitHub Search API, spaced to respect rate limits, then recomputes scores and signals.</p>
            <div className="flex flex-wrap gap-2"><Button variant="primary" onClick={() => run("discover", "/system/discover", "POST", "Discovery queued.")} loading={busy === "discover"}><Github className="h-4 w-4" />Run discovery</Button>
              <Button onClick={() => run("recompute", "/system/recompute", "POST", "Recompute queued.")} loading={busy === "recompute"}><RefreshCw className="h-4 w-4" />Recompute intelligence</Button></div>
            {data && !data.jobs_inline && <Notice>Queued jobs are processed by the background worker (<code className="num">python -m app.worker</code>).</Notice>}</div></Card>
        <Card><CardHeader title="Demonstration fixtures" description={`${formatNumber(data?.demo_repositories)} fictional repositories loaded`} />
          <div className="space-y-3 p-5"><p className="text-sm text-ink-muted">Fictional projects and developers for exploring the product. Always labelled as demo data and never mixed into live rankings.</p>
            <div className="flex flex-wrap gap-2"><Button onClick={() => run("load", "/system/demo/load", "POST", "Demo fixtures loaded.")} loading={busy === "load"}><FlaskConical className="h-4 w-4" />Load demo fixtures</Button>
              <Button variant="danger" onClick={() => run("clear", "/system/demo", "DELETE", "Demo fixtures removed.")} loading={busy === "clear"} disabled={!data?.demo_repositories}>Remove demo fixtures</Button></div></div></Card>
      </div>
      <Card><CardHeader title="Background jobs" description={data ? `${data.jobs.queued} queued · ${data.jobs.running} running · ${data.jobs.succeeded} succeeded · ${data.jobs.failed} failed` : undefined} />
        {data?.recent_jobs.length ? <div className="overflow-x-auto"><table className="w-full"><thead className="bg-surface/60"><tr><Th>Job</Th><Th>Status</Th><Th>Attempts</Th><Th>Finished</Th><Th>Note</Th></tr></thead>
          <tbody className="divide-y divide-line">{data.recent_jobs.map((job) => (
            <tr key={job.id}><Td className="num text-xs text-ink">{job.job_type}</Td><Td><Badge tone={job.status === "succeeded" ? "success" : job.status === "failed" ? "danger" : "accent"}>{job.status}</Badge></Td>
              <Td className="num text-xs text-ink-muted">{job.attempts}</Td><Td className="text-xs text-ink-muted">{job.finished_at ? timeAgo(job.finished_at) : "—"}</Td><Td className="max-w-xs truncate text-xs text-ink-faint">{job.last_error ?? ""}</Td></tr>))}</tbody></table></div>
          : <p className="p-5 text-sm text-ink-muted">No jobs have run yet.</p>}</Card>
    </div>
  );
}

function SettingsContent() {
  const params = useSearchParams();
  const githubParam = params.get("github");
  const initial = (params.get("tab") as TabKey | null) ?? (githubParam ? "integrations" : "profile");
  const [tab, setTab] = useState<TabKey>(initial);
  return (
    <div className="space-y-6">
      <PageHeader title="Settings" description="Profile, integrations, scoring methodology, plan and workspace administration." />
      <Tabs<TabKey> value={tab} onChange={setTab} tabs={[{ value: "profile", label: "Profile" }, { value: "integrations", label: "Integrations" }, { value: "scoring", label: "Scoring weights" },
        { value: "billing", label: "Plan & billing" }, { value: "workspace", label: "Workspace" }, { value: "data", label: "Data & jobs" }]} />
      {tab === "profile" && <ProfileTab />}
      {tab === "integrations" && <IntegrationsTab githubParam={githubParam} />}
      {tab === "scoring" && <ScoringTab />}
      {tab === "billing" && <BillingTab checkoutParam={params.get("checkout")} initialPlan={params.get("plan")} initialInterval={params.get("interval") === "year" ? "year" : "month"} />}
      {tab === "workspace" && <WorkspaceTab />}
      {tab === "data" && <DataTab />}
    </div>
  );
}

export default function SettingsPage() {
  return <Suspense><SettingsContent /></Suspense>;
}
