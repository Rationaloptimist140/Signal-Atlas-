"use client";

import {
  Activity, Bell, Binoculars, BookMarked, Boxes, ChevronsLeft, Code2, FileText, FlaskConical, GitBranch, LayoutDashboard, LogOut, Menu, Radar, Radio,
  Search, Settings, Swords, Users, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { logout, useApi, useIntel, useSession, type SourceMode } from "@/lib/session";
import type { Dashboard, DataSource } from "@/lib/types";
import { cn, timeAgo } from "@/lib/utils";
import { ProvenanceBadge, UpgradeDialog } from "@/components/intel";
import { Badge, Button, Segmented, Spinner } from "@/components/ui";

export const NAV_ITEMS = [
  { href: "/overview", label: "Overview", icon: LayoutDashboard },
  { href: "/technologies", label: "Explore Technologies", icon: Boxes },
  { href: "/repositories", label: "Repository Intelligence", icon: GitBranch },
  { href: "/developers", label: "Developer Intelligence", icon: Users },
  { href: "/trends", label: "Emerging Trends", icon: Activity },
  { href: "/opportunities", label: "Opportunity Discovery", icon: Radar },
  { href: "/competitors", label: "Competitor Intelligence", icon: Swords },
  { href: "/reports", label: "Intelligence Reports", icon: FileText },
  { href: "/watchlists", label: "Watchlists", icon: BookMarked },
  { href: "/api-developers", label: "API & Developers", icon: Code2 },
  { href: "/settings", label: "Settings", icon: Settings },
] as const;

export function Logo({ collapsed }: { collapsed?: boolean }) {
  return (
    <Link href="/overview" className="flex items-center gap-2.5" aria-label="Signal Atlas home">
      <span className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-primary/40 bg-gradient-to-br from-primary/30 to-accent/20 shadow-glow">
        <Binoculars className="h-4 w-4 text-white" />
      </span>
      {!collapsed && <span className="text-sm font-semibold tracking-[0.2em] text-ink">SIGNAL <span className="text-primary-bright">ATLAS</span></span>}
    </Link>
  );
}

function Sidebar({ collapsed, onToggle, mobileOpen, onMobileClose }: { collapsed: boolean; onToggle: () => void; mobileOpen: boolean; onMobileClose: () => void }) {
  const pathname = usePathname();
  const { me } = useSession();
  return (
    <>
      {mobileOpen && <div className="fixed inset-0 z-40 bg-black/60 lg:hidden" onClick={onMobileClose} aria-hidden />}
      <aside aria-label="Main navigation"
        className={cn("fixed inset-y-0 left-0 z-50 flex flex-col border-r border-line bg-surface/95 backdrop-blur transition-[width,transform] duration-200 lg:translate-x-0",
          collapsed ? "lg:w-[68px]" : "lg:w-64", "w-64", mobileOpen ? "translate-x-0" : "-translate-x-full")}>
        <div className="flex h-14 items-center justify-between border-b border-line px-4">
          <Logo collapsed={collapsed} />
          <button onClick={onMobileClose} className="rounded-md p-1 text-ink-muted hover:bg-white/5 lg:hidden" aria-label="Close navigation"><X className="h-4 w-4" /></button>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-2 scrollbar-thin">
          {NAV_ITEMS.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            const Icon = item.icon;
            return (
              <Link key={item.href} href={item.href} onClick={onMobileClose} title={collapsed ? item.label : undefined} aria-current={active ? "page" : undefined}
                className={cn("group relative flex h-9 items-center gap-3 rounded-lg px-3 text-sm transition-colors",
                  active ? "bg-primary-soft text-ink" : "text-ink-muted hover:bg-white/5 hover:text-ink")}>
                {active && <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-primary" />}
                <Icon className={cn("h-4 w-4 shrink-0", active ? "text-primary-bright" : "text-ink-faint group-hover:text-ink-muted")} />
                <span className={cn("truncate", collapsed && "lg:hidden")}>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-line p-3">
          {me && (
            <div className={cn("mb-2 rounded-lg border border-line bg-card px-3 py-2", collapsed && "lg:hidden")}>
              <p className="truncate text-xs font-medium text-ink">{me.organisation.name}</p>
              <p className="mt-0.5 flex items-center justify-between text-2xs text-ink-faint">
                <span className="capitalize">{me.plan.name} plan</span>
                {me.plan.key === "free" && <Link href="/settings?tab=billing" className="text-primary-bright hover:underline">Upgrade</Link>}
              </p>
            </div>
          )}
          <button onClick={onToggle} className="hidden h-8 w-full items-center justify-center gap-2 rounded-lg text-xs text-ink-faint hover:bg-white/5 hover:text-ink lg:flex"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
            <ChevronsLeft className={cn("h-4 w-4 transition-transform", collapsed && "rotate-180")} />
            {!collapsed && "Collapse"}
          </button>
        </div>
      </aside>
    </>
  );
}

type SearchResults = Record<"repositories" | "developers" | "technologies" | "opportunities", { id: number; title: string; subtitle: string | null; link: string; data_source?: DataSource }[]>;

export function GlobalSearch() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
      }
      if (event.key === "Escape") setOpen(false);
    };
    const onClick = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as globalThis.Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, []);

  const { data, isLoading } = useIntel<SearchResults>(debounced.length >= 2 ? "/search" : null, { q: debounced });
  const groups = data ? (Object.entries(data) as [string, SearchResults["repositories"]][]).filter(([, items]) => items.length > 0) : [];

  return (
    <div ref={boxRef} className="relative w-full max-w-md">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
      <input ref={inputRef} type="search" value={query} onChange={(e) => { setQuery(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
        onKeyDown={(e) => { if (e.key === "Enter" && query.trim().length >= 2) { setOpen(false); router.push(`/repositories?q=${encodeURIComponent(query.trim())}`); } }}
        placeholder="Search repositories, developers, technologies…" aria-label="Global search"
        className="h-9 w-full rounded-lg border border-line bg-card pl-9 pr-14 text-sm text-ink placeholder:text-ink-faint focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30" />
      <kbd className="num pointer-events-none absolute right-2.5 top-1/2 hidden -translate-y-1/2 rounded border border-line px-1.5 py-0.5 text-2xs text-ink-faint sm:block">⌘K</kbd>
      {open && debounced.length >= 2 && (
        <div className="absolute inset-x-0 top-11 z-40 max-h-[70vh] overflow-y-auto rounded-xl border border-line-strong bg-surface p-2 shadow-2xl animate-fade-in scrollbar-thin">
          {isLoading && !data && <div className="flex items-center gap-2 px-3 py-4 text-sm text-ink-muted"><Spinner />Searching…</div>}
          {data && groups.length === 0 && (
            <div className="px-3 py-4 text-sm text-ink-muted">
              No tracked results for “{debounced}”.{" "}
              <Link href={`/repositories?github=${encodeURIComponent(debounced)}`} onClick={() => setOpen(false)} className="text-accent hover:underline">Search GitHub live</Link>
            </div>
          )}
          {groups.map(([group, items]) => (
            <div key={group} className="mb-1">
              <p className="px-3 pb-1 pt-2 text-2xs font-semibold uppercase tracking-wider text-ink-faint">{group}</p>
              {items.map((item) => (
                <Link key={`${group}-${item.id}`} href={item.link} onClick={() => { setOpen(false); setQuery(""); }} className="flex items-center justify-between gap-3 rounded-lg px-3 py-2 hover:bg-white/5">
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-ink">{item.title}</span>
                    {item.subtitle && <span className="block truncate text-xs text-ink-faint">{item.subtitle}</span>}
                  </span>
                  <ProvenanceBadge source={item.data_source} />
                </Link>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

type NotificationList = { items: { id: number; kind: string; title: string; body: string; link: string | null; read: boolean; created_at: string }[]; unread: number };

function NotificationCentre() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { data, mutate } = useApi<NotificationList>("/notifications", undefined, { refreshInterval: 60_000 });
  useEffect(() => {
    const onClick = (event: MouseEvent) => { if (ref.current && !ref.current.contains(event.target as globalThis.Node)) setOpen(false); };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, []);
  async function markAll() {
    await api("/notifications/read-all", { method: "POST" });
    await mutate();
  }
  const unread = data?.unread ?? 0;
  return (
    <div ref={ref} className="relative">
      <Button variant="ghost" size="icon" onClick={() => setOpen((v) => !v)} aria-label={`Notifications${unread ? ` (${unread} unread)` : ""}`} aria-expanded={open}>
        <Bell className="h-4 w-4" />
        {unread > 0 && <span className="num absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold text-white">{unread > 9 ? "9+" : unread}</span>}
      </Button>
      {open && (
        <div className="absolute right-0 top-11 z-40 w-80 rounded-xl border border-line-strong bg-surface shadow-2xl animate-fade-in">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <p className="text-sm font-semibold text-ink">Notifications</p>
            {unread > 0 && <button onClick={markAll} className="text-xs text-primary-bright hover:underline">Mark all read</button>}
          </div>
          <div className="max-h-96 overflow-y-auto scrollbar-thin">
            {!data?.items.length && <p className="px-4 py-8 text-center text-sm text-ink-muted">No notifications yet. Changes on repositories you watch or track as competitors appear here.</p>}
            {data?.items.map((note) => (
              <Link key={note.id} href={note.link ?? "#"} onClick={() => setOpen(false)} className="flex gap-3 border-b border-line px-4 py-3 last:border-0 hover:bg-white/5">
                <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", note.read ? "bg-white/10" : "bg-primary")} />
                <span className="min-w-0">
                  <span className="block text-sm leading-snug text-ink">{note.title}</span>
                  <span className="mt-0.5 block text-2xs text-ink-faint">{note.kind.replace("_", " ")} · {timeAgo(note.created_at)}</span>
                </span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function UserMenu() {
  const { me } = useSession();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onClick = (event: MouseEvent) => { if (ref.current && !ref.current.contains(event.target as globalThis.Node)) setOpen(false); };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, []);
  const initials = (me?.user.full_name || me?.user.email || "?").split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((v) => !v)} aria-label="Account menu" aria-expanded={open}
        className="flex h-9 w-9 items-center justify-center rounded-full border border-line-strong bg-gradient-to-br from-primary/40 to-accent/20 text-xs font-semibold text-white">
        {initials}
      </button>
      {open && me && (
        <div className="absolute right-0 top-11 z-40 w-60 rounded-xl border border-line-strong bg-surface p-2 shadow-2xl animate-fade-in">
          <div className="border-b border-line px-3 pb-3 pt-2">
            <p className="truncate text-sm font-medium text-ink">{me.user.full_name}</p>
            <p className="truncate text-xs text-ink-faint">{me.user.email}</p>
            <Badge tone="primary" className="mt-2">{me.role}</Badge>
          </div>
          <Link href="/settings" onClick={() => setOpen(false)} className="mt-1 flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-ink-muted hover:bg-white/5 hover:text-ink"><Settings className="h-4 w-4" />Settings</Link>
          <button onClick={() => logout()} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-ink-muted hover:bg-white/5 hover:text-ink"><LogOut className="h-4 w-4" />Sign out</button>
        </div>
      )}
    </div>
  );
}

function SourceSwitch() {
  const { source, setSource } = useSession();
  return (
    <div className="hidden md:block" title="Choose which data the terminal shows. Auto shows live GitHub data as soon as any exists.">
      <Segmented<SourceMode> label="Data source" value={source} onChange={setSource} options={[{ value: "auto", label: "Auto" }, { value: "live", label: "Live" }, { value: "demo", label: "Demo" }]} />
    </div>
  );
}

function ProvenanceBanner() {
  const { data } = useIntel<Dashboard>("/dashboard");
  if (!data) return null;
  const { mode, message, live_repositories } = data.provenance;
  if (mode === "live") return null;
  return (
    <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-4 py-2 text-xs sm:px-6", mode === "demo" || mode === "mixed" ? "border-warning/25 bg-warning-soft text-warning" : "border-line bg-surface text-ink-muted")}>
      {mode === "empty" ? <Radio className="h-3.5 w-3.5" /> : <FlaskConical className="h-3.5 w-3.5" />}
      <span className="font-semibold uppercase tracking-wider">{mode === "empty" ? "No data yet" : mode === "demo" ? "Demonstration data" : "Mixed data"}</span>
      <span className="text-ink/80">{message}</span>
      {live_repositories === 0 && <Link href="/repositories?github=1" className="font-medium text-accent hover:underline">Search GitHub for live data →</Link>}
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const { me, loading } = useSession();

  useEffect(() => { setCollapsed(window.localStorage.getItem("signal-atlas:sidebar") === "collapsed"); }, []);
  const toggle = () => setCollapsed((value) => { window.localStorage.setItem("signal-atlas:sidebar", value ? "expanded" : "collapsed"); return !value; });

  if (loading && !me) {
    return <div className="flex h-screen items-center justify-center" role="status"><Spinner className="h-6 w-6" /><span className="sr-only">Loading workspace</span></div>;
  }
  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-lg focus:bg-primary focus:px-3 focus:py-2 focus:text-sm focus:text-white">Skip to content</a>
      <Sidebar collapsed={collapsed} onToggle={toggle} mobileOpen={mobileOpen} onMobileClose={() => setMobileOpen(false)} />
      <div className={cn("flex min-h-screen min-w-0 flex-col transition-[padding] duration-200", collapsed ? "lg:pl-[68px]" : "lg:pl-64")}>
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-bg/80 px-4 backdrop-blur sm:px-6">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu className="h-4 w-4" /></Button>
          <GlobalSearch />
          <div className="ml-auto flex items-center gap-2">
            <SourceSwitch />
            <NotificationCentre />
            <UserMenu />
          </div>
        </header>
        <ProvenanceBanner />
        <main id="main" className="mx-auto w-full min-w-0 max-w-[1500px] flex-1 overflow-x-clip px-4 py-6 sm:px-6 lg:px-8">{children}</main>
        <footer className="border-t border-line px-6 py-4 text-2xs text-ink-faint">
          Signal Atlas analyses public GitHub data only. Scores and opportunities are heuristics and unverified hypotheses, not investment advice.
        </footer>
      </div>
      <UpgradeDialog />
    </div>
  );
}
