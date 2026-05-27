"use client";

import { useState } from "react";
import {
  IceCoreNavigator,
  IceCoreDetailPanel,
  CoreMindPulse,
} from "@/components/kb";

export default function KnowledgeBasePage() {
  const [selectedStratum, setSelectedStratum] = useState<string>("themes");
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);

  const handleSelectStratum = (stratum: string) => {
    setSelectedStratum(stratum);
    setSelectedItemId(null); // clear item selection when switching strata
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Knowledge Base</h1>
        <p className="text-sm text-white/50 mt-1">
          Ice core strata — from fresh snow to deep ice
        </p>
      </div>

      {/* Two-column layout */}
      <div className="flex flex-col lg:flex-row gap-6">
        {/* Left column: Navigator + Pulse */}
        <div className="w-full lg:w-72 shrink-0 space-y-0">
          <IceCoreNavigator
            selectedStratum={selectedStratum}
            onSelectStratum={handleSelectStratum}
          />
          <CoreMindPulse />
        </div>

        {/* Right column: Detail Panel */}
        <IceCoreDetailPanel
          selectedStratum={selectedStratum}
          selectedItemId={selectedItemId}
          onSelectItem={setSelectedItemId}
        />
      </div>
    </div>
  );
}
