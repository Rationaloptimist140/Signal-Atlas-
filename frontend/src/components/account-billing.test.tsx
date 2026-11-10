import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { describe, expect, it, vi } from "vitest";
import PricingPage from "@/app/(marketing)/pricing/page";
import { ForgotPasswordForm, ResetPasswordForm, VerifyEmailPanel } from "@/components/auth-forms";
import { BillingTab } from "@/components/billing-tab";
import { planPrice } from "@/components/pricing";
import { VerifyBanner } from "@/components/shell";
import { SessionProvider } from "@/lib/session";
import type { Plan } from "@/lib/types";
import { formatMoney } from "@/lib/utils";
import { ME, mockApi, navigationState } from "@/test/setup";

function Providers({ children }: { children: ReactNode }) {
  return <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}><SessionProvider>{children}</SessionProvider></SWRConfig>;
}
const Plain = ({ children }: { children: ReactNode }) => <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{children}</SWRConfig>;

const plan = (key: string, name: string, month: number | null, year: number | null, extra: Partial<Plan> = {}): Plan => ({
  key, name, price_gbp_month: month, price_gbp_year: year, purchasable: month !== null && month > 0, tagline: `${name} tagline`, watchlist_items: 10, competitors: 1,
  reports_per_month: 3, live_syncs_per_month: 20, api_keys: 0, api_requests_per_month: 0, api_rate_per_minute: 0, ai_enrichment: false, custom_scoring_weights: false, seats: 1, ...extra,
});
const PLANS = [plan("free", "Free", 0, 0), plan("pro", "Pro", 19, 190, { api_requests_per_month: 10000, ai_enrichment: true }), plan("business", "Business", 49, 490, { custom_scoring_weights: true, ai_enrichment: true }), plan("enterprise", "Enterprise", null, null)];
const billing = (overrides = {}) => ({ provider: "manual", checkout_available: false, webhooks_configured: false, test_mode: null, payments_live: false, self_serve_plan_change: false, currency: "GBP", grace_days: 7, message: "Card payments are not configured on this instance yet, so plans cannot be purchased online.", ...overrides });
const catalogue = (overrides = {}) => ({ plans: PLANS, intervals: ["month", "year"], billing: billing(overrides), note: "Prices are initial and may change." });
const subscription = (overrides = {}, billingOverrides = {}) => ({
  plan: PLANS[0], subscribed_plan: PLANS[0], status: "active", billing_interval: null, provider: "manual", current_period_start: null, current_period_end: null,
  cancel_at_period_end: false, cancelled_at: null, grace_until: null, manageable: false,
  usage: [{ key: "reports", label: "AI reports this month", used: 2, limit: 3 }], billing: billing(billingOverrides), ...overrides,
});

