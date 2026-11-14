// End-to-end acceptance journey for Signal Atlas (see e2e/README.md for how to start the stack).
//
//   BASE_URL      web app (default http://localhost:3000)
//   API_LOG       file the API writes its output to; development mode prints e-mail links there
//   STUB_URL      local Stripe stub (default http://localhost:4242); set STUB_URL=off to skip billing steps
//
// E-mail links come from the API's development log and payments from the local stub, so this run
// verifies the application, not Resend or Stripe themselves.
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const API_LOG = process.env.API_LOG ?? "/tmp/sa_api.log";
const STUB = process.env.STUB_URL ?? "http://localhost:4242";
const BILLING = STUB !== "off";
const PASSWORD = "E2eTestPassw0rd";
const NEW_PASSWORD = "N3wE2ePassword!";
const stamp = Date.now();
const email = `e2e-${stamp}@example.com`;

const results = [];
const check = (step, name, ok, detail = "") => { results.push({ step, name, ok }); console.log(`${ok ? "PASS" : "FAIL"}  ${String(step).padStart(2)}  ${name}${detail ? `  (${detail})` : ""}`); };
const mailLink = (kind, to = email) => {
  const lines = fs.readFileSync(API_LOG, "utf8").split("\n").filter((l) => l.includes(`[dev-mail] ${kind} for ${to}`));
  if (!lines.length) throw new Error(`no ${kind} link for ${to} in ${API_LOG} (is the API running in development mode?)`);
  return lines.at(-1).split(": ").at(-1).trim();
};
const stub = (path) => fetch(`${STUB}${path}`, { method: "POST" }).then((r) => r.json());

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
const signIn = async (p, address, password) => { await p.goto(`${BASE}/login`); await p.fill("#email", address); await p.fill("#password", password); await p.click('button[type=submit]'); };
const apiJson = (p, path, init) => p.evaluate(async ([url, options]) => { const r = await fetch(url, options); return { status: r.status, body: await r.json().catch(() => null) }; }, [`/api/v1${path}`, init]);

