import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, buildUrl, errorMessage, setCsrfToken, UPGRADE_EVENT } from "@/lib/api";
import { categoryLabel, formatCompact, formatNumber, scoreTone, timeAgo, titleCase } from "@/lib/utils";
import { normaliseRepoFullName, validateEmail, validatePassword, validateRepoFullName, validateRequired, validateWeights } from "@/lib/validation";
import { layoutGraph, type GraphNode } from "@/components/ecosystem-map";
import { buildCsp } from "@/middleware";
import { mockApi } from "@/test/setup";

describe("formatting", () => {
  it("formats numbers without inventing values for missing data", () => {
    expect(formatNumber(1234567)).toBe("1,234,567");
    expect(formatNumber(null)).toBe("—");
    expect(formatNumber(undefined)).toBe("—");
    expect(formatCompact(950)).toBe("950");
    expect(formatCompact(104603)).toBe("104.6K");
    expect(formatCompact(null)).toBe("—");
  });

  it("describes relative time", () => {
    const now = new Date("2026-11-10T12:00:00Z");
    expect(timeAgo("2026-11-10T11:59:40Z", now)).toBe("just now");
    expect(timeAgo("2026-11-10T09:00:00Z", now)).toBe("3 hours ago");
    expect(timeAgo("2026-11-09T12:00:00Z", now)).toBe("1 day ago");
    expect(timeAgo("2026-08-10T12:00:00Z", now)).toBe("3 months ago");
    expect(timeAgo(null, now)).toBe("never");
  });

  it("maps scores, categories and labels", () => {
    expect([scoreTone(82), scoreTone(55), scoreTone(20), scoreTone(null)]).toEqual(["success", "accent", "warning", "muted"]);
    expect(categoryLabel("ai-ml")).toBe("AI & Machine Learning");
    expect(categoryLabel(null)).toBe("Uncategorised");
    expect(titleCase("commit_acceleration")).toBe("Commit Acceleration");
  });
});

describe("form validation", () => {
  it("validates email addresses", () => {
    expect(validateEmail("")).toMatch(/Enter your email/);
    expect(validateEmail("not-an-email")).toMatch(/valid email/);
    expect(validateEmail(" alice@example.com ")).toBeNull();
  });

  it("mirrors the API password policy", () => {
    expect(validatePassword("Short1")).toMatch(/10 characters/);
    expect(validatePassword("alllowercase1")).toMatch(/upper-case/);
    expect(validatePassword("NoDigitsHereAtAll")).toMatch(/digit/);
    expect(validatePassword("Str0ngPassw0rd!")).toBeNull();
  });

  it("validates repository names and scoring weights", () => {
    expect(validateRepoFullName("vercel/next.js")).toBeNull();
    expect(validateRepoFullName("https://github.com/vercel/next.js/")).toBeNull();
    expect(normaliseRepoFullName("https://github.com/vercel/next.js/")).toBe("vercel/next.js");
    expect(validateRepoFullName("just-a-name")).toMatch(/owner\/repository/);
    expect(validateRepoFullName("a/b; rm -rf")).not.toBeNull();
    expect(validateRequired("  ", "Name")).toBe("Name is required.");
    expect(validateWeights({ a: 60, b: 40 })).toBeNull();
    expect(validateWeights({ a: 60, b: 30 })).toMatch(/sum to 100 \(currently 90\)/);
    expect(validateWeights({ a: 120, b: -20 })).toMatch(/between 0 and 100/);
  });
});