describe("pricing", () => {
  it("computes monthly and annual prices from plan data, never from constants in the page", () => {
    expect(planPrice(PLANS[1], "month")).toEqual({ headline: "£19", suffix: "/ month", note: null });
    expect(planPrice(PLANS[1], "year")).toEqual({ headline: "£190", suffix: "/ year", note: "Save £38 against monthly billing" });
    expect(planPrice(PLANS[3], "year").headline).toBe("Custom");
    expect(planPrice(plan("pro", "Pro", 25, 250), "month").headline).toBe("£25");
    expect([formatMoney(19000), formatMoney(4950, "GBP")]).toEqual(["£190", "£49.50"]);
  });

  it("shows four plans, switches billing interval and is honest when checkout is unavailable", async () => {
    mockApi({ "/billing/plans": { body: catalogue() } });
    render(<Plain><PricingPage /></Plain>);
    expect(await screen.findByText("£19")).toBeInTheDocument();
    for (const name of ["Free", "Pro", "Business", "Enterprise"]) expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    expect(screen.getByText("£49")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Choose Pro" })).toHaveAttribute("href", "/register?plan=pro&interval=month");
    await userEvent.click(screen.getByRole("radio", { name: "Annual" }));
    expect(screen.getByText("£190")).toBeInTheDocument();
    expect(screen.getByText("£490")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Choose Business" })).toHaveAttribute("href", "/register?plan=business&interval=year");
    expect(screen.getByText(/Online checkout is not enabled yet/)).toBeInTheDocument();
  });
});

describe("billing management", () => {
  it("disables checkout and explains the setup requirement when card payments are not configured", async () => {
    mockApi({ "/auth/me": { body: ME }, "/billing/plans": { body: catalogue() }, "/billing/subscription": { body: subscription() }, "/billing/payments": { body: { items: [] } } });
    render(<Providers><BillingTab /></Providers>);
    expect(await screen.findByText("Card payments are not configured.")).toBeInTheDocument();
    expect(screen.getByText(/STRIPE_SECRET_KEY/)).toBeInTheDocument();
    const buttons = await screen.findAllByRole("button", { name: "Checkout unavailable" });
    expect(buttons).toHaveLength(2);
    buttons.forEach((b) => expect(b).toBeDisabled());
    expect(screen.getByText("2 / 3")).toBeInTheDocument(); // real usage counters from the API
    expect(screen.getByText("No payments have been recorded for this workspace.")).toBeInTheDocument();
  });

  it("starts hosted checkout with the selected plan and interval and redirects to the provider", async () => {
    const assign = vi.fn();
    Object.defineProperty(window, "location", { value: { ...window.location, assign, pathname: "/settings", origin: "http://localhost" }, writable: true });
    const calls = mockApi({
      "/auth/me": { body: ME }, "/billing/plans": { body: catalogue({ checkout_available: true, test_mode: true, provider: "stripe", message: "Card checkout runs in Stripe test mode: no real money is taken." }) },
      "/billing/subscription": { body: subscription({}, { checkout_available: true, test_mode: true, provider: "stripe", message: "Card checkout runs in Stripe test mode: no real money is taken." }) },
      "/billing/payments": { body: { items: [] } }, "/billing/checkout": { body: { status: "redirect", checkout_url: "https://checkout.stripe.com/c/pay/cs_test_1", test_mode: true } },
    });
    render(<Providers><BillingTab /></Providers>);
    expect(await screen.findByText("Test mode.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Annual" }));
    await userEvent.click(await screen.findByRole("button", { name: "Subscribe to Business" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://checkout.stripe.com/c/pay/cs_test_1"));
    const post = calls.find((c) => c.method === "POST" && c.url.endsWith("/billing/checkout"));
    expect(post?.body).toEqual({ plan: "business", interval: "year" });
    expect(post?.headers["X-CSRF-Token"]).toBe("csrf-token-123");
  });

  it("shows a paid subscription, payment history and cancellation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const state = { cancelled: false };
    const live = { checkout_available: true, test_mode: true, provider: "stripe" };
    const calls = mockApi({
      "/auth/me": { body: { ...ME, plan: PLANS[1] } }, "/billing/plans": { body: catalogue(live) },
      "/billing/subscription": () => ({ body: subscription({ plan: PLANS[1], subscribed_plan: PLANS[1], status: state.cancelled ? "cancelled" : "active", billing_interval: "year", provider: "stripe",
        current_period_end: "2027-11-10T00:00:00Z", cancel_at_period_end: state.cancelled, manageable: true }, live) }),
      "/billing/payments": { body: { items: [{ id: 1, amount_minor: 19000, refunded_minor: 0, currency: "GBP", status: "succeeded", plan: "pro", billing_interval: "year", description: "Signal Atlas Pro (annual)", receipt_url: "https://invoice.stripe.com/i/test", paid_at: "2026-11-10T00:00:00Z", created_at: "2026-11-10T00:00:00Z" }] } },
      "/billing/cancel": () => { state.cancelled = true; return { body: { status: "cancelled" } }; },
    });
    render(<Providers><BillingTab /></Providers>);
    expect(await screen.findByText("Renews on 10 Nov 2027.")).toBeInTheDocument();
    const row = (await screen.findByText("Signal Atlas Pro (annual)")).closest("tr")!;
    expect(within(row).getByText("£190")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "Invoice" })).toHaveAttribute("href", "https://invoice.stripe.com/i/test");
    await userEvent.click(screen.getByRole("button", { name: "Cancel subscription" }));
    expect(await screen.findByText("Cancels at period end")).toBeInTheDocument();
    expect(screen.getByText(/Pro access continues until 10 Nov 2027/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keep my subscription" })).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/billing/cancel"))).toBe(true);
  });
});

