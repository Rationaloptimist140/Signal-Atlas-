import type { Metadata } from "next";
import { Suspense } from "react";
import { VerifyEmailPanel } from "@/components/auth-forms";

export const metadata: Metadata = { title: "Verify email" };

export default function Page() {
  return <Suspense><VerifyEmailPanel /></Suspense>;
}
