"use client";

import { PageHeader } from "@/components/ui";
import HighlightGrid from "@/components/match/HighlightGrid";

export default function HighlightsPage() {
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Highlights" subtitle="The best shot of every analysed match, as an 8-second clip. Every upload and live recording gets one automatically." />
      <HighlightGrid />
    </div>
  );
}
