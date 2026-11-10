"use client";

import { FileText, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import type { Page, Report } from "@/lib/types";
import { timeAgo, titleCase } from "@/lib/utils";
import { GeneratedByTag, ProvenanceBadge } from "@/components/intel";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingRows, Notice, PageHeader, Pagination, Select } from "@/components/ui";

type Usage = { plan: { name: string }; usage: { key: string; used: number; limit: number | null }[] };

export default function ReportsPage() {
  const { canEdit } = useSession();
  const [type, setType] = useState("");
  const [page, setPage] = useState(1);
  const { data, error, isLoading, mutate } = useApi<Page<Report>>("/reports", { report_type: type, page, page_size: 20 });
  const { data: sub } = useApi<Usage>("/billing/subscription");
  const [actionError, setActionError] = useState<string | null>(null);
  const reports = sub?.usage.find((u) => u.key === "reports");

  async function remove(id: number) {
    if (!window.confirm("Delete this report? This cannot be undone.")) return;
    try {
      await api(`/reports/${id}`, { method: "DELETE" });
      await mutate();
    } catch (err) {
      setActionError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Engine 8" title="Intelligence Reports" description="Saved reports that separate verified facts, calculated metrics, interpretations and unverified hypotheses."
        actions={<Select value={type} onChange={(e) => { setType(e.target.value); setPage(1); }} className="w-48" aria-label="Report type">
          <option value="">All report types</option><option value="opportunity">Opportunity</option><option value="repository">Repository</option><option value="competitor">Competitor</option><option value="comparison">Comparison</option></Select>} />
      {reports && <Notice>You have generated <span className="num text-ink">{reports.used}</span>{reports.limit !== null && <> of <span className="num text-ink">{reports.limit}</span></>} reports this month on the {sub?.plan.name} plan.</Notice>}
      {actionError && <Notice tone="danger">{actionError}</Notice>}
      <Card>
        {isLoading && !data ? <LoadingRows /> : error ? <ErrorState message={errorMessage(error)} onRetry={() => mutate()} />
          : !data?.items.length ? <EmptyState icon={<FileText className="h-5 w-5" />} title="No reports yet"
              description="Open an opportunity, repository or competitor and choose Generate report."
              action={<Link href="/opportunities"><Button variant="primary">Browse opportunities</Button></Link>} />
          : <ul className="divide-y divide-line">{data.items.map((report) => (
            <li key={report.id} className="flex items-start gap-4 px-5 py-4 hover:bg-white/[0.02]">
              <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line bg-surface text-primary-bright"><FileText className="h-4 w-4" /></span>
              <div className="min-w-0 flex-1">
                <Link href={`/reports/${report.id}`} className="font-medium text-ink hover:text-primary-bright">{report.title}</Link>
                {report.summary && <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-ink-muted">{report.summary}</p>}
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <Badge tone="accent">{titleCase(report.report_type)}</Badge><GeneratedByTag by={report.provider === "rules" ? "rules" : "ai"} /><ProvenanceBadge source={report.data_source} />
                  {report.status !== "complete" && <Badge tone="warning">{report.status}</Badge>}<span className="text-2xs text-ink-faint">{timeAgo(report.created_at)}</span>
                </div>
              </div>
              {canEdit && <Button variant="ghost" size="icon" onClick={() => remove(report.id)} aria-label={`Delete ${report.title}`}><Trash2 className="h-4 w-4" /></Button>}
            </li>))}</ul>}
        {data && <Pagination page={page} pageSize={20} total={data.total} onChange={setPage} />}
      </Card>
    </div>
  );
}
