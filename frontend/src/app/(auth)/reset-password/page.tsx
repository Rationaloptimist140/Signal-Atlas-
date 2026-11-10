import type { Metadata } from "next";
import { Suspense } from "react";
import { ResetPasswordForm } from "@/components/auth-forms";

export const metadata: Metadata = { title: "Choose a new password" };

export default function Page() {
  return <Suspense><ResetPasswordForm /></Suspense>;
}
