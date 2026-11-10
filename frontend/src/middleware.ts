import { NextResponse, type NextRequest } from "next/server";

/** Reachable without a session. `/` and `/pricing` are marketing pages; the rest are account flows. */
const PUBLIC_EXACT = ["/", "/pricing"];
const AUTH_PAGES = ["/login", "/register", "/forgot-password"];
const TOKEN_PAGES = ["/reset-password", "/verify-email"]; // opened from e-mail links, with or without a session

/**
 * Fast redirects for signed-out and signed-in visitors. This only checks that a session cookie is
 * *present*; the API validates it on every request, so this is a UX convenience, not the security boundary.
 */
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasSession = request.cookies.has("sa_session");
  const isAuthPage = AUTH_PAGES.some((p) => pathname.startsWith(p));
  const isPublic = PUBLIC_EXACT.includes(pathname) || isAuthPage || TOKEN_PAGES.some((p) => pathname.startsWith(p));
  if (!hasSession && !isPublic) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname)}`;
    return NextResponse.redirect(url);
  }
  if (hasSession && (pathname === "/" || (isAuthPage && !request.nextUrl.searchParams.has("error")))) {
    const url = request.nextUrl.clone();
    url.pathname = "/overview";
    url.search = "";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/((?!api|_next/static|_next/image|favicon.ico|icon.svg).*)"] };