try {
  // 1 ─ open the site
  const landing = await page.goto(`${BASE}/`);
  await page.waitForSelector("text=Six connected intelligence engines");
  const csp = landing.headers()["content-security-policy"] ?? "";
  const nonce = (csp.match(/'nonce-([^']+)'/) ?? [])[1];
  const scriptNonces = await page.$$eval("script", (nodes) => nodes.map((n) => n.nonce || n.getAttribute("nonce")));
  check(1, "landing page opens", true);
  check(1, "page is served with a nonce-based Content-Security-Policy", !!nonce && csp.includes("'strict-dynamic'") && !csp.includes("unsafe-eval") && csp.includes("frame-ancestors 'none'"));
  check(1, "every script tag carries the request's nonce", scriptNonces.length > 0 && scriptNonces.every((n) => n === nonce), `${scriptNonces.length} scripts`);

  // 2 ─ register
  await page.goto(`${BASE}/register`);
  await page.fill("#full_name", "E2E Tester"); await page.fill("#email", email); await page.fill("#password", PASSWORD);
  await page.click('button[type=submit]');
  await page.waitForURL("**/login?registered=1");
  await page.waitForSelector("text=If that email address was not already registered");
  const cookiesAfterSignup = await context.cookies();
  check(2, "registration hands over to sign-in with a neutral message", true);
  check(2, "registration does not create a session", !cookiesAfterSignup.some((c) => c.name === "sa_session"));
  const again = await apiJson(page, "/auth/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password: "An0therPassw0rd", full_name: "Impostor" }) });
  const fresh = await apiJson(page, "/auth/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: `e2e-other-${stamp}@example.com`, password: PASSWORD, full_name: "Other" }) });
  check(2, "registering an existing address returns the same response as a new one", again.status === 202 && fresh.status === 202 && JSON.stringify(again.body) === JSON.stringify(fresh.body));

  // 3 ─ verification e-mail (development link)
  const verifyLink = mailLink("verify_email");
  check(3, "verification link is issued with the token in the URL fragment", verifyLink.includes("/verify-email#token=") && !verifyLink.includes("?"));

  // 5 ─ sign in before verifying (soft gate)
  await page.fill("#password", PASSWORD); await page.click('button[type=submit]');
  await page.waitForURL("**/overview");
  await page.waitForSelector("text=Verify your email");
  check(5, "an unverified account can sign in and sees the verification banner", true);

  // 6 ─ repository intelligence
  await page.goto(`${BASE}/repositories`); await page.waitForSelector("table tbody tr");
  const repoRows = await page.locator("table tbody tr").count();
  await page.locator('table tbody a[href^="/repositories/"]').first().click(); await page.waitForSelector("text=Repository facts");
  check(6, "repository intelligence lists repositories and opens a profile", repoRows > 0, `${repoRows} rows`);

  // 7 ─ emerging technology
  await page.goto(`${BASE}/trends`); await page.waitForSelector("article");
  const signals = await page.locator("article").count();
  await page.locator("article button", { hasText: "Show evidence" }).first().click();
  check(7, "emerging trends show signals with evidence", signals > 0 && await page.locator("article ul li").first().isVisible(), `${signals} signals`);

  // 8/9 ─ opportunity report: blocked until verified
  await page.goto(`${BASE}/opportunities`); await page.locator('a[href^="/opportunities/"]').first().click(); await page.waitForSelector("text=Market opportunity");
  await page.getByRole("button", { name: "Generate intelligence report" }).click();
  await page.waitForSelector("text=Verify your email address to use this feature.");
  check(9, "report generation is refused for an unverified account", true);

  // 4 ─ verify
  await page.goto(verifyLink); await page.waitForSelector("text=Email address confirmed.");
  check(4, "the verification link confirms the address and the token leaves the address bar", !page.url().includes("token="));
  await page.goto(`${BASE}/pricing`); await page.goto(verifyLink); await page.waitForSelector("text=This link could not be used.");
  check(4, "the verification link works only once", true);

  // 8 ─ opportunity report
  await page.goto(`${BASE}/opportunities`); await page.locator('a[href^="/opportunities/"]').first().click(); await page.waitForSelector("text=Market opportunity");
  await page.getByRole("button", { name: "Generate intelligence report" }).click();
  await page.waitForURL("**/reports/*"); await page.waitForSelector("text=Verified facts"); await page.waitForSelector("text=Unverified hypotheses");
  check(8, "a verified account generates an opportunity report", true);

  // 9 ─ premium action on the Free plan
  await page.goto(`${BASE}/api-developers`); await page.getByRole("button", { name: "Create API key" }).first().click();
  await page.fill("#key-name", "E2E key"); await page.getByRole("button", { name: "Create key" }).click();
  await page.waitForSelector("text=Upgrade to continue");
  check(9, "a Free workspace is refused API keys and shown an upgrade prompt", true);
  await page.keyboard.press("Escape");

  if (BILLING) {
    // 10 ─ cancelled checkout, then a completed one
    await page.goto(`${BASE}/settings?tab=billing`); await page.waitForSelector("text=Test mode.");
    await page.getByRole("button", { name: "Subscribe to Pro" }).click();
    await page.waitForURL(`${STUB}/pay/*`); await page.click("#cancel");
    await page.waitForURL("**/settings?tab=billing&checkout=cancelled"); await page.waitForSelector("text=No charge was made");
    await page.getByRole("button", { name: "Subscribe to Pro" }).waitFor();
    const afterCancel = await apiJson(page, "/billing/subscription");
    check(10, "a cancelled checkout returns with no charge and the Free plan unchanged", afterCancel.body.plan.key === "free" && afterCancel.body.status === "active");
    await page.getByRole("button", { name: "Subscribe to Pro" }).click();
    await page.waitForURL(`${STUB}/pay/*`);
    const item = await page.textContent("#item");
    await page.click("#pay");
    await page.waitForURL("**/settings?tab=billing&checkout=success**");
    check(10, "hosted checkout is started with the catalogue price and returns to the app", /Signal Atlas Pro \(monthly\).*19\.00 GBP/.test(item ?? ""), (item ?? "").trim());

    // 11 ─ activation
    await page.waitForSelector("text=Renews on");
    check(11, "the subscription shows as Pro, active and monthly", await page.locator("h2", { hasText: "Pro plan" }).isVisible() && await page.getByText("Active", { exact: true }).isVisible() && await page.getByText("Monthly", { exact: true }).first().isVisible());
    await page.waitForSelector("text=Signal Atlas Pro (monthly)");
    check(11, "the payment appears in payment history", await page.locator("tr", { hasText: "Signal Atlas Pro (monthly)" }).locator("text=£19").isVisible());

    // 12 ─ premium entitlement
    await page.goto(`${BASE}/api-developers`); await page.getByRole("button", { name: "Create API key" }).first().click();
    await page.fill("#key-name", "E2E key"); await page.getByRole("button", { name: "Create key" }).click();
    await page.waitForSelector("text=Copy it now");
    const key = (await page.locator("code", { hasText: "sa_live_" }).first().textContent())?.trim();
    const viaKey = await fetch(`${BASE}/api/v1/opportunities?page_size=1`, { headers: { "X-API-Key": key } });
    check(12, "the paid plan unlocks API keys and the key authenticates", viaKey.status === 200);

    // 14 ─ failed renewal and recovery
    await stub("/_stub/fail_renewal"); await page.goto(`${BASE}/settings?tab=billing`); await page.waitForSelector("text=Payment failed");
    check(14, "a failed renewal shows as payment failed while access continues in the grace period", await page.locator("text=A renewal payment failed. Update your card before").isVisible());
    await stub("/_stub/pay_renewal"); await page.reload(); await page.waitForSelector("text=Renews on");
    check(14, "a successful retry returns the subscription to active", true);

    // 13/14 ─ cancel
    await page.getByRole("button", { name: "Cancel subscription" }).click();
    await page.waitForSelector("text=Cancels at period end");
    check(13, "cancelling keeps access until the end of the paid period", await page.locator("text=Pro access continues until").isVisible() && await page.getByRole("button", { name: "Keep my subscription" }).isVisible());
    const state = await apiJson(page, "/billing/subscription");
    check(14, "the API reports status cancelled with Pro limits still in force", state.body.status === "cancelled" && state.body.plan.key === "pro" && state.body.cancel_at_period_end === true);
  }

  // 16 ─ sign out and session revocation
  const sessionCookie = (await context.cookies()).find((c) => c.name === "sa_session");
  await page.goto(`${BASE}/settings`); await page.getByRole("button", { name: "Account menu" }).click(); await page.click("text=Sign out"); await page.waitForURL("**/login");
  const replay = await fetch(`${BASE}/api/v1/auth/me`, { headers: { Cookie: `sa_session=${sessionCookie.value}` } });
  check(16, "after sign-out the old session cookie is rejected by the API", replay.status === 401);
  await page.goto(`${BASE}/overview`); await page.waitForURL("**/login?next=%2Foverview");
  check(16, "signed-out visitors are sent to sign-in", true);

  // 15 ─ password recovery (with a second signed-in device that must be signed out by the reset)
  const other = await browser.newContext(); const otherPage = await other.newPage();
  await signIn(otherPage, email, PASSWORD); await otherPage.waitForURL("**/overview");
  await page.goto(`${BASE}/login`); await page.click("text=Forgot password?"); await page.waitForURL("**/forgot-password");
  await page.fill("#email", email); await page.click('button[type=submit]'); await page.waitForSelector("text=If an account exists for that address");
  const resetLink = mailLink("password_reset");
  await page.goto(resetLink); await page.waitForSelector("text=Choose a new password");
  await page.fill("#new-password", NEW_PASSWORD); await page.fill("#confirm-password", NEW_PASSWORD); await page.click('button[type=submit]');
  await page.waitForSelector("text=Password updated.");
  check(15, "the reset link sets a new password", resetLink.includes("/reset-password#token="));
  const otherMe = await apiJson(otherPage, "/auth/me");
  check(15, "the reset signs out sessions on other devices", otherMe.status === 401);
  await signIn(page, email, PASSWORD); await page.waitForSelector("text=Invalid email or password.");
  await page.fill("#password", NEW_PASSWORD); await page.click('button[type=submit]'); await page.waitForURL("**/overview");
  check(15, "the old password is rejected and the new one signs in", true);
  await other.close();

  if (BILLING) {
    // 11b ─ activation without any webhook: the return from checkout confirms the session with the provider
    await stub("/_stub/webhooks/off");
    const second = await browser.newContext(); const p2 = await second.newPage(); p2.on("dialog", (d) => d.accept());
    const email2 = `e2e-nowebhook-${stamp}@example.com`;
    await p2.goto(`${BASE}/register`); await p2.fill("#full_name", "No Webhook"); await p2.fill("#email", email2); await p2.fill("#password", PASSWORD); await p2.click('button[type=submit]');
    await p2.waitForURL("**/login?registered=1"); await p2.fill("#password", PASSWORD); await p2.click('button[type=submit]'); await p2.waitForURL("**/overview");
    await p2.goto(`${BASE}/settings?tab=billing`); await p2.getByRole("radio", { name: "Annual" }).click(); await p2.getByRole("button", { name: "Subscribe to Business" }).click();
    await p2.waitForURL(`${STUB}/pay/*`); await p2.click("#pay"); await p2.waitForURL("**/settings?tab=billing&checkout=success**");
    await p2.waitForSelector("text=Renews on");
    check(11, "with webhooks unavailable, returning from checkout still activates the plan (Business, annual)", await p2.locator("h2", { hasText: "Business plan" }).isVisible() && await p2.getByText("Annual", { exact: true }).first().isVisible());
    await stub("/_stub/webhooks/on"); await second.close();
  }

  // layout at phone width
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 } }); const mobile = await phone.newPage();
  await signIn(mobile, email, NEW_PASSWORD); await mobile.waitForURL("**/overview");
  let overflow = 0;
  for (const path of ["/overview", "/repositories", "/opportunities", "/trends", "/settings?tab=billing", "/pricing"]) {
    await mobile.goto(`${BASE}${path}`); await mobile.waitForTimeout(1200);
    overflow += await mobile.evaluate(() => Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth));
  }
  check("–", "no horizontal overflow at 390px across six pages", overflow === 0);
  const status = await apiJson(mobile, "/system/status");
  if (status.status === 200) console.log(`INFO  client address as seen by the API: ${status.body.client_ip_as_seen} (${status.body.forwarded_for_entries} X-Forwarded-For entries), limiter: ${status.body.rate_limiting.backend}`);
  await phone.close();
} catch (error) {
  check("!", `journey stopped: ${String(error).split("\n")[0]}`, false, page.url());
}

check("–", "no Content-Security-Policy violations or console errors during the journey", problems.length === 0, `${problems.length} problems`);
problems.slice(0, 10).forEach((p) => console.log("   ", p));
await browser.close();
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed} of ${results.length} checks passed.`);
process.exit(failed ? 1 : 0);
