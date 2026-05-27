"use client";

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAnalysis, useAnalysisReport, useAnalysisAudit } from "@/hooks/use-api";
import { useTheaterStore } from "@/stores/pipeline-store";
import { Skeleton } from "@/components/ui/skeleton";
import { TheaterHeader } from "./theater-header";
import { AnalysisTheater } from "./analysis-theater";
import { ToolCallDetailPanel } from "./tool-call-detail-panel";
import { ReportOverlay } from "./report-overlay";

interface AnalysisTheaterPageProps {
  execId: string;
}

export function AnalysisTheaterPage({ execId }: AnalysisTheaterPageProps) {
  const queryClient = useQueryClient();
  const { data: detail, isLoading: detailLoading } = useAnalysis(execId);
  const { data: reportData } = useAnalysisReport(execId);
  const { data: auditData, isLoading: auditLoading } = useAnalysisAudit(
    detail?.has_audit ? execId : null
  );

  // When SSE signals analysis complete, refetch detail + report + tool calls
  const storeComplete = useTheaterStore((s) => s.isComplete);
  useEffect(() => {
    if (storeComplete) {
      queryClient.invalidateQueries({ queryKey: ["analysis", execId] });
      queryClient.invalidateQueries({ queryKey: ["analysis-report", execId] });
      queryClient.invalidateQueries({ queryKey: ["analysis-tool-calls", execId] });
    }
  }, [storeComplete, queryClient, execId]);

  // SSE-driven audit detection: when audit node completes, refetch detail (which has has_audit)
  const auditNodeState = useTheaterStore((s) => s.nodes.audit?.state);
  useEffect(() => {
    if (auditNodeState === "complete") {
      queryClient.invalidateQueries({ queryKey: ["analysis", execId] });
    }
  }, [auditNodeState, queryClient, execId]);

  // Fallback polling: if SSE missed audit completion (e.g., page loaded between analysis end and audit end)
  const isComplete_ = detail?.status === "complete" || detail?.status === "failed";
  const hasAudit = detail?.has_audit ?? false;
  const awaitingAudit = storeComplete && isComplete_ && !hasAudit && auditNodeState !== "active";
  useEffect(() => {
    if (!awaitingAudit) return;
    const timer = setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ["analysis", execId] });
    }, 5000);
    return () => clearInterval(timer);
  }, [awaitingAudit, queryClient, execId]);

  const ticker = detail?.ticker ?? "...";
  const status = detail?.status ?? "running";
  const isComplete = isComplete_;

  const auditStatus: "loading" | "in-progress" | "available" | "none" =
    auditNodeState === "active"
      ? "in-progress" // audit actively running (seen via SSE)
      : awaitingAudit
        ? "in-progress" // auto-audit queued (waiting)
        : detail?.has_audit && auditLoading
          ? "loading" // fetching completed audit data from API
          : auditData
            ? "available"
            : "none";

  if (detailLoading) {
    return (
      <div className="h-screen flex flex-col" style={{ background: 'radial-gradient(ellipse 80% 70% at 50% 45%, #0E1628 0%, #0B1120 45%, #070D18 100%)' }}>
        <div className="px-6 py-4 border-b border-border">
          <Skeleton variant="text" className="w-48 h-6" />
          <Skeleton variant="text" className="w-32 h-4 mt-2" />
        </div>
        <div className="flex-1 flex items-center justify-center">
          <Skeleton variant="text" className="w-64 h-8" />
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col" style={{ background: 'radial-gradient(ellipse 80% 70% at 50% 45%, #0E1628 0%, #0B1120 45%, #070D18 100%)' }}>
      <TheaterHeader
        ticker={ticker}
        status={status}
        startedAt={detail?.started_at}
        completedAt={detail?.completed_at}
        execId={execId}
      />

      <div className="flex-1 relative overflow-hidden">
        <AnalysisTheater
          execId={execId}
          isComplete={isComplete}
          hasAudit={hasAudit}
          ticker={ticker}
        />
        <ToolCallDetailPanel execId={execId} />
      </div>

      <ReportOverlay
        execId={execId}
        markdown={reportData?.report_markdown ?? ""}
        auditCitations={auditData?.citations}
        auditStatus={auditStatus}
      />
    </div>
  );
}
