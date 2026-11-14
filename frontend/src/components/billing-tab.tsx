"use client";

import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useApi, useSession } from "@/lib/session";
import type { PaymentRow, PlanCatalogue, SubscriptionInfo } from "@/lib/types";
import { formatDate, formatMoney, formatNumber } from "@/lib/utils";
import { IntervalToggle, PlanCards, type Interval } from "@/components/pricing";
import { Badge, Button, Card, CardHeader, ErrorState, Notice, ProgressBar, Td, Th } from "@/components/ui";

type Feedback = { tone: "success" | "danger" | "accent" | "warning"; text: string } | null;

const STATUS_META: Record<string, { label: string; tone: "success" | "warning" | "danger" | "neutral" | "accent" }> = {
  active: { label: "Active", tone: "success" }, pending: { label: "Checkout pending", tone: "accent" }, past_due: { label: "Payment failed", tone: "danger" },
  cancelled: { label: "Cancels at period end", tone: "warning" }, expired: { label: "Ended", tone: "neutral" },
};

export function BillingTab({ checkoutParam, checkoutSessionId, initialPlan, initialInterval }: { checkoutParam?: string | null; checkoutSessionId?: string | null; initialPlan?: string | null; initialInterval?: Interval }) {
  const { me, refresh } = useSession();
  const { data: catalogue } = useApi<PlanCatalogue>("/billing/plans");
  const { data: sub, error, mutate } = useApi<SubscriptionInfo>("/billing/subscription", undefined, { refreshInterval: checkoutParam === "success" ? 4000 : 0 });
  const { data: payments } = useApi<{ items: PaymentRow[] }>("/billing/payments");
  const [interval, setInterval] = useState<Interval>(initialInterval ?? "month");
  const [msg, setMsg] = useState<Feedback>(
    checkoutParam === "success" ? { tone: "success", text: "Checkout complete. Your plan updates here as soon as the payment provider confirms it (usually within seconds)." }
      : checkoutParam === "cancelled" ? { tone: "accent", text: "Checkout was cancelled. No charge was made." } : null);
  const [busy, setBusy] = useState<string | null>(null);
  const isOwner = me?.role === "owner";
  const synced = useRef(false);

  // Back from hosted checkout: ask the API to confirm the session with the provider straight away rather
  // than waiting for the webhook. Failure is harmless - the webhook and the polling above still apply.
  useEffect(() => {
    if (checkoutParam !== "success" || synced.current || !me) return;
    synced.current = true;
    api("/billing/sync", { method: "POST", body: { session_id: checkoutSessionId ?? null } }).then(() => Promise.all([mutate(), refresh()])).catch(() => undefined);
  }, [checkoutParam, checkoutSessionId, me, mutate, refresh]);

  const billing = sub?.billing ?? catalogue?.billing;
  const canBuy = !!billing && (billing.checkout_available || billing.self_serve_plan_change);
  const limit = (value: number | null) => (value === null ? "Unlimited" : formatNumber(value));

  async function run(key: string, action: () => Promise<Feedback | void>) {
    setBusy(key);
    setMsg(null);
    try {
      const feedback = await action();
      await Promise.all([mutate(), refresh()]);
      if (feedback) setMsg(feedback);
    } catch (err) {
      setMsg({ tone: "danger", text: errorMessage(err) });
    } finally {
      setBusy(null);
    }
  }
  const choose = (plan: string) => run(plan, async () => {
    const result = await api<{ status: string; checkout_url?: string }>("/billing/checkout", { method: "POST", body: { plan, interval } });
    if (result.checkout_url) {
      window.location.assign(result.checkout_url);
      return { tone: "accent", text: "Redirecting to secure checkout…" };
    }
    return { tone: "success", text: "Plan changed (development mode — no payment taken)." };
  });
  const cancel = () => { if (window.confirm("Cancel your subscription? You keep access until the end of the period you have paid for.")) void run("cancel", async () => { await api("/billing/cancel", { method: "POST" }); return { tone: "success", text: "Subscription cancelled. Access continues until the end of the current period." }; }); };
  const resume = () => run("resume", async () => { await api("/billing/resume", { method: "POST" }); return { tone: "success", text: "Cancellation undone. Your subscription will renew as normal." }; });
  const portal = () => run("portal", async () => { const { url } = await api<{ url: string }>("/billing/portal", { method: "POST" }); window.location.assign(url); });

  const status = sub ? STATUS_META[sub.status] : null;
  return (
    <div className="space-y-6">
      {billing && !billing.checkout_available && (
        <Notice tone="warning" title="Card payments are not configured.">
          {billing.message} An administrator must set <code className="num">BILLING_PROVIDER=stripe</code>, <code className="num">STRIPE_SECRET_KEY</code> and <code className="num">STRIPE_WEBHOOK_SECRET</code>.
          {billing.self_serve_plan_change && " Development mode is on, so plans can be switched without payment for testing."}
        </Notice>
      )}
      {billing?.checkout_available && billing.test_mode && <Notice tone="accent" title="Test mode.">{billing.message} Use the provider&apos;s test card numbers.</Notice>}
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
      {error && <Card><ErrorState message={errorMessage(error)} onRetry={() => mutate()} /></Card>}

      {sub && status && (
        <Card>
          <CardHeader title={<span className="flex flex-wrap items-center gap-2">{sub.subscribed_plan.name} plan <Badge tone={status.tone}>{status.label}</Badge>{sub.billing_interval && <Badge>{sub.billing_interval === "year" ? "Annual" : "Monthly"}</Badge>}</span>}
            description={
              sub.status === "past_due" ? (sub.plan.key === sub.subscribed_plan.key ? `A renewal payment failed. Update your card before ${formatDate(sub.grace_until)} to keep ${sub.subscribed_plan.name} access.` : "A renewal payment failed and the grace period has ended. Free plan limits apply until payment succeeds.")
                : sub.status === "cancelled" ? `Cancelled. ${sub.subscribed_plan.name} access continues until ${formatDate(sub.current_period_end)}.`
                : sub.current_period_end ? `Renews on ${formatDate(sub.current_period_end)}.` : sub.subscribed_plan.key === "free" ? "No payment method on file." : "Managed manually."}
            action={isOwner && sub.manageable && (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={portal} loading={busy === "portal"}>Manage card and invoices</Button>
                {sub.cancel_at_period_end ? <Button size="sm" variant="primary" onClick={resume} loading={busy === "resume"}>Keep my subscription</Button>
                  : <Button size="sm" variant="danger" onClick={cancel} loading={busy === "cancel"}>Cancel subscription</Button>}
              </div>)} />
          {sub.plan.key !== sub.subscribed_plan.key && <div className="px-5 pt-4"><Notice tone="warning">Limits currently in force: <span className="font-medium text-ink">{sub.plan.name}</span>.</Notice></div>}
          <div className="border-b border-line px-5 pt-4"><h3 className="pb-3 text-2xs font-semibold uppercase tracking-wider text-ink-faint">Usage against {sub.plan.name} limits</h3></div>
          <ul className="grid gap-5 p-5 sm:grid-cols-2 lg:grid-cols-3">{sub.usage.map((u) => (
            <li key={u.key}><div className="mb-1.5 flex justify-between text-xs"><span className="text-ink-muted">{u.label}</span><span className="num text-ink">{formatNumber(u.used)} / {limit(u.limit)}</span></div>
              <ProgressBar value={u.used} max={u.limit ?? Math.max(u.used, 1) * 4} tone={u.limit !== null && u.used >= u.limit ? "danger" : "primary"} /></li>))}</ul>
        </Card>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-ink">Plans</h2>
        <IntervalToggle value={interval} onChange={setInterval} />
      </div>
      {catalogue && (
        <PlanCards plans={catalogue.plans} interval={interval} currentKey={sub?.subscribed_plan.key} renderAction={(plan) => {
          if (plan.key === sub?.subscribed_plan.key) return <p className="text-center text-xs text-ink-faint">Your current plan</p>;
          if (plan.key === "enterprise") return <p className="text-center text-xs text-ink-muted">Custom terms — contact us.</p>;
          if (plan.key === "free") return <p className="text-center text-xs text-ink-faint">Cancel a paid plan to return to Free.</p>;
          if (!isOwner) return <p className="text-center text-xs text-ink-faint">Only the workspace owner can change plan.</p>;
          if (sub?.manageable) return <p className="text-center text-xs text-ink-faint">Use “Manage card and invoices” to switch plan.</p>;
          return (
            <Button className="w-full" variant={plan.key === (initialPlan ?? "pro") ? "primary" : "secondary"} disabled={!canBuy} onClick={() => choose(plan.key)} loading={busy === plan.key}
              title={canBuy ? undefined : "Card payments are not configured on this instance"}>
              {canBuy ? `Subscribe to ${plan.name}` : "Checkout unavailable"}
            </Button>);
        }} />
      )}
      {catalogue && <p className="text-2xs text-ink-faint">{catalogue.note} Prices in {catalogue.billing.currency}. Failed renewals keep access for {catalogue.billing.grace_days} days.</p>}

      <Card>
        <CardHeader title="Payment history" description="Invoices recorded from the payment provider" />
        {payments?.items.length ? (
          <div className="overflow-x-auto"><table className="w-full"><thead className="bg-surface/60"><tr><Th>Date</Th><Th>Description</Th><Th>Status</Th><Th className="text-right">Amount</Th><Th /></tr></thead>
            <tbody className="divide-y divide-line">{payments.items.map((p) => (
              <tr key={p.id}><Td className="whitespace-nowrap text-xs text-ink-muted">{formatDate(p.paid_at ?? p.created_at)}</Td>
                <Td className="text-ink">{p.description ?? `${p.plan ?? ""} ${p.billing_interval === "year" ? "annual" : p.billing_interval === "month" ? "monthly" : ""}`}</Td>
                <Td><Badge tone={p.status === "succeeded" ? "success" : p.status === "failed" ? "danger" : "warning"}>{p.status.replace("_", " ")}</Badge></Td>
                <Td className="num text-right">{formatMoney(p.amount_minor, p.currency)}{p.refunded_minor > 0 && <span className="block text-2xs text-warning">−{formatMoney(p.refunded_minor, p.currency)} refunded</span>}</Td>
                <Td className="text-right">{p.receipt_url && <a href={p.receipt_url} target="_blank" rel="noopener noreferrer" className="text-xs text-accent hover:underline">Invoice</a>}</Td></tr>))}</tbody></table></div>
        ) : <p className="p-5 text-sm text-ink-muted">No payments have been recorded for this workspace.</p>}
      </Card>
      {!isOwner && <Notice>Only the workspace owner can change the plan.</Notice>}
    </div>
  );
}
