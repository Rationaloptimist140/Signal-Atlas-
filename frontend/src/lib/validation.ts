export function validateEmail(value: string): string | null {
  const email = value.trim();
  if (!email) return "Enter your email address.";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) return "Enter a valid email address.";
  return null;
}

/** Mirrors the API rule: at least 10 characters with an upper-case letter and a digit. */
export function validatePassword(value: string): string | null {
  if (value.length < 10) return "Use at least 10 characters.";
  if (value.toLowerCase() === value) return "Include at least one upper-case letter.";
  if (!/\d/.test(value)) return "Include at least one digit.";
  return null;
}

export function validateRequired(value: string, label: string): string | null {
  return value.trim() ? null : `${label} is required.`;
}

export function validateRepoFullName(value: string): string | null {
  const name = value.trim().replace(/^https?:\/\/github\.com\//i, "").replace(/\/$/, "");
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(name)) return "Use the form owner/repository, e.g. vercel/next.js.";
  return null;
}

export function normaliseRepoFullName(value: string): string {
  return value.trim().replace(/^https?:\/\/github\.com\//i, "").replace(/\/$/, "");
}

export function validateWeights(weights: Record<string, number>): string | null {
  const values = Object.values(weights);
  if (values.some((v) => Number.isNaN(v) || v < 0 || v > 100)) return "Each weight must be between 0 and 100.";
  const total = values.reduce((sum, v) => sum + v, 0);
  if (Math.abs(total - 100) > 0.01) return `Weights must sum to 100 (currently ${total}).`;
  return null;
}
