import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SWRConfig } from "swr";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { UPGRADE_EVENT } from "@/lib/api";
import { SessionProvider } from "@/lib/session";
import type { Opportunity, Score, Signal } from "@/lib/types";
import { LoginForm, RegisterForm } from "@/components/auth-forms";
import { BasisTag, ConfidenceBadge, GeneratedByTag, OpportunityCard, ProvenanceBadge, SaveButton, ScoreBreakdown, ScoreRing, SignalCard, UpgradeDialog } from "@/components/intel";
import { AppShell } from "@/components/shell";
import { EmptyState, ErrorState, Pagination, Tabs } from "@/components/ui";
import TrendsPage from "@/app/(app)/trends/page";
import { ME, mockApi, navigationState } from "@/test/setup";

function Providers({ children }: { children: ReactNode }) {
  return <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}><SessionProvider>{children}</SessionProvider></SWRConfig>;
}

const SIGNAL: Signal = {
  id: 7, repository_id: 3, repository_full_name: "acme/rocket", category: "automation", signal_type: "star_surge", time_window: "weekly", strength: 64, confidence: "high",
  title: "acme/rocket gained 1,200 stars in 7 days", summary: "Star count rose 9.1% between two snapshots.", data_source: "live_github", detected_at: new Date().toISOString(),
  evidence: [{ label: "Stars now", value: "14,400", kind: "verified", source_url: "https://github.com/acme/rocket" }, { label: "Growth over the window", value: "+1,200 (+9.1%)", kind: "calculated", source_url: null }],
};

const SCORE: Score = {
  total: 71.4, default_total: 71.4, weights: { development_momentum: 20 }, custom_weights: false, confidence: "medium", confidence_value: 0.58, coverage: 0.9, missing: [],
  data_freshness: { last_synced_at: new Date().toISOString(), age_hours: 1, status: "fresh" }, computed_at: new Date().toISOString(),
  methodology_note: "Scores are heuristics, not predictions.",
  metrics: [
    { key: "development_momentum", label: "Development momentum", score: 82, weight: 20, confidence: 1, explanation: "How actively the project is developed.", missing: [],
      evidence: [{ label: "Commits in the last 4 weeks", value: "120", kind: "verified", source_url: null }] },
    { key: "competitive_positioning", label: "Competitive positioning", score: null, weight: 10, confidence: 0, explanation: "Position relative to tracked peers.", evidence: [],
      missing: ["Only 2 comparable repositories tracked in this category (5 needed)."] },
  ],
};

const OPPORTUNITY: Opportunity = {
  id: 5, repository_id: 3, repository_full_name: "acme/rocket", repository_html_url: null, title: "x", category: "automation", summary: "s", score: 71.4, confidence: "medium",
  risk_level: "low", maturity: "emerging", data_source: "demo_fixture", updated_at: new Date().toISOString(), recommended_action: "investigate", stars: 14400,
  primary_language: "Python", license_spdx: "MIT", metrics: [{ key: "development_momentum", label: "Development momentum", score: 82 }, { key: "commercial_potential", label: "Commercial potential", score: 77 }],
};

describe("provenance and epistemic labels", () => {
  it("always distinguishes demo fixtures from live GitHub data", () => {
    const { rerender } = render(<ProvenanceBadge source="demo_fixture" />);
    expect(screen.getByText("Demo data")).toHaveAttribute("title", expect.stringContaining("Fictional"));
    rerender(<ProvenanceBadge source="live_github" />);
    expect(screen.getByText("Live GitHub")).toBeInTheDocument();
    rerender(<ProvenanceBadge source={null} />);
    expect(screen.queryByText(/Demo data|Live GitHub/)).toBeNull();
  });

  it("labels facts, calculations, interpretations and hypotheses differently", () => {
    render(<><BasisTag basis="verified_fact" /><BasisTag basis="calculated_metric" /><BasisTag basis="interpretation" /><BasisTag basis="hypothesis" /><GeneratedByTag by="ai" /><GeneratedByTag by="rules" /><ConfidenceBadge level="low" /></>);
    for (const label of ["Verified fact", "Calculated", "Interpretation", "Hypothesis", "AI", "Rules", "low confidence"]) expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText("Hypothesis")).toHaveAttribute("title", expect.stringContaining("not validated"));
  });

  it("renders a score ring with an accessible value and a clear not-available state", () => {
    const { rerender } = render(<ScoreRing score={71.4} label="Opportunity score" />);
    expect(screen.getByRole("img", { name: "Opportunity score 71 out of 100" })).toHaveTextContent("71");
    rerender(<ScoreRing score={null} />);
    expect(screen.getByRole("img", { name: "Score not available" })).toHaveTextContent("—");
  });
});

