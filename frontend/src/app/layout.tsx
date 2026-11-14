import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "SIGNAL ATLAS", template: "%s · SIGNAL ATLAS" },
  description: "Open-source technology intelligence and commercial opportunity discovery.",
  icons: { icon: "/icon.svg" },
};

export const viewport: Viewport = { themeColor: "#080B14", width: "device-width", initialScale: 1 };

export default async function RootLayout({ children }: { children: ReactNode }) {
  // Reading the request makes every page render per request, which is what lets Next.js stamp the
  // CSP nonce (set in middleware) onto its script tags. Statically prerendered HTML could not carry one.
  await headers();
  return (
    <html lang="en-GB" className={`${GeistSans.variable} ${GeistMono.variable} dark`}>
      <body className="font-sans">{children}</body>
    </html>
  );
}
