"use client";

import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart, PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import type { Metric, Opportunity } from "@/lib/types";
import { CATEGORY_COLORS, categoryLabel, formatCompact } from "@/lib/utils";

const tooltipStyle = {
  contentStyle: { background: "#101626", border: "1px solid rgba(148,163,184,0.26)", borderRadius: 10, fontSize: 12, boxShadow: "0 12px 32px -12px rgba(0,0,0,0.8)" },
  labelStyle: { color: "#94A3B8", marginBottom: 4 },
  itemStyle: { color: "#F8FAFC", padding: 0 },
  cursor: { stroke: "rgba(148,163,184,0.3)" },
} as const;

const shortDate = (value: string) => new Date(value).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

export function CategoryLegend({ categories }: { categories: { key: string; label: string }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1.5 px-5 pb-4 text-2xs text-ink-muted">
      {categories.map((c) => (
        <li key={c.key} className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: CATEGORY_COLORS[c.key] ?? "#94A3B8" }} />{c.label}</li>
      ))}
    </ul>
  );
}

export function CategoryLines({ data, categories, xKey, unit, height = 260 }: { data: Record<string, number | string>[]; categories: { key: string; label: string }[]; xKey: string; unit?: string; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey={xKey} tickFormatter={shortDate} tickLine={false} axisLine={false} minTickGap={32} />
        <YAxis tickLine={false} axisLine={false} tickFormatter={(v) => `${formatCompact(v)}${unit ?? ""}`} width={52} />
        <Tooltip {...tooltipStyle} labelFormatter={(v) => shortDate(String(v))} formatter={(value: number, name: string) => [`${typeof value === "number" ? value.toLocaleString("en-GB") : value}${unit ?? ""}`, categoryLabel(name)]} />
        {categories.map((c) => <Line key={c.key} type="monotone" dataKey={c.key} stroke={CATEGORY_COLORS[c.key] ?? "#94A3B8"} strokeWidth={1.75} dot={false} activeDot={{ r: 3 }} connectNulls />)}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function AdoptionBars({ data, height = 260 }: { data: { category: string; label: string; repositories: number; stars: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 0, left: 8 }}>
        <CartesianGrid horizontal={false} />
        <XAxis type="number" tickLine={false} axisLine={false} allowDecimals={false} />
        <YAxis type="category" dataKey="label" tickLine={false} axisLine={false} width={150} />
        <Tooltip {...tooltipStyle} cursor={{ fill: "rgba(148,163,184,0.06)" }} formatter={(value: number, name: string) => [value.toLocaleString("en-GB"), name === "repositories" ? "Tracked repositories" : name]} />
        <Bar dataKey="repositories" radius={[0, 4, 4, 0]} barSize={14}>
          {data.map((row) => <Cell key={row.category} fill={CATEGORY_COLORS[row.category] ?? "#8B5CF6"} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function CommitBars({ data, height = 220 }: { data: { week_start: string; commits: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="week_start" tickFormatter={shortDate} tickLine={false} axisLine={false} minTickGap={28} />
        <YAxis tickLine={false} axisLine={false} allowDecimals={false} />
        <Tooltip {...tooltipStyle} cursor={{ fill: "rgba(148,163,184,0.06)" }} labelFormatter={(v) => `Week of ${shortDate(String(v))}`} formatter={(value: number) => [value, "Commits"]} />
        <Bar dataKey="commits" fill="#8B5CF6" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function StarArea({ data, height = 220 }: { data: { date: string; stars: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -4 }}>
        <defs>
          <linearGradient id="starFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#22D3EE" stopOpacity={0.35} /><stop offset="100%" stopColor="#22D3EE" stopOpacity={0} /></linearGradient>
        </defs>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="date" tickFormatter={shortDate} tickLine={false} axisLine={false} minTickGap={28} />
        <YAxis tickLine={false} axisLine={false} domain={["auto", "auto"]} tickFormatter={(v) => formatCompact(v)} width={48} />
        <Tooltip {...tooltipStyle} labelFormatter={(v) => shortDate(String(v))} formatter={(value: number) => [value.toLocaleString("en-GB"), "Stars"]} />
        <Area type="monotone" dataKey="stars" stroke="#22D3EE" strokeWidth={2} fill="url(#starFill)" />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function MetricRadar({ metrics, height = 280 }: { metrics: Metric[] | { key: string; label: string; score: number | null }[]; height?: number }) {
  const data = metrics.map((m) => ({ metric: m.label.replace("Development ", "Dev. ").replace("Competitive ", "Comp. "), score: m.score ?? 0 }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <RadarChart data={data} outerRadius="72%">
        <PolarGrid stroke="rgba(148,163,184,0.18)" />
        <PolarAngleAxis dataKey="metric" tick={{ fill: "#94A3B8", fontSize: 11 }} />
        <Radar dataKey="score" stroke="#8B5CF6" strokeWidth={2} fill="#8B5CF6" fillOpacity={0.22} />
        <Tooltip {...tooltipStyle} formatter={(value: number) => [Math.round(value), "Score"]} />
      </RadarChart>
    </ResponsiveContainer>
  );
}

const RISK_COLORS: Record<string, string> = { low: "#10B981", medium: "#F59E0B", high: "#F43F5E" };

/** Opportunity radar: development momentum (x) against commercial potential (y); bubble size is the total score. */
export function OpportunityRadar({ opportunities, onSelect, height = 320 }: { opportunities: Opportunity[]; onSelect?: (id: number) => void; height?: number }) {
  const points = opportunities
    .map((o) => {
      const metric = (key: string) => o.metrics.find((m) => m.key === key)?.score;
      const x = metric("development_momentum");
      const y = metric("commercial_potential");
      return x === null || x === undefined || y === null || y === undefined ? null : { x, y, z: o.score, id: o.id, name: o.repository_full_name, risk: o.risk_level, score: o.score };
    })
    .filter((p): p is NonNullable<typeof p> => p !== null);
  const unplotted = opportunities.length - points.length;
  return (
    <div>
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ top: 12, right: 16, bottom: 28, left: 4 }}>
        <CartesianGrid />
        <XAxis type="number" dataKey="x" domain={[0, 100]} tickLine={false} axisLine={false} label={{ value: "Development momentum", position: "bottom", offset: 8, fill: "#64748B", fontSize: 11 }} />
        <YAxis type="number" dataKey="y" domain={[0, 100]} tickLine={false} axisLine={false} width={44} label={{ value: "Commercial potential", angle: -90, position: "insideLeft", offset: 12, fill: "#64748B", fontSize: 11 }} />
        <ZAxis type="number" dataKey="z" range={[60, 420]} domain={[0, 100]} />
        <Tooltip {...tooltipStyle} cursor={{ strokeDasharray: "3 3" }} content={({ active, payload }) => {
          if (!active || !payload?.length) return null;
          const p = payload[0].payload as (typeof points)[number];
          return (
            <div className="rounded-[10px] border border-line-strong bg-surface px-3 py-2 text-xs shadow-2xl">
              <p className="font-medium text-ink">{p.name}</p>
              <p className="num mt-1 text-ink-muted">Score {Math.round(p.score)} · momentum {Math.round(p.x)} · commercial {Math.round(p.y)}</p>
              <p className="mt-0.5 capitalize text-ink-faint">{p.risk} risk</p>
            </div>
          );
        }} />
        <Scatter data={points} onClick={(point) => onSelect?.((point as unknown as { id: number }).id)} cursor={onSelect ? "pointer" : undefined}>
          {points.map((p) => <Cell key={p.id} fill={RISK_COLORS[p.risk] ?? "#8B5CF6"} fillOpacity={0.55} stroke={RISK_COLORS[p.risk] ?? "#8B5CF6"} />)}
        </Scatter>
      </ScatterChart>
    </ResponsiveContainer>
    {unplotted > 0 && (
      <p className="px-3 pb-1 text-2xs text-ink-faint">
        {unplotted} of {opportunities.length} not plotted: development momentum is measured after a full sync (commit and release history).
      </p>
    )}
    </div>
  );
}

export function ScoreHistory({ data, height = 120 }: { data: { date: string; total_default: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
        <XAxis dataKey="date" tickFormatter={shortDate} tickLine={false} axisLine={false} minTickGap={28} />
        <YAxis domain={[0, 100]} tickLine={false} axisLine={false} />
        <Tooltip {...tooltipStyle} labelFormatter={(v) => shortDate(String(v))} formatter={(value: number) => [value, "Score"]} />
        <Line type="monotone" dataKey="total_default" stroke="#8B5CF6" strokeWidth={2} dot={{ r: 2 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}
