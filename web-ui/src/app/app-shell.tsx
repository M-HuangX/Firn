"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/layout/sidebar";
import { Header } from "@/components/layout/header";
import { CommandPalette } from "@/components/layout/command-palette";
import { cn } from "@/lib/utils";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);

  // Theater mode: /analysis/[id] and /accretion/[id] routes — hide header, remove padding, collapse sidebar
  const isTheater = /^\/analysis\/.+/.test(pathname) || /^\/accretion\/.+/.test(pathname);

  // Global Cmd+K / Ctrl+K listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCommandPaletteOpen((prev) => !prev);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  const openCommandPalette = useCallback(() => {
    setCommandPaletteOpen(true);
  }, []);

  return (
    <>
      <Sidebar forceCollapsed={isTheater} />
      <div className="flex-1 flex flex-col min-h-screen lg:min-w-0">
        {!isTheater && <Header onOpenCommandPalette={openCommandPalette} />}
        <main className={cn("flex-1 overflow-y-auto", !isTheater && "p-6")}>
          {children}
        </main>
      </div>
      <CommandPalette
        open={commandPaletteOpen}
        onOpenChange={setCommandPaletteOpen}
      />
    </>
  );
}
