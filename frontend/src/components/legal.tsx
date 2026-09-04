import Link from "next/link";
import type { ReactNode } from "react";

import { BottomDock } from "@/components/bottom-nav";
import { AppHeader } from "@/components/header";
import { Page, SiteFooter } from "@/components/ui";

/** The date all three legal pages were last written. Change it when you edit them. */
export const LEGAL_UPDATED = "4 September 2026";

/**
 * Something the operator of this instance has to fill in before publishing.
 * Marked rather than invented: a made-up company name or address in a legal
 * document is worse than an obvious blank.
 */
export function Fill({ children }: { children: ReactNode }) {
  return (
    <mark className="rounded bg-amber-soft px-1 py-0.5 font-medium text-amber">
      [{children}]
    </mark>
  );
}

export function LegalHeading({ children }: { children: ReactNode }) {
  return <h2 className="mt-6 text-title text-ink">{children}</h2>;
}

export function LegalPage({
  title,
  intro,
  children,
}: {
  title: string;
  intro: string;
  children: ReactNode;
}) {
  return (
    <>
      <Page>
        <AppHeader />
        <h1 className="font-display text-display">{title}</h1>
        <p className="mt-1 text-sm text-muted">
          Last updated {LEGAL_UPDATED}. {intro}
        </p>

        <div className="mt-2 text-sm leading-relaxed text-ink-2 [&_a]:text-accent [&_a]:underline-offset-2 hover:[&_a]:underline [&_li]:mt-1 [&_p]:mt-3 [&_ul]:mt-2 [&_ul]:list-disc [&_ul]:pl-5">
          {children}
        </div>

        <p className="mt-8 text-xs text-muted">
          Nothing on this page is legal advice. If this app is used by anyone other than the person
          running it, the operator should have a lawyer read these words first.
        </p>

        <nav className="mt-6 flex flex-wrap gap-x-4 gap-y-1 text-sm">
          <Link href="/terms" className="text-accent underline-offset-2 hover:underline">
            Terms of Service
          </Link>
          <Link href="/privacy" className="text-accent underline-offset-2 hover:underline">
            Privacy Policy
          </Link>
          <Link href="/dmca" className="text-accent underline-offset-2 hover:underline">
            Copyright and contact
          </Link>
        </nav>

        <SiteFooter className="mt-8" />
      </Page>
      <BottomDock />
    </>
  );
}