describe("account email flows", () => {
  it("requests a reset link, validates the address and reports missing email configuration", async () => {
    const calls = mockApi({ "/auth/password-reset/request": { status: 202, body: { status: "accepted", message: "If an account exists for that address, a password-reset link has been sent.", delivery_configured: false } } });
    render(<ForgotPasswordForm />);
    await userEvent.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(screen.getByText("Enter your email address.")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    await userEvent.type(screen.getByLabelText("Email"), "alice@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByText(/If an account exists for that address/)).toBeInTheDocument();
    expect(screen.getByText("Email delivery is not configured on this instance.")).toBeInTheDocument();
    expect(calls[0].body).toEqual({ email: "alice@example.com" });
  });

  it("resets the password with the URL token and enforces the password policy", async () => {
    navigationState.search = new URLSearchParams("token=reset-token-abcdefghijklmnopqrstuvwxyz");
    const calls = mockApi({ "/auth/password-reset/confirm": { body: { status: "password_reset" } } });
    render(<ResetPasswordForm />);
    await userEvent.type(screen.getByLabelText("New password"), "weak");
    await userEvent.click(screen.getByRole("button", { name: "Update password" }));
    expect(screen.getByText("Use at least 10 characters.")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("New password"));
    await userEvent.type(screen.getByLabelText("New password"), "Br4ndNewPassw0rd");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "Different0ne");
    await userEvent.click(screen.getByRole("button", { name: "Update password" }));
    expect(screen.getByText("Passwords do not match.")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    await userEvent.clear(screen.getByLabelText("Confirm new password"));
    await userEvent.type(screen.getByLabelText("Confirm new password"), "Br4ndNewPassw0rd");
    await userEvent.click(screen.getByRole("button", { name: "Update password" }));
    expect(await screen.findByText("Password updated.")).toBeInTheDocument();
    expect(calls[0].body).toEqual({ token: "reset-token-abcdefghijklmnopqrstuvwxyz", new_password: "Br4ndNewPassw0rd" });
  });

  it("refuses to show the reset form without a token", () => {
    render(<ResetPasswordForm />);
    expect(screen.getByText("This reset link is incomplete.")).toBeInTheDocument();
    expect(screen.queryByLabelText("New password")).toBeNull();
  });

  it("confirms an email address exactly once and reports an unusable link", async () => {
    navigationState.search = new URLSearchParams("token=verify-token-abcdefghijklmnopqrstuvwxyz");
    const calls = mockApi({ "/auth/verify-email/confirm": { body: { status: "verified" } } });
    const { unmount } = render(<VerifyEmailPanel />);
    expect(await screen.findByText("Email address confirmed.")).toBeInTheDocument();
    expect(calls).toHaveLength(1);
    unmount();
    mockApi({ "/auth/verify-email/confirm": { status: 400, body: { error: { code: "invalid_token", message: "This verification link is invalid, has expired or was already used." } } } });
    render(<VerifyEmailPanel />);
    expect(await screen.findByText("This link could not be used.")).toBeInTheDocument();
  });

  it("shows the verification banner only to unverified users and resends the email", async () => {
    const unverified = { ...ME, user: { ...ME.user, email_verified: false } };
    const calls = mockApi({ "/auth/me": { body: unverified }, "/auth/verify-email/request": { status: 202, body: { status: "not_configured", message: "Email delivery is not configured on this instance, so no message was sent." } } });
    const { unmount } = render(<Providers><VerifyBanner /></Providers>);
    expect(await screen.findByText("Verify your email")).toBeInTheDocument();
    expect(screen.getByText(/Email delivery is not configured on this instance yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Resend verification email" }));
    expect(await screen.findByText("Email delivery is not configured on this instance, so no message was sent.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/auth/verify-email/request"))).toBe(true);
    unmount();
    mockApi({ "/auth/me": { body: ME } });
    render(<Providers><VerifyBanner /></Providers>);
    await waitFor(() => expect(screen.queryByText("Verify your email")).toBeNull());
  });
});
