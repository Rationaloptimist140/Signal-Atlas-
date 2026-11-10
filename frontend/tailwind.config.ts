import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#080B14",
        surface: "#101626",
        card: "#141C2D",
        raised: "#1A2438",
        line: "rgba(148, 163, 184, 0.14)",
        "line-strong": "rgba(148, 163, 184, 0.26)",
        primary: { DEFAULT: "#8B5CF6", soft: "rgba(139, 92, 246, 0.14)", bright: "#A78BFA" },
        accent: { DEFAULT: "#22D3EE", soft: "rgba(34, 211, 238, 0.12)" },
        success: { DEFAULT: "#10B981", soft: "rgba(16, 185, 129, 0.13)" },
        warning: { DEFAULT: "#F59E0B", soft: "rgba(245, 158, 11, 0.13)" },
        danger: { DEFAULT: "#F43F5E", soft: "rgba(244, 63, 94, 0.13)" },
        ink: { DEFAULT: "#F8FAFC", muted: "#94A3B8", faint: "#64748B" },
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "Inter", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "monospace"],
      },
      fontSize: { "2xs": ["0.6875rem", { lineHeight: "1rem" }] },
      boxShadow: {
        card: "0 1px 0 rgba(255,255,255,0.03) inset, 0 8px 24px -12px rgba(0,0,0,0.6)",
        glow: "0 0 0 1px rgba(139,92,246,0.35), 0 0 28px -6px rgba(139,92,246,0.45)",
      },
      keyframes: {
        "fade-in": { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        pulseDot: { "0%, 100%": { opacity: "1" }, "50%": { opacity: "0.35" } },
      },
      animation: { "fade-in": "fade-in 180ms ease-out", "pulse-dot": "pulseDot 2s ease-in-out infinite" },
    },
  },
  plugins: [],
};

export default config;
