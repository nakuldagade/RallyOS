"use client";

import type { ReactNode } from "react";
import { api } from "@/lib/api";
import { AuthProvider } from "@/lib/auth";

export default function Providers({ children }: { children: ReactNode }) {
  return <AuthProvider loadMe={() => api.me()}>{children}</AuthProvider>;
}
