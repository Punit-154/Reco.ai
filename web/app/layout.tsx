import type { Metadata } from "next";
import Link from "next/link";
import { ShieldAlert } from "lucide-react";
import { Toaster } from "@/components/ui/sonner";

import { DEMO_ACTOR, DEMO_MODE_LABEL } from "@/lib/format";
import "./globals.css";

export const metadata: Metadata = {
  title: "Reco.ai — Finance Ops Console",
  description: "Deterministic reconciliation with AI residue triage (demo)",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-background font-sans antialiased">
        <header className="border-b bg-card">
          <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-2">
            <div className="flex items-center gap-4">
              <span className="text-sm font-semibold tracking-tight">Reco.ai</span>
              <nav className="flex items-center gap-3 text-xs text-muted-foreground">
                <Link href="/" className="hover:text-foreground">
                  Dashboard
                </Link>
                <Link href="/exceptions" className="hover:text-foreground">
                  Exceptions
                </Link>
              </nav>
            </div>
            <div className="flex items-center gap-1 rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-900">
              <ShieldAlert className="size-3" />
              {DEMO_MODE_LABEL}: {DEMO_ACTOR}
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-4">{children}</main>
        <Toaster position="bottom-right" richColors />
      </body>
    </html>
  );
}
