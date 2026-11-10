"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { errorMessage, fetcher } from "@/lib/api";
import type { PlanCatalogue } from "@/lib/types";
import { IntervalToggle, PlanCards, type Interval } from "@/components/pricing";
import { ErrorState, Notice, Skeleton } from "@/components/ui";

const FAQ = [
  ["Can I use Signal Atlas for free?", "Yes. The Free plan includes browsing all intelligence, a small number of reports and live GitHub requests each month, and one monitored competitor."],
  ["How does annual billing work?", "Annual plans are charged once per year at the annual price shown. Monthly plans renew every month. You can cancel at any time and keep access until the end of the period you have paid for."],
  ["What happens if a renewal payment fails?", "Your plan stays active for a short grace period while you update your card. After that the workspace returns to the Free plan's limits; nothing is deleted."],
  ["What does Enterprise include?", "Custom limits, single sign-on and support terms agreed with you. Contact us to discuss."],
];

export default function PricingPage() {
  const [interval, setInterval] = useState<Interval>("month");
  const { data, error, isLoading, mutate } = useSWR<PlanCatalogue>("/billing/plans", fetcher, { revalidateOnFocus: false });

  return (
    <div className="mx-auto max-w-6xl px-5 py-16">
      <div className="text-center">
        <p className="text-2xs font-semibold uppercase tracking-[0.24em] text-primary-bright">Pricing</p>
        <h1 className="mt-4 text-4xl font-semibold tracking-tight text-ink">Plans for every stage of discovery</h1>
        <p className="mx-auto mt-3 max-w-xl text-sm text-ink-muted">Start free. Upgrade when you need more reports, API access or deeper monitoring.</p>
        <div className="mt-8 flex justify-center"><IntervalToggle value={interval} onChange={setInterval} /></div>
      </div>

      <div className="mt-10">
        {error ? <ErrorState message={errorMessage(error)} onRetry={() => mutate()} />
          : isLoading || !data ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-96 rounded-xl" />)}</div>
          : (
            <>
              <PlanCards plans={data.plans} interval={interval} renderAction={(plan) =>
                plan.key === "enterprise"
                  ? <p className="text-center text-xs text-ink-muted">Custom terms — contact us.</p>
                  : <Link href={plan.key === "free" ? "/register" : `/register?plan=${plan.key}&interval=${interval}`}
                      className={plan.key === "pro" ? "flex h-10 items-center justify-center rounded-lg bg-primary text-sm font-medium text-white hover:bg-primary-bright" : "flex h-10 items-center justify-center rounded-lg border border-line-strong bg-raised text-sm font-medium text-ink hover:bg-[#223049]"}>
                      {plan.key === "free" ? "Start free" : `Choose ${plan.name}`}
                    </Link>} />
              <p className="mt-4 text-center text-xs text-ink-faint">{data.note} Prices in GBP.</p>
              {!data.billing.checkout_available && (
                <Notice className="mx-auto mt-6 max-w-2xl" tone="warning" title="Online checkout is not enabled yet.">
                  You can create a free workspace today. Paid plans become purchasable once card payments are configured on this instance.
                </Notice>
              )}
              {data.billing.checkout_available && data.billing.test_mode && (
                <Notice className="mx-auto mt-6 max-w-2xl" tone="accent" title="Test mode.">Checkout currently runs in the payment provider&apos;s test mode: no real money is taken.</Notice>
              )}
            </>
          )}
      </div>

      <div className="mx-auto mt-20 max-w-3xl">
        <h2 className="text-xl font-semibold text-ink">Questions</h2>
        <dl className="mt-6 divide-y divide-line border-y border-line">
          {FAQ.map(([q, a]) => (<div key={q} className="py-5"><dt className="text-sm font-medium text-ink">{q}</dt><dd className="mt-2 text-sm leading-relaxed text-ink-muted">{a}</dd></div>))}
        </dl>
      </div>
    </div>
  );
}
