// Deployed-site acceptance journey: BASE_URL=https://<web domain> node production.mjs
//
// Runs against a real deployment with a fresh account. It asserts only what a deployment can show
// without reading e-mail or paying: steps that need a delivered e-mail (verification, password reset
// completion) or a payment provider (checkout, cancellation) are reported as BLOCKED, never as passed.
// Set EXPECT_EMAIL=1 / EXPECT_BILLING=1 once those providers are configured to turn a missing
// provider into a failure instead.
import { chromium } from "playwright";

const BASE = (process.env.BASE_URL ?? "").replace(/\/$/, "");
if (!BASE.startsWith("https://")) { console.error("BASE_URL must be the https:// address of the deployed web app"); process.exit(2); }
const PASSWORD = `E2e-${Math.random().toString(36).slice(2, 12)}-Passw0rd`;
const stamp = Date.now();
const email = `e2e-prod-${stamp}@example.com`;

const results = [];
const record = (status, step, name, detail = "") => { results.push({ step, name, status }); console.log(`${status.padEnd(7)} ${String(step).padStart(2)}  ${name}${detail ? `  (${detail})` : ""}`); };
const check = (step, name, ok, detail) => record(ok ? "PASS" : "FAIL", step, name, detail);
const blocked = (step, name, why) => record("BLOCKED", step, name, why);

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
const problems = [];
page.on("console", (m) => {
  const text = m.text();
  if (m.type() !== "error") return;
  if (/Content Security Policy|Refused to/i.test(text)) problems.push(`CSP ${page.url()} ${text.slice(0, 200)}`);
  else if (!/status of (40[0-49]|42[39]|503)/.test(text)) problems.push(`console ${page.url()} ${text.slice(0, 200)}`);
});
page.on("pageerror", (e) => problems.push(`pageerror ${page.url()} ${String(e).slice(0, 200)}`));
page.on("dialog", (d) => d.accept());
const apiJson = (p, path, init) => p.evaluate(async ([url, options]) => { const r = await fetch(url, options); return { status: r.status, body: await r.json().catch(() => null), retryAfter: r.headers.get("retry-after") }; }, [`/api/v1${path}`, init]);
const post = (body, csrf) => ({ method: "POST", headers: { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}) }, body: JSON.stringify(body) });
const csrfToken = async () => (await context.cookies()).find((c) => c.name === "sa_csrf")?.value;

