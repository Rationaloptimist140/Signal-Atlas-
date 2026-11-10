import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-GB").format(value);
}

export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const abs = Math.abs(value);
  const trim = (n: number) => n.toFixed(1).replace(/\.0$/, "");
  if (abs >= 1_000_000) return `${trim(value / 1_000_000)}M`;
  if (abs >= 1_000) return `${trim(value / 1_000)}K`;
  return String(value);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function timeAgo(value: string | null | undefined, now: Date = new Date()): string {
  if (!value) return "never";
  const date = new Date(value);
  const seconds = Math.round((now.getTime() - date.getTime()) / 1000);
  if (Number.isNaN(seconds)) return "—";
  if (seconds < 60) return "just now";
  const units: [number, string][] = [[60, "minute"], [24, "hour"], [30, "day"], [12, "month"], [Number.POSITIVE_INFINITY, "year"]];
  let amount = Math.floor(seconds / 60);
  for (const [size, name] of units) {
    if (amount < size) return `${amount} ${name}${amount === 1 ? "" : "s"} ago`;
    amount = Math.floor(amount / size);
  }
  return formatDate(value);
}

export function scoreTone(score: number | null | undefined): "success" | "accent" | "warning" | "muted" {
  if (score === null || score === undefined) return "muted";
  if (score >= 70) return "success";
  if (score >= 50) return "accent";
  return "warning";
}

export const CATEGORY_COLORS: Record<string, string> = {
  "ai-ml": "#8B5CF6",
  fintech: "#10B981",
  blockchain: "#F59E0B",
  "developer-infrastructure": "#22D3EE",
  cybersecurity: "#F43F5E",
  automation: "#A3E635",
  "cloud-computing": "#60A5FA",
  "data-infrastructure": "#F472B6",
  "enterprise-software": "#FB923C",
};

export const CATEGORY_LABELS: Record<string, string> = {
  "ai-ml": "AI & Machine Learning",
  fintech: "Fintech",
  blockchain: "Blockchain",
  "developer-infrastructure": "Developer Infrastructure",
  cybersecurity: "Cybersecurity & Privacy",
  automation: "Automation",
  "cloud-computing": "Cloud Computing",
  "data-infrastructure": "Data Infrastructure",
  "enterprise-software": "Enterprise Software",
};

export function categoryLabel(key: string | null | undefined): string {
  if (!key) return "Uncategorised";
  return CATEGORY_LABELS[key] ?? key;
}

export function titleCase(value: string): string {
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatMoney(minor: number, currency = "GBP"): string {
  return new Intl.NumberFormat("en-GB", { style: "currency", currency, minimumFractionDigits: minor % 100 === 0 ? 0 : 2 }).format(minor / 100);
}
