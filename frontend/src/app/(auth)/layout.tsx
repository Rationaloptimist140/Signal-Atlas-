import { Activity, Radar, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import { Logo } from "@/components/shell";

const POINTS = [
  { icon: Activity, title: "Emerging signals", text: "Unusual growth, accelerating development and new project clusters, each with the evidence behind it." },
  { icon: Radar, title: "Commercial opportunity hypotheses", text: "Transparent 0–100 scoring with confidence, missing-data notes and licence risk." },
  { icon: ShieldCheck, title: "Facts kept apart from inference", text: "Verified GitHub data, calculated metrics, interpretations and hypotheses are always labelled." },
];

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <aside className="relative hidden overflow-hidden border-r border-line bg-surface lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(600px_400px_at_20%_10%,rgba(139,92,246,0.18),transparent_60%),radial-gradient(500px_400px_at_90%_90%,rgba(34,211,238,0.1),transparent_60%)]" />
        <div className="relative"><Logo href="/" /></div>
        <div className="relative max-w-lg">
          <p className="text-2xs font-semibold uppercase tracking-[0.2em] text-primary-bright">Open-source technology intelligence</p>
          <h1 className="mt-4 text-4xl font-semibold leading-tight tracking-tight text-ink text-balance">Discover technology. Identify opportunities. See what comes next.</h1>
          <ul className="mt-10 space-y-6">
            {POINTS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line-strong bg-card text-accent"><Icon className="h-4 w-4" /></span>
                <div><p className="text-sm font-medium text-ink">{title}</p><p className="mt-1 text-sm leading-relaxed text-ink-muted">{text}</p></div>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-ink-faint">Analyses public GitHub data only. Read-only access; never modifies repositories.</p>
      </aside>
      <main className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden"><Logo href="/" /></div>
          {children}
        </div>
      </main>
    </div>
  );
}
