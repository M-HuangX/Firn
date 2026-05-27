"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import type {
  SystemStatus,
  AnalysisMeta,
  AnalysisDetail,
  AuditResult,
  DigestMeta,
  DigestDetail,
  KBTheme,
  KBStock,
  KBThemeDetail,
  KBStockDetail,
  KBEvent,
  KBEventDetail,
  KBGraphData,
  CoreMindSnapshot,
  EvolutionData,
  MarketSnapshotResponse,
  MaturationResponse,
  PulseResponse,
  SourceInfo,
  WatchlistCategory,
} from "@/lib/types";

// ─── Queries ───────────────────────────────────────────────────────────────

export function useSystemStatus() {
  return useQuery<SystemStatus>({
    queryKey: ["system-status"],
    queryFn: () => api.get("/api/status"),
    refetchInterval: 30_000,
  });
}

export function useAnalysisList() {
  return useQuery<AnalysisMeta[]>({
    queryKey: ["analysis-list"],
    queryFn: () => api.get("/api/analysis"),
  });
}

export function useAnalysis(id: string | null) {
  return useQuery<AnalysisDetail>({
    queryKey: ["analysis", id],
    queryFn: () => api.get(`/api/analysis/${id}`),
    enabled: !!id,
  });
}

export function useAnalysisReport(id: string | null) {
  return useQuery<{ report_markdown: string }>({
    queryKey: ["analysis-report", id],
    queryFn: () => api.get(`/api/analysis/${id}/report`),
    enabled: !!id,
  });
}

export function useAnalysisAudit(id: string | null) {
  return useQuery<AuditResult>({
    queryKey: ["analysis-audit", id],
    queryFn: () => api.get(`/api/analysis/${id}/audit`),
    enabled: !!id,
  });
}

export function useTriggerAudit() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (execId: string) => api.post(`/api/analysis/${execId}/audit`),
    onSuccess: (_data, execId) => {
      // Start polling the analysis detail until has_audit becomes true
      queryClient.invalidateQueries({ queryKey: ["analysis", execId] });
    },
  });
}

export function useAnalysisToolCalls(id: string | null) {
  return useQuery<Record<string, Array<{
    tool_name: string;
    input: string;
    output?: string;
    duration_seconds?: number;
    success?: boolean;
    error?: string;
  }>>>({
    queryKey: ["analysis-tool-calls", id],
    queryFn: () => api.get(`/api/analysis/${id}/tool-calls`),
    enabled: !!id,
    staleTime: Infinity, // Tool call data doesn't change
  });
}

export function useDigestList() {
  return useQuery<DigestMeta[]>({
    queryKey: ["digest-list"],
    queryFn: () => api.get("/api/digest"),
    refetchInterval: 10_000, // Poll every 10s to discover CLI-triggered sessions
  });
}

export function useDigest(id: string | null) {
  return useQuery<DigestDetail>({
    queryKey: ["digest", id],
    queryFn: () => api.get(`/api/digest/${id}`),
    enabled: !!id,
  });
}

export function useKBThemes() {
  return useQuery<KBTheme[]>({
    queryKey: ["kb-themes"],
    queryFn: () => api.get("/api/kb/themes"),
  });
}

export function useKBStocks() {
  return useQuery<KBStock[]>({
    queryKey: ["kb-stocks"],
    queryFn: () => api.get("/api/kb/stocks"),
  });
}

export function useKBCoreMind() {
  return useQuery<{ content: string }>({
    queryKey: ["kb-core-mind"],
    queryFn: () => api.get("/api/kb/core-mind"),
  });
}

export function useMarketSnapshot() {
  return useQuery<MarketSnapshotResponse>({
    queryKey: ["market-snapshot"],
    queryFn: () => api.get("/api/config/market-snapshot"),
    refetchInterval: 5 * 60_000,
  });
}

export function useKBGraph() {
  return useQuery<KBGraphData>({
    queryKey: ["kb-graph"],
    queryFn: () => api.get("/api/kb/graph"),
  });
}

