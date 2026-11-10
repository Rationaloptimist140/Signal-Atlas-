"use client";

import { Github } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import useSWR from "swr";
import { api, ApiError, errorMessage, fetcher, setCsrfToken } from "@/lib/api";
import type { Me } from "@/lib/types";
import { validateEmail, validatePassword, validateRequired } from "@/lib/validation";
import { Button, Field, Input, Notice } from "@/components/ui";

const OAUTH_ERRORS: Record<string, string> = {
  github_cancelled: "GitHub sign-in was cancelled.",
  github_state_mismatch: "The GitHub sign-in could not be verified. Please try again.",
  github_profile_unavailable: "GitHub did not return a profile. Please try again.",
  github_email_unverified: "Your GitHub account has no verified primary email address.",
  account_exists: "An account with your GitHub email already exists. Sign in with your password, then connect GitHub from Settings.",
  registration_closed: "Registration is currently closed.",
  session_expired: "Your session expired. Please sign in again.",
  account_disabled: "This account is disabled.",
};

type Providers = { github_oauth: boolean; registration_open: boolean; github_scopes: string | null };

function safeNext(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/overview";
}

function GitHubButton({ providers }: { providers: Providers | undefined }) {
  if (!providers) return null;
  if (!providers.github_oauth) {
    return (
      <Notice title="GitHub sign-in needs setup.">
        Set <code className="num">GITHUB_OAUTH_CLIENT_ID</code> and <code className="num">GITHUB_OAUTH_CLIENT_SECRET</code> on the API service to enable it. Email sign-in works without it.
      </Notice>
    );
  }
  return (
    <div>
      <a href="/api/v1/auth/github/start?mode=login" className="flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-line-strong bg-raised text-sm font-medium text-ink hover:bg-[#223049]">
        <Github className="h-4 w-4" />Continue with GitHub
      </a>
      <p className="mt-2 text-center text-2xs text-ink-faint">Requests identity only ({providers.github_scopes}). Never repository write access.</p>
    </div>
  );
}

function Divider() {
  return <div className="my-6 flex items-center gap-3 text-2xs uppercase tracking-wider text-ink-faint"><span className="h-px flex-1 bg-line" />or<span className="h-px flex-1 bg-line" /></div>;
}

export function LoginForm() {
  const params = useSearchParams();
  const { data: providers } = useSWR<Providers>("/auth/providers", fetcher, { revalidateOnFocus: false });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string | null; password?: string | null }>({});
  const [formError, setFormError] = useState<string | null>(OAUTH_ERRORS[params.get("error") ?? ""] ?? null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const next = { email: validateEmail(email), password: validateRequired(password, "Password") };
    setErrors(next);
    if (next.email || next.password) return;
    setBusy(true);
    setFormError(null);
    try {
      const me = await api<Me>("/auth/login", { method: "POST", body: { email: email.trim(), password } });
      setCsrfToken(me.csrf_token);
      window.location.assign(safeNext(params.get("next")));
    } catch (error) {
      setFormError(errorMessage(error));
      setBusy(false);
    }
  }

  return (
    <div>
      <h2 className="text-2xl font-semibold tracking-tight text-ink">Sign in</h2>
      <p className="mt-1.5 text-sm text-ink-muted">Access your intelligence terminal.</p>
      <form onSubmit={onSubmit} noValidate className="mt-8 space-y-4">
        {formError && <Notice tone="danger">{formError}</Notice>}
        <Field label="Email" htmlFor="email" error={errors.email}>
          <Input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={!!errors.email} placeholder="you@company.com" />
        </Field>
        <Field label="Password" htmlFor="password" error={errors.password}>
          <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} aria-invalid={!!errors.password} />
        </Field>
        <p className="-mt-1 text-right text-xs"><Link href="/forgot-password" className="text-primary-bright hover:underline">Forgot password?</Link></p>
        <Button type="submit" variant="primary" size="lg" className="w-full" loading={busy}>Sign in</Button>
      </form>
      <Divider />
      <GitHubButton providers={providers} />
      <p className="mt-8 text-center text-sm text-ink-muted">New to Signal Atlas? <Link href="/register" className="font-medium text-primary-bright hover:underline">Create an account</Link></p>
    </div>
  );
}

