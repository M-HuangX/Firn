"use client";

import { useState, useEffect, Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { StatusBadge } from "@/components/ui/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ReportView } from "@/components/report/report-view";
import { AnalysisDAG, AgentDetailPanel } from "@/components/pipeline";
import { useAnalysis, useAnalysisReport, useAnalysisAudit } from "@/hooks/use-api";
import { useAuth } from "@/hooks/use-auth";
import { api } from "@/lib/api-client";
import { AnalysisTheaterPage } from "@/components/theater/analysis-theater-page";

interface TraceStep {
  step: number;
  ts: string;
  input: { message_count?: number; total_chars?: number };
  output: {
    text?: string;
    text_length?: number;
    tool_calls?: { name: string; args: Record<string, unknown> }[];
  };
  tokens: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number; reasoning_tokens?: number };
}

interface TraceData {
  prompts: Record<string, string>;
  react_steps: Record<string, TraceStep[]>;
  tool_calls: Record<string, unknown>;
  verification: Record<string, unknown>;
}

function ExpandableText({ text, maxLines = 6 }: { text: string; maxLines?: number }) {
  const [expanded, setExpanded] = useState(false);
  const lines = text.split("\n");
  const needsTruncate = lines.length > maxLines;
  const displayText = expanded ? text : lines.slice(0, maxLines).join("\n");

  return (
    <div className="relative">
      <pre className="text-xs text-text-secondary whitespace-pre-wrap font-mono leading-relaxed overflow-x-auto max-h-[60vh] overflow-y-auto scrollbar-thin">
        {displayText}
        {!expanded && needsTruncate && "..."}
      </pre>
      {needsTruncate && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-interactive hover:underline mt-1"
        >
          {expanded ? "Collapse" : `Show all (${lines.length} lines)`}
        </button>
      )}
    </div>
  );
}

