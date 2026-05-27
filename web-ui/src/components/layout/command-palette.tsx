"use client";

import { useEffect, useState, useCallback } from "react";
import { Command } from "cmdk";
import { useRouter } from "next/navigation";

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const router = useRouter();
  const [search, setSearch] = useState("");

  // Close on escape
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onOpenChange(false);
      }
    };
    if (open) {
      document.addEventListener("keydown", handleKeyDown);
      return () => document.removeEventListener("keydown", handleKeyDown);
    }
  }, [open, onOpenChange]);

  const runAction = useCallback(
    (action: () => void) => {
      action();
      onOpenChange(false);
      setSearch("");
    },
    [onOpenChange]
  );

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={() => onOpenChange(false)}
      />

      {/* Command dialog */}
      <div className="relative w-full max-w-lg mx-4">
        <Command
          className="rounded-xl border border-border bg-surface shadow-2xl overflow-hidden"
          shouldFilter={true}
        >
          <div className="flex items-center border-b border-border px-4">
            <svg className="w-4 h-4 text-text-secondary mr-2 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
            </svg>
            <Command.Input
              value={search}
              onValueChange={setSearch}
              placeholder="Search tickers, pages, actions..."
              className="flex-1 h-12 bg-transparent text-text-primary placeholder:text-text-secondary outline-none text-sm"
            />
          </div>

          <Command.List className="max-h-80 overflow-y-auto p-2">
            <Command.Empty className="py-6 text-center text-sm text-text-secondary">
              No results found.
            </Command.Empty>

            <Command.Group heading="Navigation" className="[&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:text-text-secondary [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
              <Command.Item
                onSelect={() => runAction(() => router.push("/"))}
                className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-text-primary cursor-pointer data-[selected=true]:bg-accent/10 data-[selected=true]:text-accent"
              >
                Go to Overview
              </Command.Item>
              <Command.Item
                onSelect={() => runAction(() => router.push("/analysis"))}
                className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-text-primary cursor-pointer data-[selected=true]:bg-accent/10 data-[selected=true]:text-accent"
              >
                Go to Analysis
              </Command.Item>
              <Command.Item
                onSelect={() => runAction(() => router.push("/kb"))}
                className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-text-primary cursor-pointer data-[selected=true]:bg-accent/10 data-[selected=true]:text-accent"
              >
                Go to Knowledge Base
              </Command.Item>
              <Command.Item
                onSelect={() => runAction(() => router.push("/accretion"))}
                className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-text-primary cursor-pointer data-[selected=true]:bg-accent/10 data-[selected=true]:text-accent"
              >
                Go to Accretion
              </Command.Item>
              <Command.Item
                onSelect={() => runAction(() => router.push("/settings"))}
                className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-text-primary cursor-pointer data-[selected=true]:bg-accent/10 data-[selected=true]:text-accent"
              >
                Go to Settings
              </Command.Item>
            </Command.Group>

            <Command.Separator className="h-px bg-border my-2" />

            <Command.Group heading="Actions" className="[&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:text-text-secondary [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
              <Command.Item
                onSelect={() =>
                  runAction(() => {
                    const ticker = search.trim().toUpperCase();
                    if (ticker) {
                      router.push(`/analysis?run=${ticker}`);
                    }
                  })
                }
                className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-text-primary cursor-pointer data-[selected=true]:bg-accent/10 data-[selected=true]:text-accent"
              >
                Analyze {search.trim().toUpperCase() || "[ticker]"}
              </Command.Item>
            </Command.Group>
          </Command.List>
        </Command>
      </div>
    </div>
  );
}
