"use client";

import { QueryProvider } from "@/providers/query-provider";
import { AuthProvider } from "@/providers/auth-provider";
import { LazyMotion, domMax } from "motion/react";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <QueryProvider>
      <AuthProvider>
        <LazyMotion features={domMax}>
          {children}
        </LazyMotion>
      </AuthProvider>
    </QueryProvider>
  );
}