function StepCard({ step, agentName }: { step: TraceStep; agentName: string }) {
  const [expanded, setExpanded] = useState(false);
  const toolCalls = step.output?.tool_calls || [];
  const outputText = step.output?.text || "";
  const hasContent = outputText.length > 0 || toolCalls.length > 0;

  return (
    <div className="rounded-lg bg-background border border-border overflow-hidden">
      <button
        onClick={() => hasContent && setExpanded(!expanded)}
        className="w-full flex items-center gap-3 p-3 hover:bg-surface/50 transition-colors text-left"
      >
        <div className="w-6 h-6 rounded-full bg-accent/10 flex items-center justify-center flex-shrink-0">
          <span className="text-xs font-mono text-accent">{step.step}</span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-secondary">
              {step.ts && new Date(step.ts).toLocaleTimeString()}
            </span>
            {toolCalls.length > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 font-mono">
                {toolCalls.length} tool{toolCalls.length > 1 ? "s" : ""}
              </span>
            )}
            {outputText.length > 200 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-mono">
                {step.output?.text_length?.toLocaleString() || outputText.length} chars
              </span>
            )}
          </div>
          {!expanded && toolCalls.length > 0 && (
            <div className="text-[11px] text-text-secondary/70 truncate mt-0.5">
              {toolCalls.map((t) => t.name).join(", ")}
            </div>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs text-text-secondary flex-shrink-0">
          <span>{(step.tokens?.total_tokens || 0).toLocaleString()} tok</span>
          {(step.tokens?.reasoning_tokens ?? 0) > 0 && (
            <span className="text-interactive">{step.tokens.reasoning_tokens} reasoning</span>
          )}
          {hasContent && (
            <svg
              className={`w-4 h-4 transition-transform ${expanded ? "rotate-180" : ""}`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          )}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-border px-4 py-3 space-y-3">
          {/* Tool calls */}
          {toolCalls.length > 0 && (
            <div className="space-y-2">
              <span className="text-[10px] font-medium text-text-secondary uppercase tracking-wider">Tool Calls</span>
              {toolCalls.map((tc, i) => (
                <div key={i} className="rounded border border-border bg-surface/50 px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-blue-400">{tc.name}</span>
                  </div>
                  <pre className="text-[11px] text-text-secondary/80 font-mono mt-1 whitespace-pre-wrap">
                    {JSON.stringify(tc.args, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          )}

          {/* Agent output text */}
          {outputText && (
            <div className="space-y-1">
              <span className="text-[10px] font-medium text-text-secondary uppercase tracking-wider">Agent Response</span>
              <div className="rounded border border-border bg-surface/50 px-3 py-2">
                <ExpandableText text={outputText} maxLines={12} />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function PromptViewer({ prompts }: { prompts: Record<string, string> }) {
  const [selectedPrompt, setSelectedPrompt] = useState<string | null>(null);
  const promptKeys = Object.keys(prompts);

  return (
    <div className="bg-surface rounded-xl border border-border p-4">
      <h4 className="text-sm font-medium text-text-primary mb-3">System & User Prompts</h4>
      <div className="flex flex-wrap gap-2 mb-3">
        {promptKeys.map((key) => {
          const label = key.replace(/_/g, " ").replace(/(system|user)$/i, (m) => `(${m})`);
          return (
            <button
              key={key}
              onClick={() => setSelectedPrompt(selectedPrompt === key ? null : key)}
              className={`text-xs px-2.5 py-1.5 rounded-lg border transition-colors ${
                selectedPrompt === key
                  ? "bg-accent/10 border-accent/30 text-accent"
                  : "bg-background border-border text-text-secondary hover:text-text-primary"
              }`}
            >
              {label}
            </button>
          );
        })}
      </div>
      {selectedPrompt && (
        <div className="rounded-lg border border-border bg-background p-3 max-h-[50vh] overflow-y-auto scrollbar-thin">
          <ExpandableText text={prompts[selectedPrompt]} maxLines={30} />
        </div>
      )}
    </div>
  );
}

function TraceTab({ execId }: { execId: string }) {
  const { isAdmin } = useAuth();
  const { data, isLoading, error } = useQuery<TraceData>({
    queryKey: ["analysis-trace", execId],
    queryFn: () => api.get(`/api/analysis/${execId}/trace`),
    enabled: isAdmin,
  });

  if (!isAdmin) {
    return (
      <div className="bg-surface rounded-xl border border-border p-6 text-center">
        <p className="text-sm text-text-secondary">Trace data requires admin access.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="bg-surface rounded-xl border border-border p-6 space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} variant="text" />
        ))}
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-surface rounded-xl border border-border p-6 text-center">
        <p className="text-sm text-negative">Failed to load trace data.</p>
      </div>
    );
  }

  const agentNames = Object.keys(data.react_steps);
  const totalTokens = agentNames.reduce((sum, name) => {
    const steps = data.react_steps[name] || [];
    return sum + steps.reduce((s, step) => s + (step.tokens?.total_tokens || 0), 0);
  }, 0);
  const totalSteps = agentNames.reduce((s, n) => s + (data.react_steps[n]?.length || 0), 0);
  const totalToolCalls = agentNames.reduce((s, n) => {
    return s + (data.react_steps[n] || []).reduce((ts, step) => ts + (step.output?.tool_calls?.length || 0), 0);
  }, 0);

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="bg-surface rounded-xl border border-border p-4">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div>
            <span className="text-xs text-text-secondary">Agents</span>
            <p className="text-lg font-mono text-text-primary">{agentNames.length}</p>
          </div>
          <div>
            <span className="text-xs text-text-secondary">Total Steps</span>
            <p className="text-lg font-mono text-text-primary">{totalSteps}</p>
          </div>
          <div>
            <span className="text-xs text-text-secondary">Tool Calls</span>
            <p className="text-lg font-mono text-text-primary">{totalToolCalls}</p>
          </div>
          <div>
            <span className="text-xs text-text-secondary">Total Tokens</span>
            <p className="text-lg font-mono text-text-primary">{totalTokens.toLocaleString()}</p>
          </div>
          <div>
            <span className="text-xs text-text-secondary">Prompts</span>
            <p className="text-lg font-mono text-text-primary">{Object.keys(data.prompts).length}</p>
          </div>
        </div>
      </div>

      {/* Prompts */}
      {Object.keys(data.prompts).length > 0 && (
        <PromptViewer prompts={data.prompts} />
      )}

      {/* Agent Steps */}
      {agentNames.map((agentName) => {
        const steps = data.react_steps[agentName] || [];
        const label = agentName.replace(/_steps$/, "").replace(/_/g, " ");
        const agentToolCount = steps.reduce((s, step) => s + (step.output?.tool_calls?.length || 0), 0);
        const agentTokens = steps.reduce((s, step) => s + (step.tokens?.total_tokens || 0), 0);
        return (
          <div key={agentName} className="bg-surface rounded-xl border border-border p-4">
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-sm font-medium text-text-primary capitalize">{label}</h4>
              <div className="flex gap-3 text-[10px] text-text-secondary">
                <span>{steps.length} steps</span>
                <span>{agentToolCount} tools</span>
                <span>{agentTokens.toLocaleString()} tok</span>
              </div>
            </div>
            <div className="space-y-2">
              {steps.map((step) => (
                <StepCard key={step.step} step={step} agentName={agentName} />
              ))}
            </div>
          </div>
        );
      })}

      {/* Verification sidecar */}
      {Object.keys(data.verification).length > 0 && (
        <div className="bg-surface rounded-xl border border-border p-4">
          <h4 className="text-sm font-medium text-text-primary mb-3">Verification Sidecars</h4>
          <div className="space-y-1">
            {Object.keys(data.verification).map((key) => (
              <div key={key} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-background border border-border">
                <div className="w-2 h-2 rounded-full bg-positive" />
                <span className="text-sm font-mono text-text-primary">{key}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

type TabKey = "pipeline" | "report" | "trace";

const tabs: { key: TabKey; label: string }[] = [
  { key: "pipeline", label: "Pipeline" },
  { key: "report", label: "Report" },
  { key: "trace", label: "Trace" },
];

export default function AnalysisDetailPage() {
  const params = useParams();
  const id = params.id as string;

  // Theater view routing
  return (
    <Suspense fallback={null}>
      <TheaterOrLegacy id={id} />
    </Suspense>
  );
}

function TheaterOrLegacy({ id }: { id: string }) {
  const searchParams = useSearchParams();
  const view = searchParams.get("view");

  if (view === "legacy") {
    return <LegacyAnalysisDetail id={id} />;
  }

  return <AnalysisTheaterPage execId={id} />;
}

function LegacyAnalysisDetail({ id }: { id: string }) {
  const [activeTab, setActiveTab] = useState<TabKey>("report");

  const { data: detail } = useAnalysis(id);
  const { data: reportData, isLoading: reportLoading } = useAnalysisReport(id);
  const { data: auditData, isLoading: auditLoading } = useAnalysisAudit(detail?.has_audit ? id : null);

  const ticker = detail?.ticker ?? "...";
  // Stable audit state: only show "pending" when we KNOW there's no audit
  const auditStatus: "loading" | "available" | "none" =
    detail?.has_audit && auditLoading ? "loading" :
    auditData ? "available" : "none";

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h2 className="text-2xl font-bold font-mono text-text-primary">
            {ticker}
          </h2>
          <StatusBadge variant={detail?.status ?? "running"} />
          {auditData && (
            <span className="text-xs text-text-secondary bg-surface border border-border rounded px-2 py-0.5">
              {auditData.total_claims} claims audited
            </span>
          )}
        </div>
        <div className="text-right">
          {detail?.started_at && (
            <div className="text-sm text-text-secondary">
              {new Date(detail.started_at).toLocaleString()}
              {detail.completed_at && (
                <span className="ml-2 font-mono text-text-secondary/70">
                  ({Math.round((new Date(detail.completed_at).getTime() - new Date(detail.started_at).getTime()) / 1000)}s)
                </span>
              )}
            </div>
          )}
          <div className="text-xs text-text-secondary/50 font-mono mt-0.5">{id}</div>
        </div>
      </div>

      {/* Tab navigation */}
      <div className="border-b border-border">
        <nav className="flex gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                "px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px",
                activeTab === tab.key
                  ? "border-accent text-accent"
                  : "border-transparent text-text-secondary hover:text-text-primary"
              )}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      <div className="min-h-[400px]">
        {activeTab === "pipeline" && (
          <div className="relative">
            <AnalysisDAG execId={id} />
            <AgentDetailPanel />
          </div>
        )}

        {activeTab === "report" && (
          <div className="bg-surface rounded-xl border border-border p-6">
            {reportLoading ? (
              <div className="space-y-4">
                <Skeleton variant="text" className="w-1/3 h-6" />
                <Skeleton variant="text" />
                <Skeleton variant="text" />
                <Skeleton variant="text" className="w-4/5" />
                <Skeleton variant="text" className="w-1/4 h-6 mt-6" />
                <Skeleton variant="text" />
                <Skeleton variant="text" className="w-3/4" />
              </div>
            ) : reportData?.report_markdown ? (
              <ReportView
                markdown={reportData.report_markdown}
                auditCitations={auditData?.citations}
                auditStatus={auditStatus}
                execId={id}
              />
            ) : (
              <p className="text-text-secondary text-sm text-center py-8">
                No report available. Run an analysis to generate one.
              </p>
            )}
          </div>
        )}

        {activeTab === "trace" && (
          <TraceTab execId={id} />
        )}
      </div>
    </div>
  );
}
