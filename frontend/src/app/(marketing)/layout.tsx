import Link from "next/link";
import type { ReactNode } from "react";
import { Logo } from "@/components/shell";

export default function MarketingLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-line bg-bg/80 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
          <Logo href="/" />
          <nav aria-label="Site" className="flex items-center gap-1 text-sm">
            <Link href="/#engines" className="hidden rounded-lg px-3 py-2 text-ink-muted hover:text-ink sm:block">Product</Link>
            <Link href="/pricing" className="rounded-lg px-3 py-2 text-ink-muted hover:text-ink">Pricing</Link>
            <Link href="/login" className="rounded-lg px-3 py-2 text-ink-muted hover:text-ink">Sign in</Link>
            <Link href="/register" className="ml-1 inline-flex h-9 items-center rounded-lg bg-primary px-4 font-medium text-white shadow-glow hover:bg-primary-bright">Get started</Link>
          </nav>
        </div>
      </header>
      <main className="flex-1">{children}</main>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 px-5 py-8 text-xs text-ink-faint sm:flex-row sm:items-center sm:justify-between">
          <p>Signal Atlas analyses public GitHub data only, with read-only access. Scores and opportunities are heuristics and unverified hypotheses, not investment advice.</p>
          <p className="flex shrink-0 gap-4"><Link href="/pricing" className="hover:text-ink">Pricing</Link><Link href="/login" className="hover:text-ink">Sign in</Link><a href="/api/docs" className="hover:text-ink">API</a></p>
        </div>
      </footer>
    </div>
  );
}
