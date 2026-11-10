import { Activity, ArrowRight, FileText, GitBranch, Radar, ShieldCheck, Swords, Users } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "SIGNAL ATLAS — open-source technology intelligence" };

const ENGINES = [
  { icon: GitBranch, title: "Repository intelligence", text: "Search public repositories and inspect commit activity, contributors, releases, forks, dependencies and licences — every figure links back to GitHub." },
  { icon: Users, title: "Developer intelligence", text: "Public contribution activity and collaboration networks. Inferred attributes are labelled as inferred; visibility is never presented as ability." },
  { icon: Activity, title: "Emerging technology detection", text: "Star surges, accelerating development, contributor growth and new project clusters, each with the evidence that triggered it." },
  { icon: Radar, title: "Commercial opportunity discovery", text: "For each project: the problem, target customers, monetisation models, adjacent projects, licence risk and a recommended next step." },
  { icon: Swords, title: "Competitive intelligence", text: "Track competitors' repositories for new releases, dependency changes and stack changes, with notifications when something moves." },
  { icon: FileText, title: "Intelligence reports", text: "Saved reports that separate verified facts, calculated metrics, interpretations and unverified hypotheses." },
];

const WEIGHTS = [["Development momentum", 20], ["Commercial potential", 20], ["Developer adoption", 15], ["Technical innovation", 15], ["Community growth", 10], ["Market demand", 10], ["Competitive positioning", 10]] as const;

const PRINCIPLES = [
  { title: "Real data, labelled", text: "Live GitHub data and demonstration fixtures are always marked. An empty workspace shows zeros, not invented statistics." },
  { title: "Evidence with every score", text: "Each metric shows what it was built from, how fresh the data is, how confident the score is and what is missing." },
  { title: "Hypotheses stay hypotheses", text: "A popular repository is not a validated business. Opportunities are presented as ideas to test, with their risks." },
  { title: "Read-only by design", text: "Signal Atlas reads public data through the GitHub API. It never modifies repositories and never asks for write access." },
];

export default function LandingPage() {
  return (
    <>
      <section className="relative overflow-hidden border-b border-line">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(700px_420px_at_50%_-10%,rgba(139,92,246,0.22),transparent_65%)]" />
        <div className="relative mx-auto max-w-4xl px-5 py-24 text-center sm:py-32">
          <p className="text-2xs font-semibold uppercase tracking-[0.24em] text-primary-bright">Open-source technology intelligence</p>
          <h1 className="mt-5 text-4xl font-semibold leading-[1.08] tracking-tight text-ink text-balance sm:text-6xl">Find the technology and the opportunity before the market does.</h1>
          <p className="mx-auto mt-6 max-w-2xl text-base leading-relaxed text-ink-muted text-balance sm:text-lg">
            Signal Atlas turns public GitHub activity into evidence-backed intelligence for founders, investors and product teams: what is gaining momentum, who is building it, and which projects show the signals of a commercial opportunity.
          </p>
          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link href="/register" className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-6 text-sm font-medium text-white shadow-glow hover:bg-primary-bright">Start free <ArrowRight className="h-4 w-4" /></Link>
            <Link href="/pricing" className="inline-flex h-11 items-center rounded-lg border border-line-strong bg-raised px-6 text-sm font-medium text-ink hover:bg-[#223049]">See pricing</Link>
          </div>
          <p className="mt-4 text-xs text-ink-faint">Free plan, no card required.</p>
        </div>
      </section>

      <section id="engines" className="mx-auto max-w-6xl px-5 py-20">
        <h2 className="text-2xl font-semibold tracking-tight text-ink">Six connected intelligence engines</h2>
        <p className="mt-2 max-w-2xl text-sm text-ink-muted">One terminal from raw repository data to a commercial hypothesis you can test.</p>
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {ENGINES.map(({ icon: Icon, title, text }) => (
            <div key={title} className="rounded-xl border border-line bg-card p-6 shadow-card">
              <span className="flex h-10 w-10 items-center justify-center rounded-lg border border-line-strong bg-surface text-accent"><Icon className="h-5 w-5" /></span>
              <h3 className="mt-4 text-base font-semibold text-ink">{title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-ink-muted">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="border-y border-line bg-surface/50">
        <div className="mx-auto grid max-w-6xl gap-12 px-5 py-20 lg:grid-cols-2">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight text-ink">A score you can interrogate</h2>
            <p className="mt-3 text-sm leading-relaxed text-ink-muted">
              The business potential score runs from 0 to 100 across seven weighted metrics. Open any metric to see its evidence, confidence and missing data. Scores rank projects by observable signals; they are not predictions of commercial success.
            </p>
            <p className="mt-3 text-sm leading-relaxed text-ink-muted">Metrics without data are left unscored and the total is damped towards neutral, so thin evidence cannot produce a headline number.</p>
          </div>
          <ul className="space-y-3">
            {WEIGHTS.map(([label, weight]) => (
              <li key={label}>
                <div className="mb-1 flex justify-between text-sm"><span className="text-ink">{label}</span><span className="num text-ink-muted">{weight}%</span></div>
                <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.07]"><div className="h-full rounded-full bg-gradient-to-r from-primary to-accent" style={{ width: `${weight * 5}%` }} /></div>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-5 py-20">
        <div className="flex items-center gap-3"><ShieldCheck className="h-6 w-6 text-success" /><h2 className="text-2xl font-semibold tracking-tight text-ink">Built to be trusted</h2></div>
        <div className="mt-10 grid gap-x-10 gap-y-8 sm:grid-cols-2">
          {PRINCIPLES.map((p) => (
            <div key={p.title} className="border-l-2 border-primary/50 pl-5"><h3 className="text-base font-semibold text-ink">{p.title}</h3><p className="mt-1.5 text-sm leading-relaxed text-ink-muted">{p.text}</p></div>
          ))}
        </div>
      </section>

      <section className="border-t border-line">
        <div className="mx-auto max-w-3xl px-5 py-20 text-center">
          <h2 className="text-3xl font-semibold tracking-tight text-ink text-balance">Start with the free plan and your first live GitHub search.</h2>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link href="/register" className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-6 text-sm font-medium text-white shadow-glow hover:bg-primary-bright">Create your workspace <ArrowRight className="h-4 w-4" /></Link>
            <Link href="/login" className="text-sm text-ink-muted hover:text-ink">Already have an account? Sign in</Link>
          </div>
        </div>
      </section>
    </>
  );
}
