"use client";

import { BottomDock } from "@/components/bottom-nav";
import { AppHeader } from "@/components/header";
import { Card, Page, SectionLabel, Skeleton } from "@/components/ui";

/**
 * First paint of the home screen, shown while the router hands over the
 * shared link. Same boxes in the same places as the real thing, so nothing
 * jumps when the content arrives.
 */
export function DownloaderSkeleton() {
  return (
    <>
      <Page dock="action">
        <AppHeader asHeading />
        <p className="sr-only">Loading the downloader.</p>
        <Card className="p-3">
          <Skeleton className="mb-1.5 h-3 w-24" />
          <div className="flex gap-2">
            <Skeleton className="h-11 flex-1 rounded-control" />
            <Skeleton className="h-11 w-16 rounded-control" />
          </div>
          <div className="mt-3 min-h-18" />
        </Card>
        <section className="mt-section">
          <SectionLabel>Save as</SectionLabel>
          <Skeleton className="h-15 rounded-card" />
        </section>
        <section className="mt-5">
          <SectionLabel>Quality</SectionLabel>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-12 rounded-control" />
            ))}
          </div>
        </section>
      </Page>
      <BottomDock />
    </>
  );
}
