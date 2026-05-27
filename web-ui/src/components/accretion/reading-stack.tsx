"use client";

import { useMemo, useRef, useEffect, useCallback } from "react";
import { useDigestTheaterStore } from "@/stores/digest-theater-store";
import { SOURCE_DOT_COLORS } from "@/lib/digest-theater-types";
import type { ArticleState, ArticleVisualState } from "@/lib/digest-theater-types";

// ─── Constants ───────────────────────────────────────────────────────────────

/** Stagger delay per card within a batch (ms) */
const CARD_STAGGER_MS = 80;

/** How long after manual scroll before auto-scroll re-engages (ms) */
const SCROLL_DISENGAGE_MS = 5000;

// ─── Formatting helpers ──────────────────────────────────────────────────────

function formatCharCount(count: number): string {
  if (!count || count <= 0) return "";
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}k chars`;
  }
  return `${count} chars`;
}

function formatDate(dateStr: string): string {
  if (!dateStr) return "";
  // Handle ISO date strings — show just the date portion
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toISOString().slice(0, 10);
  } catch {
    return dateStr;
  }
}

// ─── Card state → inline style mapping ──────────────────────────────────────

function getCardTransform(state: ArticleVisualState): string {
  switch (state) {
    case "idle":
      return "rotateY(-1.5deg)";
    case "active-batch":
      return "rotateY(0deg) translateZ(24px)";
    case "reading":
      return "rotateY(0deg) translateZ(32px)";
    case "processed":
      return "rotateY(-1.5deg) translateZ(-4px)";
    default:
      return "rotateY(-1.5deg)";
  }
}

function getCardBoxShadow(state: ArticleVisualState): string {
  switch (state) {
    case "active-batch":
      return "0 0 16px rgba(217, 168, 83, 0.1), inset 0 0 12px rgba(217, 168, 83, 0.04)";
    case "reading":
      return "0 0 12px rgba(96, 165, 250, 0.15), 0 2px 8px rgba(0,0,0,0.3)";
    case "processed":
      return "none";
    default:
      return "none";
  }
}

function getCardBorder(state: ArticleVisualState): string {
  switch (state) {
    case "active-batch":
      return "1px solid rgba(217, 168, 83, 0.2)";
    case "reading":
      return "1px solid rgba(96, 165, 250, 0.2)";
    default:
      return "1px solid rgba(255, 255, 255, 0.06)";
  }
}

function getCardOpacity(state: ArticleVisualState): number {
  switch (state) {
    case "processed":
      return 0.35;
    default:
      return 1;
  }
}

function getCardFilter(state: ArticleVisualState): string {
  if (state === "processed") return "grayscale(20%)";
  return "none";
}

// ─── Batch group type ────────────────────────────────────────────────────────

interface BatchGroup {
  batchNum: number;
  articles: ArticleState[];
}

// ─── Component ───────────────────────────────────────────────────────────────

export function ReadingStack() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastManualScrollRef = useRef<number>(0);
  const prevBatchCountRef = useRef<number>(0);

  // Scalar selectors (React 19 safe)
  const activeArticleCount = useDigestTheaterStore((s) => s.activeArticleCount);
  const activeBatchNum = useDigestTheaterStore((s) => s.activeBatchNum);
  const readingArticleSlug = useDigestTheaterStore((s) => s.readingArticleSlug);

  // Derive articles array from store using scalar triggers
  // readingArticleSlug changes when a different article enters "reading" state
  const articles = useMemo(() => {
    return useDigestTheaterStore.getState().activeArticles;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeArticleCount, readingArticleSlug]);

  // Group articles by batch
  const batchGroups = useMemo((): BatchGroup[] => {
    const groups: BatchGroup[] = [];
    let currentBatch = -1;

    for (const article of articles) {
      if (article.batchNum !== currentBatch) {
        currentBatch = article.batchNum;
        groups.push({ batchNum: currentBatch, articles: [] });
      }
      groups[groups.length - 1].articles.push(article);
    }

    return groups;
  }, [articles]);

  // Track manual scrolling to temporarily disable auto-scroll
  const handleScroll = useCallback(() => {
    lastManualScrollRef.current = Date.now();
  }, []);

  // Auto-scroll to newest batch when it arrives
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const currentBatchCount = batchGroups.length;
    const prevBatchCount = prevBatchCountRef.current;
    prevBatchCountRef.current = currentBatchCount;

    // Only auto-scroll if a new batch appeared
    if (currentBatchCount <= prevBatchCount) return;

    // Skip auto-scroll if user recently scrolled manually
    const timeSinceManual = Date.now() - lastManualScrollRef.current;
    if (timeSinceManual < SCROLL_DISENGAGE_MS && lastManualScrollRef.current > 0) return;

    // Scroll to bottom with smooth behavior
    requestAnimationFrame(() => {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    });
  }, [batchGroups.length]);

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      {/* Scroll container wrapping perspective — per R5 spec to avoid distortion during scroll */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto scrollbar-thin"
        style={{ paddingTop: "12px", paddingBottom: "12px" }}
      >
        {/* Perspective wrapper (not on scroll container) */}
        <div
          style={{
            perspective: "1000px",
            perspectiveOrigin: "60% 50%",
          }}
        >
          {/* 3D content */}
          <div style={{ transformStyle: "preserve-3d" }}>
            {articles.length === 0 ? (
              <div
                className="flex items-center justify-center text-xs"
                style={{
                  color: "rgba(226, 235, 245, 0.25)",
                  height: "120px",
                  fontFamily: "system-ui, sans-serif",
                  letterSpacing: "0.02em",
                }}
              >
                Awaiting articles...
              </div>
            ) : (
              batchGroups.map((group) => (
                <div
                  key={`batch-${group.batchNum}`}
                  style={{ padding: "0 12px" }}
                >
                  {/* Batch separator */}
                  <BatchSeparator
                    batchNum={group.batchNum}
                    articleCount={group.articles.length}
                    isActive={group.batchNum === activeBatchNum}
                  />

                  {/* Article cards with stagger */}
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    {group.articles.map((article, i) => (
                      <div
                        key={`${article.slug}-${article.batchNum}`}
                        style={{
                          willChange: "transform",
                          animation: `cardDrift ${10 + (i % 6)}s ease-in-out ${(i * 1.7) % 8}s infinite`,
                        }}
                      >
                        <ArticleCard
                          article={article}
                          staggerIndex={i}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Inline keyframes for card entry animation + ambient drift */}
      <style
        dangerouslySetInnerHTML={{
          __html: `
            @keyframes readingStackCardEnter {
              from {
                transform: rotateY(-1.5deg) translateY(12px);
                opacity: 0;
              }
              to {
                transform: rotateY(-1.5deg) translateY(0);
                opacity: 1;
              }
            }
            @keyframes cardDrift {
              0%, 100% { transform: translateX(0); }
              50% { transform: translateX(0.8px); }
            }
          `,
        }}
      />
    </div>
  );
}

// ─── Batch Separator ────────────────────────────────────────────────────────

interface BatchSeparatorProps {
  batchNum: number;
  articleCount: number;
  isActive: boolean;
}

function BatchSeparator({ batchNum, articleCount, isActive }: BatchSeparatorProps) {
  const lineColor = isActive
    ? "rgba(217, 168, 83, 0.2)"
    : "rgba(255, 255, 255, 0.06)";
  const textColor = isActive
    ? "rgba(217, 168, 83, 0.4)"
    : "rgba(255, 255, 255, 0.25)";

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "8px",
        padding: "8px 4px 6px",
      }}
    >
      <div style={{ height: "1px", flex: 1, backgroundColor: lineColor }} />
      <span
        style={{
          fontSize: "10px",
          fontFamily: "system-ui, sans-serif",
          fontWeight: 500,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          color: textColor,
          whiteSpace: "nowrap",
        }}
      >
        Batch {batchNum} · {articleCount} article{articleCount !== 1 ? "s" : ""}
      </span>
      <div style={{ height: "1px", flex: 1, backgroundColor: lineColor }} />
    </div>
  );
}

// ─── Article Card ───────────────────────────────────────────────────────────

interface ArticleCardProps {
  article: ArticleState;
  staggerIndex: number;
}

function ArticleCard({ article, staggerIndex }: ArticleCardProps) {
  const dotColor = SOURCE_DOT_COLORS[article.source] ?? SOURCE_DOT_COLORS.generic;

  // Metadata fragments
  const dateStr = formatDate(article.published_date);
  const charStr = formatCharCount(article.char_count);
  const metaParts = [dateStr, charStr].filter(Boolean);
  const metaLine = metaParts.join(" · ");

  return (
    <div
      data-article-slug={article.slug}
      style={{
        // Card background — glacial glass
        background: "rgba(255, 255, 255, 0.025)",
        backdropFilter: "blur(4px)",
        WebkitBackdropFilter: "blur(4px)",
        border: getCardBorder(article.state),
        borderRadius: "8px",
        padding: "12px 14px",
        // 3D transforms per state
        transform: getCardTransform(article.state),
        opacity: getCardOpacity(article.state),
        filter: getCardFilter(article.state),
        boxShadow: getCardBoxShadow(article.state),
        // Transition between states
        transition: `
          transform 500ms cubic-bezier(0.34, 1.56, 0.64, 1),
          opacity 800ms ease-out,
          box-shadow 500ms ease-out,
          border-color 500ms ease-out,
          filter 800ms ease-out
        `,
        // Entry animation (staggered)
        animation: `readingStackCardEnter 600ms cubic-bezier(0.22, 1, 0.36, 1) both`,
        animationDelay: `${staggerIndex * CARD_STAGGER_MS}ms`,
        // Cursor
        cursor: "default",
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: "10px" }}>
        {/* Source color dot */}
        <span
          style={{
            width: "6px",
            height: "6px",
            borderRadius: "50%",
            backgroundColor: dotColor,
            flexShrink: 0,
            marginTop: "7px",
          }}
        />

        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Title — English primary (serif), Chinese subtitle */}
          <div title={article.title}>
            <div style={{
              fontFamily: 'Georgia, "Noto Serif SC", serif',
              fontSize: "13px",
              lineHeight: 1.5,
              color: "rgba(255, 255, 255, 0.85)",
              letterSpacing: "0.02em",
              display: "-webkit-box",
              WebkitLineClamp: 2,
              WebkitBoxOrient: "vertical",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}>
              {article.title_en || article.title}
            </div>
            {article.title_en && article.title_en !== article.title && (
              <div style={{
                fontFamily: '"Noto Serif SC", Georgia, serif',
                fontSize: "11px",
                lineHeight: 1.4,
                color: "rgba(255, 255, 255, 0.35)",
                marginTop: "2px",
                display: "-webkit-box",
                WebkitLineClamp: 1,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}>
                {article.title}
              </div>
            )}
          </div>

          {/* Metadata line */}
          {metaLine && (
            <div
              style={{
                fontFamily: '"JetBrains Mono", ui-monospace, monospace',
                fontSize: "10px",
                lineHeight: 1.4,
                color: "rgba(255, 255, 255, 0.45)",
                marginTop: "4px",
              }}
            >
              {metaLine}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