export function RegisterForm() {
  const params = useSearchParams();
  const { data: providers } = useSWR<Providers>("/auth/providers", fetcher, { revalidateOnFocus: false });
  const [values, setValues] = useState({ full_name: "", organisation_name: "", email: "", password: "" });
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof values) => (event: { target: { value: string } }) => setValues((v) => ({ ...v, [key]: event.target.value }));

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const next = { full_name: validateRequired(values.full_name, "Your name"), email: validateEmail(values.email), password: validatePassword(values.password) };
    setErrors(next);
    if (Object.values(next).some(Boolean)) return;
    setBusy(true);
    setFormError(null);
    try {
      const me = await api<Me>("/auth/register", { method: "POST", body: { ...values, email: values.email.trim(), organisation_name: values.organisation_name.trim() || null } });
      setCsrfToken(me.csrf_token);
      const plan = params.get("plan");
      const interval = params.get("interval") === "year" ? "year" : "month";
      window.location.assign(plan === "pro" || plan === "business" ? `/settings?tab=billing&plan=${plan}&interval=${interval}` : "/overview");
    } catch (error) {
      if (error instanceof ApiError && error.detail.fields?.length) {
        setErrors(Object.fromEntries(error.detail.fields.map((f) => [f.field, f.message])));
      }
      setFormError(errorMessage(error));
      setBusy(false);
    }
  }

  if (providers && !providers.registration_open) {
    return <Notice tone="warning" title="Registration is closed.">Ask a workspace owner for access, or <Link href="/login" className="underline">sign in</Link>.</Notice>;
  }
  return (
    <div>
      <h2 className="text-2xl font-semibold tracking-tight text-ink">Create your workspace</h2>
      <p className="mt-1.5 text-sm text-ink-muted">Free plan. No card required.</p>
      <form onSubmit={onSubmit} noValidate className="mt-8 space-y-4">
        {formError && <Notice tone="danger">{formError}</Notice>}
        <Field label="Your name" htmlFor="full_name" error={errors.full_name}>
          <Input id="full_name" autoComplete="name" value={values.full_name} onChange={set("full_name")} aria-invalid={!!errors.full_name} />
        </Field>
        <Field label="Organisation (optional)" htmlFor="organisation_name" error={errors.organisation_name}>
          <Input id="organisation_name" autoComplete="organization" value={values.organisation_name} onChange={set("organisation_name")} />
        </Field>
        <Field label="Work email" htmlFor="email" error={errors.email}>
          <Input id="email" type="email" autoComplete="email" value={values.email} onChange={set("email")} aria-invalid={!!errors.email} />
        </Field>
        <Field label="Password" htmlFor="password" error={errors.password} hint="At least 10 characters, with an upper-case letter and a digit.">
          <Input id="password" type="password" autoComplete="new-password" value={values.password} onChange={set("password")} aria-invalid={!!errors.password} />
        </Field>
        <Button type="submit" variant="primary" size="lg" className="w-full" loading={busy}>Create account</Button>
      </form>
      <Divider />
      <GitHubButton providers={providers} />
      <p className="mt-8 text-center text-sm text-ink-muted">Already have an account? <Link href="/login" className="font-medium text-primary-bright hover:underline">Sign in</Link></p>
    </div>
  );
}


export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [result, setResult] = useState<{ message: string; delivery_configured: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const invalid = validateEmail(email);
    setError(invalid);
    if (invalid) return;
    setBusy(true);
    setFormError(null);
    try {
      setResult(await api("/auth/password-reset/request", { method: "POST", body: { email: email.trim() } }));
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h2 className="text-2xl font-semibold tracking-tight text-ink">Reset your password</h2>
      <p className="mt-1.5 text-sm text-ink-muted">Enter your account email and we will send a link that is valid for 30 minutes.</p>
      {result ? (
        <div className="mt-8 space-y-4">
          <Notice tone="success">{result.message}</Notice>
          {!result.delivery_configured && (
            <Notice tone="warning" title="Email delivery is not configured on this instance.">
              No message can be sent until an administrator sets an email provider. In local development the link is written to the API log.
            </Notice>
          )}
        </div>
      ) : (
        <form onSubmit={onSubmit} noValidate className="mt-8 space-y-4">
          {formError && <Notice tone="danger">{formError}</Notice>}
          <Field label="Email" htmlFor="email" error={error}><Input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={!!error} /></Field>
          <Button type="submit" variant="primary" size="lg" className="w-full" loading={busy}>Send reset link</Button>
        </form>
      )}
      <p className="mt-8 text-center text-sm text-ink-muted"><Link href="/login" className="font-medium text-primary-bright hover:underline">Back to sign in</Link></p>
    </div>
  );
}

