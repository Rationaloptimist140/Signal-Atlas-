import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import type { AnchorHTMLAttributes, ReactNode } from "react";
import { afterEach, vi } from "vitest";

export const routerMock = { push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn() };
export const navigationState = { pathname: "/overview", search: new URLSearchParams(), params: {} as Record<string, string> };

vi.mock("next/navigation", () => ({
  useRouter: () => routerMock,
  usePathname: () => navigationState.pathname,
  useSearchParams: () => navigationState.search,
  useParams: () => navigationState.params,
  redirect: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string; children: ReactNode }) => <a href={href} {...rest}>{children}</a>,
}));

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  navigationState.pathname = "/overview";
  navigationState.search = new URLSearchParams();
  window.localStorage.clear();
});

type Route = { status?: number; body?: unknown } | ((url: string, init?: RequestInit) => { status?: number; body?: unknown });

/** Install a fetch mock that answers by path prefix. Returns the list of calls for assertions. */
export function mockApi(routes: Record<string, Route>) {
  const calls: { url: string; method: string; headers: Record<string, string>; body: unknown }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ url, method, headers: (init?.headers ?? {}) as Record<string, string>, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const key = Object.keys(routes).sort((a, b) => b.length - a.length).find((prefix) => url.startsWith(`/api/v1${prefix}`));
    if (!key) return new Response(JSON.stringify({ error: { code: "not_mocked", message: `No mock for ${url}` } }), { status: 404 });
    const route = routes[key];
    const result = typeof route === "function" ? route(url, init) : route;
    const status = result.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(result.body ?? {}), { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

export const ME = {
  user: { id: 1, email: "alice@example.com", full_name: "Alice Owner", job_title: null, has_password: true, created_at: "2026-11-01T00:00:00Z", email_verified: true },
  email: { verification_required: true, delivery_configured: false },
  organisation: { id: 1, name: "Org A", slug: "org-a" },
  role: "owner",
  plan: { key: "free", name: "Free", price_gbp_month: 0, price_gbp_year: 0, purchasable: false, tagline: "", watchlist_items: 10, competitors: 1, reports_per_month: 3, live_syncs_per_month: 20, api_keys: 0,
    api_requests_per_month: 0, api_rate_per_minute: 0, ai_enrichment: false, custom_scoring_weights: false, seats: 1 },
  csrf_token: "csrf-token-123",
  github: { connected: false, login: null, avatar_url: null, scopes: null, oauth_configured: false },
};
