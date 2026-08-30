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
        <header className="sticky top-0 z-40 border-b bg-card/80 backdrop-blur-md">
          <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
            <div className="flex items-center gap-6">
              <span className="text-base font-bold tracking-tight text-primary">
                Reco.ai
              </span>
              <nav className="flex items-center gap-1">
                <Link
                  href="/"
                  className="rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  Dashboard
                </Link>
                <Link
                  href="/exceptions"
                  className="rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  Exceptions
                </Link>
              </nav>
            </div>
            <div className="flex items-center gap-1.5 rounded-md border border-amber-300/60 bg-amber-50 px-2.5 py-1 text-[11px] font-medium text-amber-800">
              <ShieldAlert className="size-3.5" />
              {DEMO_MODE_LABEL}
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-6 py-6">{children}</main>
        <Toaster position="bottom-right" richColors />
      </body>
    </html>
  );
}
