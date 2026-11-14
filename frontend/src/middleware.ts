import { NextResponse, type NextRequest } from "next/server";

/** Reachable without a session. `/` and `/pricing` are marketing pages; the rest are account flows. */
const PUBLIC_EXACT = ["/", "/pricing"];
const AUTH_PAGES = ["/login", "/register", "/forgot-password"];
const TOKEN_PAGES = ["/reset-password", "/verify-email"]; // opened from e-mail links, with or without a session

/**
 * Content-Security-Policy for every page.
 *
 * - Scripts: only this origin's bundles, authorised per request by a nonce ('strict-dynamic' lets those
 *   bundles load their own chunks). No inline or eval'd script in production.
 * - Styles: 'unsafe-inline' is required because React, Recharts and React Flow position elements with
 *   inline style attributes. Inline styles cannot run script; this is the one documented exception.
 * - Images: this origin, data: URIs (inline SVG icons) and GitHub's avatar CDN.
 * - Everything else (API calls, fonts, forms) is same-origin; framing and plugins are disallowed.
 */
export function buildCsp(nonce: string, dev = process.env.NODE_ENV !== "production"): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https://avatars.githubusercontent.com",
    "font-src 'self'",
    `connect-src 'self'${dev ? " ws:" : ""}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

/**
 * Sets the CSP and performs fast redirects for signed-out and signed-in visitors. The redirect only
 * checks that a session cookie is *present*; the API validates it on every request, so it is a UX
 * convenience, not the security boundary.
 */
export function middleware(request: NextRequest) {
  const nonce = btoa(crypto.randomUUID());
  const csp = buildCsp(nonce);
  const { pathname } = request.nextUrl;
  const hasSession = request.cookies.has("sa_session");
  const isAuthPage = AUTH_PAGES.some((p) => pathname.startsWith(p));
  const isPublic = PUBLIC_EXACT.includes(pathname) || isAuthPage || TOKEN_PAGES.some((p) => pathname.startsWith(p));

  let response: NextResponse;
  if (!hasSession && !isPublic) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname)}`;
    response = NextResponse.redirect(url);
  } else if (hasSession && (pathname === "/" || (isAuthPage && !request.nextUrl.searchParams.has("error")))) {
    const url = request.nextUrl.clone();
    url.pathname = "/overview";
    url.search = "";
    response = NextResponse.redirect(url);
  } else {
    // Next.js reads the nonce from the request's CSP header and applies it to the scripts it renders.
    const headers = new Headers(request.headers);
    headers.set("x-nonce", nonce);
    headers.set("Content-Security-Policy", csp);
    response = NextResponse.next({ request: { headers } });
  }
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = { matcher: ["/((?!api|_next/static|_next/image|favicon.ico|icon.svg).*)"] };
