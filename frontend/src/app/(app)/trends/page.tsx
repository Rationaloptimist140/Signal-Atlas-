"use client";

import { useState } from "react";
import { errorMessage } from "@/lib/api";
import { useIntel } from "@/lib/session";
import type { Signal } from "@/lib/types";
import { CATEGORY_LABELS } from "@/lib/utils";
import { MomentumCard } from "@/components/dashboard-sections";
import { SignalCard, signalLabel } from "@/components/intel";
import { Card, EmptyState, ErrorState, LoadingRows, Notice, PageHeader, Select, Tabs } from "@/components/ui";

type Trends = { items: Signal[]; counts_by_window: Record<"daily" | "weekly" | "monthly", number>; methodology: string };
const TYPES = ["star_surge", "unusual_growth", "commit_acceleration", "breakout_new_project", "contributor_growth", "release_burst", "category_momentum", "emerging_cluster"];

export default function TrendsPage() {
  const [window, setWindow] = useState<"all" | "daily" | "weekly" | "monthly">("all");
  const [category, setCategory] = useState("");
  const [signalType, setSignalType] = useState("");
  const { data, error, isLoading, mutate } = useIntel<Trends>("/trends", { window, category, signal_type: signalType, limit: 100 });
  const counts = data?.counts_by_window;
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Engine 3" title="Emerging Trends" description="Unusual growth, accelerating development and new project clusters, detected from dated snapshots and commit history." />
      <MomentumCard />
      <Card>
        <Tabs className="px-3" value={window} onChange={setWindow} tabs={[
          { value: "all", label: "All windows", count: counts ? counts.daily + counts.weekly + counts.monthly : undefined },
          { value: "daily", label: "Daily", count: counts?.daily }, { value: "weekly", label: "Weekly", count: counts?.weekly }, { value: "monthly", label: "Monthly", count: counts?.monthly }]} />
        <div className="flex flex-wrap gap-2 border-b border-line px-5 py-3">
          <Select value={category} onChange={(e) => setCategory(e.target.value)} className="h-8 w-auto text-xs" aria-label="Category">
            <option value="">All categories</option>{Object.entries(CATEGORY_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>
          <Select value={signalType} onChange={(e) => setSignalType(e.target.value)} className="h-8 w-auto text-xs" aria-label="Signal type">
            <option value="">All signal types</option>{TYPES.map((t) => <option key={t} value={t}>{signalLabel(t)}</option>)}</Select>
        </div>
        {isLoading && !data ? <LoadingRows rows={6} /> : error ? <ErrorState message={errorMessage(error)} onRetry={() => mutate()} />
          : !data?.items.length ? <EmptyState title="No signals for this view" description={window === "daily" || window === "weekly" ? "Daily and weekly signals need snapshots on consecutive days. They fill in as scheduled syncs run." : "Signals are detected once repositories have commit history or more than one snapshot."} />
          : data.items.map((signal) => <SignalCard key={signal.id} signal={signal} />)}
      </Card>
      {data && <Notice title="Methodology.">{data.methodology}</Notice>}
    </div>
  );
}