describe("intelligence components", () => {
  it("shows why a signal matters and reveals its evidence on demand", async () => {
    render(<SignalCard signal={SIGNAL} />);
    expect(screen.getByText("Star surge")).toBeInTheDocument();
    expect(screen.getByText(/Why it matters/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Evidence/ })).toHaveAttribute("href", "https://github.com/acme/rocket");
    expect(screen.queryByText("Growth over the window:")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Show evidence \(2\)/ }));
    expect(screen.getByText("Growth over the window:")).toBeInTheDocument();
    expect(screen.getByText("14,400").closest("a")).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("explains each metric, including data that is missing rather than estimated", async () => {
    render(<ScoreBreakdown score={SCORE} />);
    expect(screen.getByText("medium confidence")).toBeInTheDocument();
    expect(screen.getByText("n/a")).toBeInTheDocument(); // unscored metric is not shown as zero
    await userEvent.click(screen.getByRole("button", { name: /Competitive positioning/ }));
    expect(screen.getByText("Missing data")).toBeInTheDocument();
    expect(screen.getByText(/Only 2 comparable repositories/)).toBeInTheDocument();
    expect(screen.getByText("Scores are heuristics, not predictions.")).toBeInTheDocument();
  });

  it("summarises an opportunity with score, risk, provenance and recommended action", () => {
    render(<OpportunityCard opportunity={OPPORTUNITY} />);
    const card = screen.getByRole("link");
    expect(card).toHaveAttribute("href", "/opportunities/5");
    expect(within(card).getByText("acme/rocket")).toBeInTheDocument();
    expect(within(card).getByText("low risk")).toBeInTheDocument();
    expect(within(card).getByText("Demo data")).toBeInTheDocument();
    expect(within(card).getByText("investigate")).toBeInTheDocument();
  });

  it("opens an upgrade prompt when the API reports a plan limit", async () => {
    render(<UpgradeDialog />);
    expect(screen.queryByText("Upgrade to continue")).toBeNull();
    act(() => { window.dispatchEvent(new CustomEvent(UPGRADE_EVENT, { detail: { code: "upgrade_required", message: "Your Free plan includes 3 reports per month.", current_plan: "free", suggested_plan: "pro", limit: 3, used: 3 } })); });
    expect(await screen.findByText("Upgrade to continue")).toBeInTheDocument();
    expect(screen.getByText("Your Free plan includes 3 reports per month.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View plans" })).toHaveAttribute("href", "/settings?tab=billing");
    expect(screen.getByText(/payments are not live/i)).toBeInTheDocument();
  });

  it("saves and removes a repository from the watchlist", async () => {
    let saved: Record<string, unknown> = {};
    const calls = mockApi({
      "/auth/me": { body: ME },
      "/watchlists/saved": () => ({ body: { saved } }),
      "/watchlists/9/items": () => { saved = { "3": { item_row_id: 44, watchlist_id: 9 } }; return { status: 201, body: { id: 44, created: true } }; },
      "/watchlists": { body: { items: [{ id: 9, name: "My watchlist", items: [] }] } },
    });
    render(<Providers><SaveButton itemType="repository" itemId={3} /></Providers>);
    const button = await screen.findByRole("button", { name: "Save" });
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/watchlists")).toBe(true));
    await userEvent.click(button);
    expect(await screen.findByRole("button", { name: "Saved" })).toHaveAttribute("aria-pressed", "true");
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({ item_type: "repository", item_id: 3 });
    expect(post?.headers["X-CSRF-Token"]).toBe("csrf-token-123");
  });
});

