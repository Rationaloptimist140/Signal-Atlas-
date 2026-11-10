"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { errorMessage } from "@/lib/api";
import { useIntel } from "@/lib/session";
import type { Developer, Page } from "@/lib/types";
import { formatCompact, formatNumber } from "@/lib/utils";
import { Avatar, ProvenanceBadge, SaveButton } from "@/components/intel";
import { Card, EmptyState, ErrorState, Input, LoadingRows, Notice, PageHeader, Pagination, Select, Td, Th } from "@/components/ui";

export default function DevelopersPage() {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("tracked_contributions");
  const [page, setPage] = useState(1);
  const { data, error, isLoading, mutate } = useIntel<Page<Developer>>("/developers", { q, sort, page, page_size: 25 });
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Engine 2" title="Developer Intelligence" description="Public contribution activity for developers working on tracked repositories." />
      <Notice title="How to read this page.">
        Profiles use only what developers have made public on GitHub. Follower and contribution counts describe visibility, not technical ability. Anything inferred by Signal Atlas is labelled as inferred.
      </Notice>
      <Card>
        <div className="flex flex-col gap-2 border-b border-line p-4 sm:flex-row">
          <div className="relative flex-1"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
            <Input value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} placeholder="Search by login or name" className="pl-9" aria-label="Search developers" /></div>
          <Select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }} className="sm:w-64" aria-label="Sort developers">
            <option value="tracked_contributions">Most commits to tracked repositories</option><option value="followers">Most followers</option><option value="emerging">Newest accounts (emerging)</option><option value="login">Login A–Z</option>
          </Select>
        </div>
        {isLoading && !data ? <LoadingRows rows={8} /> : error ? <ErrorState message={errorMessage(error)} onRetry={() => mutate()} />
          : !data?.items.length ? <EmptyState title="No developers found" description="Developer profiles are created from the contributor lists of fully synced repositories." />
          : (
            <div className="overflow-x-auto scrollbar-thin"><table className="w-full min-w-[760px]">
              <thead className="bg-surface/60"><tr><Th>Developer</Th><Th>Languages (inferred)</Th><Th className="text-right">Tracked repos</Th><Th className="text-right">Commits to tracked repos</Th><Th className="text-right">Followers</Th><Th /></tr></thead>
              <tbody className="divide-y divide-line">{data.items.map((dev) => (
                <tr key={dev.id} className="hover:bg-white/[0.02]">
                  <Td><Link href={`/developers/${dev.id}`} className="flex items-center gap-3"><Avatar src={dev.avatar_url} login={dev.login} />
                    <span className="min-w-0"><span className="block truncate font-medium text-ink hover:text-primary-bright">{dev.login}</span>{dev.name && <span className="block truncate text-xs text-ink-faint">{dev.name}</span>}</span>
                    <ProvenanceBadge source={dev.data_source} /></Link></Td>
                  <Td className="text-xs text-ink-muted">{dev.top_languages?.length ? dev.top_languages.join(", ") : "—"}</Td>
                  <Td className="num text-right">{formatNumber(dev.tracked_repositories)}</Td>
                  <Td className="num text-right">{formatNumber(dev.tracked_contributions)}</Td>
                  <Td className="num text-right text-ink-muted">{dev.followers === null ? <span title="Refresh the profile to load public details">—</span> : formatCompact(dev.followers)}</Td>
                  <Td className="text-right"><SaveButton itemType="developer" itemId={dev.id} /></Td>
                </tr>))}</tbody></table></div>
          )}
        {data && <Pagination page={page} pageSize={25} total={data.total} onChange={setPage} />}
      </Card>
    </div>
  );
}
