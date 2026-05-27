"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";
import { FirnLogo } from "./firn-logo";

const STORAGE_KEY = "firn-sidebar-collapsed";

const mainNavItems = [
  {
    href: "/",
    label: "Overview",
    icon: (
      <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25a2.25 2.25 0 0 1-2.25-2.25v-2.25Z" />
      </svg>
    ),
  },
  {
    href: "/analysis",
    label: "Analysis",
    icon: (
      <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
      </svg>
    ),
  },
  {
    href: "/kb",
    label: "Knowledge Base",
    icon: (
      <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
      </svg>
    ),
  },
  {
    href: "/accretion",
    label: "Accretion",
    icon: (
      <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 4h12M4 8h16M2 12h20M4 16h16M6 20h12" />
      </svg>
    ),
  },
];

const settingsNavItem = {
  href: "/settings",
  label: "Settings",
  icon: (
    <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
    </svg>
  ),
};

interface SidebarProps {
  forceCollapsed?: boolean;
}

export function Sidebar({ forceCollapsed }: SidebarProps) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  // Initialize collapsed state from localStorage (client-side only)
  useEffect(() => {
    setCollapsed(localStorage.getItem(STORAGE_KEY) === "true");
  }, []);

  const effectiveCollapsed = forceCollapsed || collapsed;

  function toggleCollapsed() {
    const next = !collapsed;
    setCollapsed(next);
    localStorage.setItem(STORAGE_KEY, String(next));
  }

  function isActive(href: string) {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  }

  function renderNavLink(item: { href: string; label: string; icon: React.ReactNode }) {
    const active = isActive(item.href);
    return (
      <Link
        key={item.href}
        href={item.href}
        onClick={() => setMobileOpen(false)}
        title={effectiveCollapsed ? item.label : undefined}
        className={cn(
          "flex items-center gap-3 py-2 text-sm transition-colors",
          effectiveCollapsed ? "justify-center px-0" : "px-3",
          active
            ? "border-l-[3px] border-accent text-accent bg-accent/5"
            : "border-l-[3px] border-transparent text-text-secondary hover:text-text-primary hover:bg-white/5"
        )}
      >
        {item.icon}
        {!effectiveCollapsed && <span className="truncate">{item.label}</span>}
      </Link>
    );
  }

  return (
    <>
      {/* Mobile hamburger button */}
      <button
        onClick={() => setMobileOpen(!mobileOpen)}
        className="fixed top-4 left-4 z-50 p-2 rounded-lg bg-surface border border-border lg:hidden"
        aria-label="Toggle sidebar"
      >
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
        </svg>
      </button>

      {/* Backdrop for mobile */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          "fixed top-0 left-0 z-40 h-full bg-surface border-r border-border flex flex-col transition-[width] duration-200 ease-[cubic-bezier(0.22,1,0.36,1)]",
          "lg:translate-x-0 lg:static lg:z-auto",
          mobileOpen ? "translate-x-0 w-60" : "-translate-x-full",
          // On desktop: respect collapsed state
          effectiveCollapsed ? "lg:w-16 overflow-hidden" : "lg:w-60",
          // Mobile always uses full translate for open/close
          mobileOpen && "!w-60 !overflow-visible"
        )}
      >
        {/* Logo */}
        <div className={cn(
          "h-16 flex items-center border-b border-border shrink-0",
          effectiveCollapsed ? "justify-center px-2" : "px-6"
        )}>
          <Link href="/" className={cn(
            "flex items-center",
            effectiveCollapsed ? "justify-center" : "gap-2"
          )}>
            <FirnLogo size={effectiveCollapsed ? 24 : 28} />
            {!effectiveCollapsed && (
              <span className="font-semibold text-text-primary text-sm">Firn</span>
            )}
          </Link>
        </div>

        {/* Main navigation */}
        <nav className={cn(
          "flex-1 py-4 space-y-1",
          effectiveCollapsed ? "px-1" : "px-3"
        )}>
          {mainNavItems.map(renderNavLink)}
        </nav>

        {/* Bottom section */}
        <div className={cn(
          "py-4 border-t border-border space-y-1",
          effectiveCollapsed ? "px-1" : "px-3"
        )}>
          {/* Mountain ridge decoration (B6) — only when expanded */}
          {!effectiveCollapsed && (
            <svg
              className="w-full mb-3 opacity-100"
              viewBox="0 0 200 30"
              fill="rgba(0, 212, 170, 0.04)"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <path d="M0 30 L20 18 L40 24 L65 8 L85 20 L100 12 L120 22 L145 4 L165 16 L180 10 L200 20 L200 30 Z" />
            </svg>
          )}

          {/* Settings — below divider, before Sign Out */}
          {renderNavLink(settingsNavItem)}

          {/* Collapse toggle (desktop only) */}
          <button
            onClick={toggleCollapsed}
            title={effectiveCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={cn(
              "hidden lg:flex items-center gap-3 py-2 text-sm text-text-secondary hover:text-text-primary hover:bg-white/5 w-full transition-colors border-l-[3px] border-transparent",
              effectiveCollapsed ? "justify-center px-0" : "px-3"
            )}
          >
            <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              {collapsed ? (
                <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 4.5l7.5 7.5-7.5 7.5m-6-15l7.5 7.5-7.5 7.5" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" d="M18.75 19.5l-7.5-7.5 7.5-7.5m-6 15L5.25 12l7.5-7.5" />
              )}
            </svg>
            {!effectiveCollapsed && <span>Collapse</span>}
          </button>

          {/* Sign Out / Sign In */}
          {user?.role === "admin" ? (
            <button
              onClick={logout}
              title={effectiveCollapsed ? "Sign Out (Admin)" : undefined}
              className={cn(
                "flex items-center gap-3 py-2 text-sm text-text-secondary hover:text-text-primary hover:bg-white/5 w-full transition-colors border-l-[3px] border-transparent",
                effectiveCollapsed ? "justify-center px-0" : "px-3"
              )}
            >
              <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6a2.25 2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15m3 0 3-3m0 0-3-3m3 3H9" />
              </svg>
              {!effectiveCollapsed && <span>Sign Out (Admin)</span>}
            </button>
          ) : (
            <Link
              href="/login"
              onClick={() => setMobileOpen(false)}
              title={effectiveCollapsed ? "Sign In" : undefined}
              className={cn(
                "flex items-center gap-3 py-2 text-sm text-text-secondary hover:text-text-primary hover:bg-white/5 w-full transition-colors border-l-[3px] border-transparent",
                effectiveCollapsed ? "justify-center px-0" : "px-3"
              )}
            >
              <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z" />
              </svg>
              {!effectiveCollapsed && <span>Sign In</span>}
            </Link>
          )}
        </div>
      </aside>
    </>
  );
}