/** Reads the single-use token from the URL once, then removes it from the address bar and browser history. */
function useUrlToken(): string | null {
  const params = useSearchParams();
  const [token] = useState(() => params.get("token"));
  useEffect(() => {
    if (token && typeof window !== "undefined") window.history.replaceState(null, "", window.location.pathname);
  }, [token]);
  return token;
}

export function ResetPasswordForm() {
  const token = useUrlToken();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<{ password?: string | null; confirm?: string | null }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const next = { password: validatePassword(password), confirm: password === confirm ? null : "Passwords do not match." };
    setErrors(next);
    if (next.password || next.confirm) return;
    setBusy(true);
    setFormError(null);
    try {
      await api("/auth/password-reset/confirm", { method: "POST", body: { token, new_password: password } });
      setCsrfToken(null);
      setDone(true);
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return <div className="space-y-4"><Notice tone="danger" title="This reset link is incomplete.">Request a new one.</Notice><Link href="/forgot-password" className="text-sm font-medium text-primary-bright hover:underline">Request a reset link</Link></div>;
  }
  if (done) {
    return <div className="space-y-4"><Notice tone="success" title="Password updated.">Every existing session was signed out. Sign in with your new password.</Notice><Link href="/login" className="text-sm font-medium text-primary-bright hover:underline">Go to sign in</Link></div>;
  }
  return (
    <div>
      <h2 className="text-2xl font-semibold tracking-tight text-ink">Choose a new password</h2>
      <form onSubmit={onSubmit} noValidate className="mt-8 space-y-4">
        {formError && <Notice tone="danger">{formError} <Link href="/forgot-password" className="underline">Request a new link</Link></Notice>}
        <Field label="New password" htmlFor="new-password" error={errors.password} hint="At least 10 characters, with an upper-case letter and a digit.">
          <Input id="new-password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} aria-invalid={!!errors.password} />
        </Field>
        <Field label="Confirm new password" htmlFor="confirm-password" error={errors.confirm}>
          <Input id="confirm-password" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} aria-invalid={!!errors.confirm} />
        </Field>
        <Button type="submit" variant="primary" size="lg" className="w-full" loading={busy}>Update password</Button>
      </form>
    </div>
  );
}

export function VerifyEmailPanel() {
  const token = useUrlToken();
  const [state, setState] = useState<"working" | "verified" | "failed" | "missing">(token ? "working" : "missing");
  const [message, setMessage] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (!token || started.current) return;
    started.current = true; // the token is single-use: never send it twice (React strict mode runs effects twice)
    api("/auth/verify-email/confirm", { method: "POST", body: { token } })
      .then(() => setState("verified"))
      .catch((err) => { setMessage(errorMessage(err)); setState("failed"); });
  }, [token]);

  return (
    <div className="space-y-5">
      <h2 className="text-2xl font-semibold tracking-tight text-ink">Email verification</h2>
      {state === "working" && <Notice tone="accent">Confirming your email address…</Notice>}
      {state === "verified" && <Notice tone="success" title="Email address confirmed.">Report generation, API keys and live GitHub requests are now available.</Notice>}
      {state === "failed" && <Notice tone="danger" title="This link could not be used.">{message} Sign in and request a new verification email from the banner at the top of the app.</Notice>}
      {state === "missing" && <Notice tone="warning">Open the verification link from your email, or sign in and request a new one.</Notice>}
      <Link href="/overview" className="inline-block text-sm font-medium text-primary-bright hover:underline">Continue to Signal Atlas</Link>
    </div>
  );
}