describe("ui primitives: loading, empty and error states", () => {
  it("renders empty and error states with a working retry", async () => {
    const retry = vi.fn();
    render(<><EmptyState title="No reports yet" description="Generate one from an opportunity." /><ErrorState message="The API is unavailable." onRetry={retry} /></>);
    expect(screen.getByText("No reports yet")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("The API is unavailable.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("paginates and switches tabs", async () => {
    const onPage = vi.fn();
    const onTab = vi.fn();
    render(<><Pagination page={2} pageSize={25} total={60} onChange={onPage} /><Tabs value="a" onChange={onTab} tabs={[{ value: "a", label: "Overview" }, { value: "b", label: "Releases", count: 4 }]} /></>);
    expect(screen.getByText("26–50 of 60")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(onPage.mock.calls).toEqual([[3], [1]]);
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(screen.getByRole("tab", { name: /Releases/ }));
    expect(onTab).toHaveBeenCalledWith("b");
    const { container } = render(<Pagination page={1} pageSize={25} total={10} onChange={onPage} />);
    expect(container).toBeEmptyDOMElement(); // no controls for a single page
  });

  it("shows loading, then an error with retry, then data on the trends page", async () => {
    let fail = true;
    mockApi({
      "/auth/me": { body: ME },
      "/trends/momentum": { body: { categories: [], developer_activity: { series: [], unit: "", basis: "" }, repository_growth: { series: [], unit: "", cohort_size: 0, has_history: false, basis: "", note: "Needs two days." }, technology_adoption: [], trending_categories: [] } },
      "/trends": () => (fail ? { status: 503, body: { error: { code: "server_unavailable", message: "The API is unavailable right now." } } }
        : { body: { items: [SIGNAL], counts_by_window: { daily: 0, weekly: 1, monthly: 0 }, methodology: "Signals compare dated snapshots." } }),
    });
    render(<Providers><TrendsPage /></Providers>);
    expect(screen.getAllByRole("status").length).toBeGreaterThan(0); // skeleton rows while loading
    expect(await screen.findByText("The API is unavailable right now.")).toBeInTheDocument();
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("acme/rocket gained 1,200 stars in 7 days")).toBeInTheDocument();
    expect(screen.getByText(/Signals compare dated snapshots/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Weekly/ })).toHaveTextContent("1");
  });
});

describe("authentication forms", () => {
  it("validates the login form before calling the API and shows server errors", async () => {
    const calls = mockApi({ "/auth/providers": { body: { github_oauth: false, registration_open: true, github_scopes: null } },
      "/auth/login": { status: 401, body: { error: { code: "invalid_credentials", message: "Invalid email or password." } } } });
    render(<Providers><LoginForm /></Providers>);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByText("Enter your email address.")).toBeInTheDocument();
    expect(screen.getByText("Password is required.")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    await userEvent.type(screen.getByLabelText("Email"), "alice@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Invalid email or password.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ email: "alice@example.com", password: "wrong-password" });
    expect(await screen.findByText(/GitHub sign-in needs setup/)).toBeInTheDocument(); // clearly labelled setup requirement
  });

  it("explains OAuth errors and offers GitHub sign-in with read-only scopes when configured", async () => {
    navigationState.search = new URLSearchParams("error=account_exists");
    mockApi({ "/auth/providers": { body: { github_oauth: true, registration_open: true, github_scopes: "read:user user:email" } } });
    render(<Providers><LoginForm /></Providers>);
    expect(screen.getByText(/already exists. Sign in with your password/)).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /Continue with GitHub/ })).toHaveAttribute("href", "/api/v1/auth/github/start?mode=login");
    expect(screen.getByText(/Never repository write access/)).toBeInTheDocument();
  });

  it("enforces the password policy on registration and maps API field errors", async () => {
    const calls = mockApi({ "/auth/providers": { body: { github_oauth: false, registration_open: true, github_scopes: null } },
      "/auth/register": { status: 409, body: { error: { code: "email_taken", message: "An account with this email already exists." } } } });
    render(<Providers><RegisterForm /></Providers>);
    await userEvent.type(screen.getByLabelText("Your name"), "Alice");
    await userEvent.type(screen.getByLabelText("Work email"), "alice@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "weakpass");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByText("Use at least 10 characters.")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    await userEvent.clear(screen.getByLabelText("Password"));
    await userEvent.type(screen.getByLabelText("Password"), "Str0ngPassw0rd!");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("An account with this email already exists.")).toBeInTheDocument();
  });
});