try {
  // 1 ─ site, TLS and headers
  const landing = await page.goto(`${BASE}/`);
  await page.waitForSelector("text=Six connected intelligence engines");
  const headers = landing.headers();
  const csp = headers["content-security-policy"] ?? "";
  const nonce = (csp.match(/'nonce-([^']+)'/) ?? [])[1];
  const scriptNonces = await page.$$eval("script", (nodes) => nodes.map((n) => n.nonce || n.getAttribute("nonce")));
  check(1, "landing page opens over HTTPS", landing.status() === 200 && page.url().startsWith("https://"));
  check(1, "nonce-based Content-Security-Policy, no unsafe-eval, framing denied", !!nonce && csp.includes("'strict-dynamic'") && !csp.includes("unsafe-eval") && csp.includes("frame-ancestors 'none'"));
  check(1, "every script tag carries the request's nonce", scriptNonces.length > 0 && scriptNonces.every((n) => n === nonce), `${scriptNonces.length} scripts`);
  check(1, "HSTS, nosniff, frame and referrer headers are present", /max-age=\d+/.test(headers["strict-transport-security"] ?? "") && headers["x-content-type-options"] === "nosniff" && headers["x-frame-options"] === "DENY" && !!headers["referrer-policy"]);

  // 2 ─ pricing
  await page.goto(`${BASE}/pricing`); await page.waitForSelector("text=£19");
  const pricing = await page.locator("body").innerText();
  check(2, "pricing shows Free, Pro £19, Business £49 and Enterprise", /Free/.test(pricing) && /£19/.test(pricing) && /£49/.test(pricing) && /Enterprise/.test(pricing));

  // 3 ─ register
  await page.goto(`${BASE}/register`);
  await page.fill("#full_name", "E2E Production Tester"); await page.fill("#email", email); await page.fill("#password", PASSWORD);
  await page.click('button[type=submit]');
  await page.waitForURL("**/login?registered=1");
  check(3, "registration hands over to sign-in with a neutral message", await page.locator("text=If that email address was not already registered").isVisible());
  check(3, "registration does not create a session", !(await context.cookies()).some((c) => c.name === "sa_session"));
  const again = await apiJson(page, "/auth/register", post({ email, password: "An0therPassw0rd!", full_name: "Impostor" }));
  const fresh = await apiJson(page, "/auth/register", post({ email: `e2e-prod-other-${stamp}@example.com`, password: PASSWORD, full_name: "Other" }));
  check(3, "an existing address gets the same response as a new one (no account probing)", again.status === 202 && fresh.status === 202 && JSON.stringify(again.body) === JSON.stringify(fresh.body));
  const delivery = fresh.body?.delivery_configured === true;

  // 4 ─ wrong password, then sign in
  const wrong = await apiJson(page, "/auth/login", post({ email, password: "definitely-wrong-password" }));
  check(4, "a wrong password is refused with a generic message", wrong.status === 401 && wrong.body?.error?.code === "invalid_credentials");
  await page.fill("#email", email); await page.fill("#password", PASSWORD); await page.click('button[type=submit]');
  await page.waitForURL("**/overview");
  const cookies = await context.cookies();
  const session = cookies.find((c) => c.name === "sa_session");
  check(4, "sign-in succeeds and the session cookie is HttpOnly, Secure, SameSite=Lax", !!session && session.httpOnly && session.secure && session.sameSite === "Lax");
  await page.waitForSelector("text=Verify your email");
  check(4, "an unverified account sees the verification banner", true);

  // 5 ─ e-mail verification
  if (delivery) blocked(5, "e-mail verification link", "a message was sent; opening it needs inbox access, so it is not asserted here");
  else if (process.env.EXPECT_EMAIL) check(5, "e-mail delivery is configured", false, "delivery_configured=false");
  else blocked(5, "e-mail verification", "no e-mail provider is configured on this deployment");

  // 6 ─ the terminal pages load for a signed-in user
  const me = await apiJson(page, "/auth/me");
  check(6, "the account is on the Free plan in its own workspace", me.status === 200 && me.body?.plan?.key === "free" && me.body?.role === "owner");
  for (const [path, marker] of [["/overview", "main"], ["/repositories", "main"], ["/trends", "main"], ["/opportunities", "main"], ["/watchlists", "main"], ["/settings", "main"]]) {
    const response = await page.goto(`${BASE}${path}`); await page.waitForSelector(marker);
    check(6, `${path} renders`, response.status() === 200 && !/Application error|Something went wrong/i.test(await page.locator("body").innerText()));
  }

  // 7 ─ live repository data
  const repos = await apiJson(page, "/repositories?page_size=5");
  const repoItems = repos.body?.items ?? [];
  if (repoItems.length) {
    await page.goto(`${BASE}/repositories`); await page.waitForSelector("table tbody tr");
    await page.locator('table tbody a[href^="/repositories/"]').first().click(); await page.waitForSelector("text=Repository facts");
    check(7, "repository intelligence lists live repositories and opens a profile", true, `${repos.body.total ?? repoItems.length} repositories`);
    check(7, "live repositories are not marked as demonstration data", repoItems.every((r) => r.is_demo !== true));
  } else blocked(7, "repository intelligence with live data", "no repositories have been ingested on this deployment");

  // 8 ─ soft gate: actions that need a verified address are refused, not broken
  const csrf = await csrfToken();
  const noCsrf = await apiJson(page, "/watchlists", post({ name: "No CSRF" }));
  check(8, "a state-changing request without the CSRF token is refused", noCsrf.status === 403);
  const gatedSearch = await apiJson(page, "/repositories/github-search?q=vector+database");
  const gatedKey = await apiJson(page, "/api-keys", post({ name: "E2E key" }, csrf));
  if (me.body?.user?.email_verified === false && me.body?.email?.verification_required) {
    check(8, "live GitHub search is refused until the address is verified", gatedSearch.status === 403 && gatedSearch.body?.error?.code === "email_verification_required", `HTTP ${gatedSearch.status}`);
    check(8, "API key creation is refused for an unverified Free account", gatedKey.status === 403 || gatedKey.status === 402, `HTTP ${gatedKey.status} ${gatedKey.body?.error?.code ?? ""}`);
  }

  // 9 ─ watchlist (allowed on Free without verification)
  const created = await apiJson(page, "/watchlists", post({ name: `E2E watchlist ${stamp}` }, csrf));
  const listed = await apiJson(page, "/watchlists");
  check(9, "a watchlist can be created and is listed", created.status < 300 && JSON.stringify(listed.body).includes(`E2E watchlist ${stamp}`), `HTTP ${created.status}`);

  // 10 ─ billing
  const plans = await apiJson(page, "/billing/plans");
  const subscription = await apiJson(page, "/billing/subscription");
  check(10, "the plan catalogue and the current subscription load", plans.status === 200 && subscription.status === 200 && subscription.body?.plan?.key === "free");
  const checkout = await apiJson(page, "/billing/checkout", post({ plan: "pro", interval: "month" }, csrf));
  if (checkout.status === 200 && /^https:\/\/checkout\.stripe\.com\//.test(checkout.body?.url ?? "")) blocked(10, "hosted checkout", "a Stripe session was created; paying with a test card is done interactively, not in this script");
  else if (process.env.EXPECT_BILLING) check(10, "checkout is available", false, `HTTP ${checkout.status}`);
  else {
    check(10, "checkout fails safely while no payment provider is configured (no plan change)", (checkout.status === 503 && checkout.body?.error?.code === "billing_not_configured") && (await apiJson(page, "/billing/subscription")).body?.plan?.key === "free", `HTTP ${checkout.status} ${checkout.body?.error?.code ?? ""}`);
    blocked(10, "checkout, activation, cancellation and payment history", "no payment provider is configured on this deployment");
  }

  // 11 ─ tenant isolation and unknown routes
  const otherContext = await browser.newContext(); const otherPage = await otherContext.newPage(); await otherPage.goto(`${BASE}/login`);
  const otherLogin = await apiJson(otherPage, "/auth/login", post({ email: `e2e-prod-other-${stamp}@example.com`, password: PASSWORD }));
  const otherCsrf = (await otherContext.cookies()).find((c) => c.name === "sa_csrf")?.value;
  const theirs = await apiJson(otherPage, "/watchlists", post({ name: `Other workspace ${stamp}` }, otherCsrf));
  const theirId = theirs.body?.id;
  const foreignAdd = await apiJson(page, `/watchlists/${theirId}/items`, post({ item_type: "repository", item_id: repoItems[0]?.id ?? 1 }, csrf));
  const foreignDelete = await apiJson(page, `/watchlists/${theirId}`, { method: "DELETE", headers: { "X-CSRF-Token": csrf } });
  const stillThere = await apiJson(otherPage, "/watchlists");
  check(11, "another workspace's watchlist cannot be changed or deleted", otherLogin.status === 200 && !!theirId && foreignAdd.status === 404 && foreignDelete.status === 404 && JSON.stringify(stillThere.body).includes(`Other workspace ${stamp}`) && !JSON.stringify(listed.body).includes("Other workspace"), `add HTTP ${foreignAdd.status}, delete HTTP ${foreignDelete.status}`);
  await otherContext.close();
  const missing = await page.goto(`${BASE}/this-page-does-not-exist`);
  check(11, "an unknown page returns 404 without a stack trace", missing.status() === 404 && !/at \w+ \(|Traceback/.test(await page.locator("body").innerText()));

  // 12 ─ password reset request
  const anon = await browser.newContext(); const anonPage = await anon.newPage(); await anonPage.goto(`${BASE}/forgot-password`);
  const known = await apiJson(anonPage, "/auth/password-reset/request", post({ email }));
  const unknown = await apiJson(anonPage, "/auth/password-reset/request", post({ email: `nobody-${stamp}@example.com` }));
  check(12, "password reset answers identically for known and unknown addresses", known.status === unknown.status && known.status < 300 && JSON.stringify(known.body) === JSON.stringify(unknown.body), `HTTP ${known.status}`);
  blocked(12, "completing a password reset", delivery ? "needs inbox access" : "no e-mail provider is configured on this deployment");

  // 13 ─ brute-force limit on sign-in (uses a throwaway address so the tester is not locked out)
  let limited = null;
  for (let i = 0; i < 30 && !limited; i += 1) {
    const attempt = await apiJson(anonPage, "/auth/login", post({ email: `lockout-${stamp}@example.com`, password: `wrong-${i}` }));
    if (attempt.status === 429) limited = attempt;
  }
  check(13, "repeated failed sign-ins are rate limited with Retry-After", !!limited && Number(limited.retryAfter) > 0, limited ? `Retry-After ${limited.retryAfter}s` : "no 429 in 30 attempts");
  await anon.close();

  // 14 ─ mobile layout
  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, storageState: await context.storageState() });
  const m = await mobile.newPage(); let overflow = 0;
  for (const path of ["/", "/pricing", "/overview", "/repositories", "/trends", "/settings"]) {
    await m.goto(`${BASE}${path}`); await m.waitForLoadState("networkidle");
    if (await m.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)) { overflow += 1; console.log(`        overflow at ${path}`); }
  }
  check(14, "no horizontal overflow at 390px across six pages", overflow === 0);
  await mobile.close();

  // 15 ─ sign out
  const oldCookie = (await context.cookies()).find((c) => c.name === "sa_session")?.value;
  const out = await apiJson(page, "/auth/logout", post({}, csrf));
  await page.goto(`${BASE}/overview`); await page.waitForURL("**/login**");
  check(15, "sign-out works and signed-out visitors are sent to sign-in", out.status < 300);
  await context.addCookies([{ name: "sa_session", value: oldCookie, url: BASE }]);
  const replay = await apiJson(page, "/auth/me");
  check(15, "the old session cookie is rejected after sign-out", replay.status === 401);
} catch (error) {
  check("!", `journey stopped: ${String(error).split("\n")[0]}`, false, page.url());
}

check("–", "no Content-Security-Policy violations or console errors during the journey", problems.length === 0, `${problems.length} problems`);
problems.slice(0, 10).forEach((p) => console.log(`        ${p}`));
await browser.close();
const count = (s) => results.filter((r) => r.status === s).length;
console.log(`\n${count("PASS")} passed, ${count("FAIL")} failed, ${count("BLOCKED")} blocked (provider not configured)  ·  account ${email}`);
process.exit(count("FAIL") ? 1 : 0);
