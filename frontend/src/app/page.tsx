import { Suspense } from "react";

import Downloader from "@/components/downloader";
import { DownloaderSkeleton } from "@/components/downloader-skeleton";

export default function Home() {
  // Suspense is required because the downloader reads the share target
  // (?url=, ?text=) from the query string.
  return (
    <Suspense fallback={<DownloaderSkeleton />}>
      <Downloader />
    </Suspense>
  );
}
