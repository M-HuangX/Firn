"use client";

import { usePathname } from "next/navigation";

const pageTitles: Record<string, string> = {
  "/": "Overview",
  "/analysis": "Analysis",
  "/kb": "Knowledge Base",
  "/settings": "Settings",
  "/accretion": "Accretion",
  "/login": "Sign In",
};

function getPageTitle(pathname: string): string {
  if (pathname.startsWith("/analysis/")) return "Analysis Detail";
  if (pathname.startsWith("/accretion/")) return "Accretion Theater";
  return pageTitles[pathname] ?? "Firn";
}

interface HeaderProps {
  onOpenCommandPalette: () => void;
}

export function Header({ onOpenCommandPalette }: HeaderProps) {
  const pathname = usePathname();
  const title = getPageTitle(pathname);

  return (
    <header className="h-14 shadow-[0_1px_0_0_var(--color-border)] flex items-center justify-between px-6 bg-background/80 backdrop-blur-md sticky top-0 z-30">
      {/* Left: page title (with left padding on mobile for hamburger) */}
      <h1 className="text-lg font-semibold text-text-primary pl-10 lg:pl-0">
        {title}
      </h1>

      {/* Right: command palette trigger + status */}
      <div className="flex items-center gap-4">
        {/* Cmd+K button */}
        <button
          onClick={onOpenCommandPalette}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border text-text-secondary text-sm hover:text-text-primary hover:border-text-secondary/50 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
          </svg>
          <span className="hidden sm:inline">Search</span>
          <kbd className="hidden sm:inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-background text-xs font-mono text-text-secondary">
            <span className="text-[10px]">&#8984;</span>K
          </kbd>
        </button>

        {/* System status indicator */}
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-positive animate-[pulse-dot_2s_ease-in-out_infinite]" />
          <span className="text-xs text-text-secondary hidden sm:inline">Healthy</span>
        </div>
      </div>
    </header>
  );
}