export function useEvolution() {
  return useQuery<EvolutionData>({
    queryKey: ["kb-evolution"],
    queryFn: () => api.get("/api/kb/evolution"),
  });
}

export function useCoreMindHistory() {
  return useQuery<{ snapshots: CoreMindSnapshot[] }>({
    queryKey: ["kb-core-mind-history"],
    queryFn: () => api.get("/api/kb/core-mind/history"),
  });
}

export function useCoreMindSnapshot(id: string | null) {
  return useQuery<{ id: string; content: string }>({
    queryKey: ["kb-core-mind-snapshot", id],
    queryFn: () => api.get(`/api/kb/core-mind/snapshot/${id}`),
    enabled: !!id,
  });
}

export function useKBThemeDetail(slug: string | null) {
  return useQuery<KBThemeDetail>({
    queryKey: ["kb-theme", slug],
    queryFn: () => api.get(`/api/kb/themes/${slug}`),
    enabled: !!slug,
  });
}

export function useKBStockDetail(ticker: string | null) {
  return useQuery<KBStockDetail>({
    queryKey: ["kb-stock", ticker],
    queryFn: () => api.get(`/api/kb/stocks/${ticker}`),
    enabled: !!ticker,
  });
}

export function useKBEvents() {
  return useQuery<KBEvent[]>({
    queryKey: ["kb-events"],
    queryFn: () => api.get("/api/kb/events"),
  });
}

export function useKBEventDetail(slug: string | null) {
  return useQuery<KBEventDetail>({
    queryKey: ["kb-event", slug],
    queryFn: () => api.get(`/api/kb/events/${slug}`),
    enabled: !!slug,
  });
}

export function useKBInbox() {
  return useQuery<{ unread: number; read: number }>({
    queryKey: ["kb-inbox"],
    queryFn: () => api.get("/api/kb/inbox"),
  });
}

export function useMaturation() {
  return useQuery<MaturationResponse>({
    queryKey: ["kb", "maturation"],
    queryFn: () => api.get("/api/kb/maturation"),
  });
}

export function useCoreMindPulse() {
  return useQuery<PulseResponse>({
    queryKey: ["kb", "core-mind", "pulse"],
    queryFn: () => api.get("/api/kb/core-mind/pulse"),
  });
}

// ─── Mutations ─────────────────────────────────────────────────────────────

export function useRunAnalysis() {
  const queryClient = useQueryClient();
  return useMutation<{ exec_id: string; status: string }, Error, { ticker: string }>({
    mutationFn: (params) => api.post("/api/analysis", params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["analysis-list"] });
    },
  });
}

export function useRunDigest() {
  const queryClient = useQueryClient();
  return useMutation<{ exec_id: string; status: string }, Error, void>({
    mutationFn: () => api.post("/api/digest"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["digest-list"] });
    },
  });
}

// ─── Config ──────────────────────────────────────────────────────────────────

export function useWatchlist() {
  return useQuery<{ categories: Record<string, WatchlistCategory> }>({
    queryKey: ["config-watchlist"],
    queryFn: () => api.get("/api/config/watchlist"),
  });
}

export function useUpdateWatchlist() {
  const queryClient = useQueryClient();
  return useMutation<void, Error, { categories: Record<string, WatchlistCategory> }>({
    mutationFn: (data) => api.put("/api/config/watchlist", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config-watchlist"] });
    },
  });
}

export function useSources() {
  return useQuery<{ sources: SourceInfo[] }>({
    queryKey: ["config-sources"],
    queryFn: () => api.get("/api/config/sources"),
  });
}

export function useRefreshSources() {
  const queryClient = useQueryClient();
  return useMutation<{ exec_id: string }, Error, void>({
    mutationFn: () => api.post("/api/config/sources/refresh"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config-sources"] });
    },
  });
}

// Auth mutations live in use-auth.ts (single source of truth for auth state)
