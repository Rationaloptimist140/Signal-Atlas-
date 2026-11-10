"use client";

import { Activity, Boxes, GitBranch, Radar, Swords, Users } from "lucide-react";
import Link from "next/link";
import { errorMessage } from "@/lib/api";
import { useIntel } from "@/lib/session";
import type { Dashboard } from "@/lib/types";
import { formatNumber, timeAgo } from "@/lib/utils";
import { EcosystemCard, GettingStarted, MomentumCard, OpportunityRadarCard, SetupChecklist } from "@/components/dashboard-sections";
import { SignalCard, StatCard } from "@/components/intel";
import { Card, CardHeader, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";

const STATS = [
  { key: "repositories_monitored", label: "Repositories monitored", icon: GitBranch },
  { key: "technologies_detected", label: "Technologies detected", icon: Boxes },
  { key: "trending_projects", label: "Trending projects", icon: Activity },
  { key: "opportunities_discovered", label: "Opportunities", icon: Radar },
  { key: "developers_analysed", label: "Developers analysed", icon: Users },
  { key: "competitors_monitored", label: "Competitors monitored", icon: Swords },
] as const;

export default function OverviewPage() {
  const { data, error, isLoading, mutate } = useIntel<Dashboard>("/dashboard");

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Intelligence terminal" title="Overview"
        description={data?.provenance.last_synced_at ? `Latest data collected ${timeAgo(data.provenance.last_synced_at)} · ${data.provenance.fully_synced_repositories} ${data.provenance.fully_synced_repositories === 1 ? "repository" : "repositories"} fully synced` : "Open-source technology and commercial opportunity intelligence."} />

      {error && !data ? <Card><ErrorState message={errorMessage(error)} onRetry={() => mutate()} /></Card> : (
        <section aria-label="Intelligence summary" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {STATS.map(({ key, label, icon: Icon }) =>
            isLoading && !data ? <Skeleton key={key} className="h-[104px] rounded-xl" />
              : <StatCard key={key} label={label} value={formatNumber(data?.summary[key])} hint={data?.summary_definitions[key]} icon={<Icon className="h-4 w-4" />} />)}
        </section>
      )}

      {data?.provenance.mode === "empty" ? <GettingStarted /> : (
        <>
          <div className="grid gap-6 xl:grid-cols-[1.35fr_1fr]">
            <MomentumCard />
            <Card className="flex flex-col">
              <CardHeader title={<span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-success animate-pulse-dot" />Emerging signals</span>}
                description="Detected changes with evidence — not forecasts" action={<Link href="/trends" className="text-xs text-primary-bright hover:underline">All signals →</Link>} />
              <div className="max-h-[430px] flex-1 overflow-y-auto scrollbar-thin">
                {isLoading && !data ? <div className="space-y-2 p-5">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-16" />)}</div>
                  : data?.signals.length ? data.signals.map((signal) => <SignalCard key={signal.id} signal={signal} compact />)
                  : <EmptyState title="No signals yet" description="Signals appear once repositories have commit history or snapshots on more than one day." />}
              </div>
            </Card>
          </div>
          <OpportunityRadarCard />
          <EcosystemCard />
        </>
      )}
      {data && <SetupChecklist setup={data.setup} />}
    </div>
  );
}
