/**
 * Browser API client. All requests go to this origin (/api/v1/...), which Next.js proxies to the
 * backend. Authentication is an HttpOnly session cookie; state-changing requests echo the CSRF token.
 * No GitHub or LLM credential is ever present in the browser.
 */

export type ApiErrorDetail = {
  code: string;
  message: string;
  fields?: { field: string; message: string }[];
  feature?: string;
  current_plan?: string;
  suggested_plan?: string | null;
  limit?: number | null;
  used?: number | null;
  retry_at?: string;
};

export class ApiError extends Error {
  status: number;
  code: string;
  detail: ApiErrorDetail;

  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message || "Request failed");
    this.status = status;
    this.code = detail.code || "error";
    this.detail = detail;
  }
}

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

function csrfFromCookie(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)sa_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

export type Params = Record<string, string | number | boolean | null | undefined>;

export function buildUrl(path: string, params?: Params): string {
  const url = `/api/v1${path}`;
  if (!params) return url;
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `${url}${url.includes("?") ? "&" : "?"}${query}` : url;
}

export const UPGRADE_EVENT = "signal-atlas:upgrade-required";

export async function api<T = unknown>(path: string, options: { method?: string; body?: unknown; params?: Params } = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") {
    const token = csrfToken ?? csrfFromCookie();
    if (token) headers["X-CSRF-Token"] = token;
  }
  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.params), {
      method,
      headers,
      credentials: "same-origin",
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch {
    throw new ApiError(0, { code: "network_error", message: "Cannot reach the Signal Atlas API. Check your connection and try again." });
  }
  if (response.status === 204) return undefined as T;
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail: ApiErrorDetail =
      (payload as { error?: ApiErrorDetail } | null)?.error ?? {
        code: response.status >= 500 ? "server_unavailable" : "error",
        message: response.status >= 500 ? "The API is unavailable right now. Please try again shortly." : `Request failed (${response.status})`,
      };
    const error = new ApiError(response.status, detail);
    if (typeof window !== "undefined") {
      if (response.status === 402 && detail.code === "upgrade_required") {
        window.dispatchEvent(new CustomEvent(UPGRADE_EVENT, { detail }));
      }
      const publicPage = /^\/($|pricing|login|register|forgot-password|reset-password|verify-email)/.test(window.location.pathname);
      if (response.status === 401 && !publicPage && !path.startsWith("/auth/login")) {
        window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`);
      }
    }
    throw error;
  }
  return payload as T;
}

export const fetcher = <T,>(path: string) => api<T>(path);

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
