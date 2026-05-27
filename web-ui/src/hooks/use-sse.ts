"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { PipelineEvent } from "@/lib/types";
import { API_BASE } from "@/lib/api-client";

const MAX_RECONNECT_DELAY = 30_000;
const INITIAL_RECONNECT_DELAY = 1_000;
const MAX_RETRIES = 10;
const EXEC_ID_PATTERN = /^[a-zA-Z0-9_-]+$/;

export interface UseSSEOptions {
  /** Callback for each event — use this for Zustand store integration */
  onEvent?: (event: PipelineEvent) => void;
}

export function useSSE(execId: string | null, options?: UseSSEOptions) {
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isDone, setIsDone] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectDelayRef = useRef(INITIAL_RECONNECT_DELAY);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retriesRef = useRef(0);
  const onEventRef = useRef(options?.onEvent);
  onEventRef.current = options?.onEvent;

  const cleanup = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setIsConnected(false);
  }, []);

  useEffect(() => {
    if (!execId || !EXEC_ID_PATTERN.test(execId)) {
      cleanup();
      setEvents([]);
      setIsDone(false);
      return;
    }

    retriesRef.current = 0;
    setIsDone(false);

    function connect() {
      const url = `${API_BASE}/api/events/${execId}`;
      const es = new EventSource(url, { withCredentials: true });
      eventSourceRef.current = es;

      es.onopen = () => {
        setIsConnected(true);
        reconnectDelayRef.current = INITIAL_RECONNECT_DELAY;
        retriesRef.current = 0;
      };

      // Backend sends named "pipeline" events
      es.addEventListener("pipeline", (e: MessageEvent) => {
        try {
          const parsed = JSON.parse(e.data) as PipelineEvent;
          // Only accumulate internally if no external handler (avoids double-buffering)
          if (onEventRef.current) {
            onEventRef.current(parsed);
          } else {
            setEvents((prev) => [...prev, parsed]);
          }
        } catch {
          // skip malformed events
        }
      });

      // Backend sends "complete" when pipeline finishes
      es.addEventListener("complete", () => {
        es.close();
        eventSourceRef.current = null;
        setIsConnected(false);
        setIsDone(true);
      });

      // Backend sends "timeout" after 30min
      es.addEventListener("timeout", () => {
        es.close();
        eventSourceRef.current = null;
        setIsConnected(false);
        setIsDone(true);
      });

      es.onerror = () => {
        es.close();
        eventSourceRef.current = null;
        setIsConnected(false);

        retriesRef.current += 1;
        if (retriesRef.current >= MAX_RETRIES) {
          return; // stop reconnecting
        }

        const delay = reconnectDelayRef.current;
        reconnectDelayRef.current = Math.min(
          delay * 2,
          MAX_RECONNECT_DELAY,
        );
        reconnectTimerRef.current = setTimeout(connect, delay);
      };
    }

    connect();

    return cleanup;
  }, [execId, cleanup]);

  return { events, isConnected, isDone };
}