describe("application shell (responsive behaviour)", () => {
  const dashboard = { summary: {}, summary_definitions: {}, signals: [], top_opportunities: [], setup: {},
    provenance: { mode: "demo", showing: "demo_fixture", live_repositories: 0, demo_repositories: 27, fully_synced_repositories: 27, last_synced_at: null, message: "Showing fictional demonstration fixtures." } };

  it("renders all navigation sections, a demo-data banner, search and notifications", async () => {
    mockApi({ "/auth/me": { body: ME }, "/dashboard": { body: dashboard }, "/notifications": { body: { items: [], unread: 2 } } });
    render(<Providers><AppShell><p>Page body</p></AppShell></Providers>);
    expect(await screen.findByText("Page body")).toBeInTheDocument();
    const nav = screen.getByRole("navigation");
    for (const label of ["Overview", "Explore Technologies", "Repository Intelligence", "Developer Intelligence", "Emerging Trends", "Opportunity Discovery",
      "Competitor Intelligence", "Intelligence Reports", "Watchlists", "API & Developers", "Settings"]) expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByText("Demonstration data")).toBeInTheDocument();
    expect(screen.getByText("Showing fictional demonstration fixtures.")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Global search" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Notifications (2 unread)" })).toBeInTheDocument();
  });

  it("collapses the desktop sidebar and opens the mobile navigation drawer", async () => {
    mockApi({ "/auth/me": { body: ME }, "/dashboard": { body: dashboard }, "/notifications": { body: { items: [], unread: 0 } } });
    render(<Providers><AppShell><p>Page body</p></AppShell></Providers>);
    await screen.findByText("Page body");
    const sidebar = screen.getByLabelText("Main navigation");
    expect(sidebar.className).toContain("lg:w-64");
    expect(sidebar.className).toContain("-translate-x-full"); // hidden off-canvas on small screens
    await userEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(sidebar.className).toContain("lg:w-[68px]");
    expect(window.localStorage.getItem("signal-atlas:sidebar")).toBe("collapsed");
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(sidebar.className).toContain("translate-x-0");
    fireEvent.click(screen.getByRole("button", { name: "Close navigation" }));
    expect(sidebar.className).toContain("-translate-x-full");
  });

  it("switches between live and demo data sources and remembers the choice", async () => {
    const calls = mockApi({ "/auth/me": { body: ME }, "/dashboard": { body: dashboard }, "/notifications": { body: { items: [], unread: 0 } } });
    render(<Providers><AppShell><p>Page body</p></AppShell></Providers>);
    await screen.findByText("Page body");
    await userEvent.click(screen.getByRole("radio", { name: "Live" }));
    expect(screen.getByRole("radio", { name: "Live" })).toHaveAttribute("aria-checked", "true");
    expect(window.localStorage.getItem("signal-atlas:source")).toBe("live");
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/dashboard?source=live")).toBe(true));
  });
});