describe("api client", () => {
  beforeEach(() => setCsrfToken(null));

  it("builds query strings and drops empty parameters", () => {
    expect(buildUrl("/repositories", { q: "vector db", category: "", page: 2, min_stars: null, source: "live" })).toBe("/api/v1/repositories?q=vector+db&page=2&source=live");
    expect(buildUrl("/dashboard")).toBe("/api/v1/dashboard");
  });

  it("sends the CSRF token on state-changing requests only, with same-origin credentials", async () => {
    const calls = mockApi({ "/watchlists": { body: { items: [] } } });
    setCsrfToken("csrf-abc");
    await api("/watchlists");
    await api("/watchlists", { method: "POST", body: { name: "Thesis" } });
    expect(calls[0].headers["X-CSRF-Token"]).toBeUndefined();
    expect(calls[1].headers["X-CSRF-Token"]).toBe("csrf-abc");
    expect(calls[1].body).toEqual({ name: "Thesis" });
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1].credentials).toBe("same-origin");
  });

  it("turns API errors into ApiError and raises the upgrade prompt on 402", async () => {
    mockApi({ "/reports/generate": { status: 402, body: { error: { code: "upgrade_required", message: "Limit reached", current_plan: "free", suggested_plan: "pro", limit: 3, used: 3 } } } });
    const listener = vi.fn();
    window.addEventListener(UPGRADE_EVENT, listener);
    await expect(api("/reports/generate", { method: "POST", body: {} })).rejects.toMatchObject({ status: 402, code: "upgrade_required", message: "Limit reached" });
    expect(listener).toHaveBeenCalledTimes(1);
    expect((listener.mock.calls[0][0] as CustomEvent).detail.suggested_plan).toBe("pro");
    window.removeEventListener(UPGRADE_EVENT, listener);
  });

  it("reports network failures and unparseable server errors clearly", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    const networkError = await api("/dashboard").catch((e) => e);
    expect(networkError).toBeInstanceOf(ApiError);
    expect(errorMessage(networkError)).toMatch(/Cannot reach the Signal Atlas API/);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>Bad gateway</html>", { status: 502 })));
    await expect(api("/dashboard")).rejects.toMatchObject({ status: 502, code: "server_unavailable" });
    expect(errorMessage("weird")).toBe("Something went wrong.");
  });
});

describe("content security policy", () => {
  it("allows only nonce-authorised scripts in production and nothing from third-party origins except GitHub avatars", () => {
    const csp = buildCsp("abc123", false);
    const directives = Object.fromEntries(csp.split("; ").map((d) => [d.split(" ")[0], d.split(" ").slice(1)]));
    expect(directives["script-src"]).toEqual(["'self'", "'nonce-abc123'", "'strict-dynamic'"]);
    expect(csp).not.toMatch(/unsafe-eval|\*/);
    expect(directives["style-src"]).toEqual(["'self'", "'unsafe-inline'"]); // documented exception: inline style attributes
    expect(directives["img-src"]).toEqual(["'self'", "data:", "https://avatars.githubusercontent.com"]);
    expect(directives["connect-src"]).toEqual(["'self'"]);
    expect(directives["frame-ancestors"]).toEqual(["'none'"]);
    expect(directives["object-src"]).toEqual(["'none'"]);
    expect(directives["form-action"]).toEqual(["'self'"]);
    expect(directives["base-uri"]).toEqual(["'self'"]);
    expect(buildCsp("n", true)).toContain("'unsafe-eval'"); // development only (React refresh)
  });
});

describe("ecosystem layout", () => {
  it("places every node deterministically on its ring", () => {
    const nodes: GraphNode[] = [
      { id: "tech:llm", type: "technology", label: "LLM" },
      { id: "repo:1", type: "repository", label: "a/one", category: "ai-ml" },
      { id: "repo:2", type: "repository", label: "b/two", category: "fintech" },
      { id: "org:a", type: "company", label: "a" },
      { id: "pkg:npm:react", type: "dependency", label: "react" },
    ];
    const first = layoutGraph(nodes);
    expect(Object.keys(first).sort()).toEqual(nodes.map((n) => n.id).sort());
    expect(layoutGraph([...nodes].reverse())).toEqual(first);
    const radius = (id: string) => Math.hypot(first[id].x / 1.5, first[id].y);
    expect(radius("tech:llm")).toBeLessThan(radius("repo:1"));
    expect(radius("repo:1")).toBeLessThan(radius("org:a"));
  });
});
