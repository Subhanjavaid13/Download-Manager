import { Suspense } from "react";

import Downloader from "@/components/downloader";

export default function Home() {
  // Suspense is required because the downloader reads ?url= from the share target.
  return (
    <Suspense fallback={null}>
      <Downloader />
    </Suspense>
  );
}
