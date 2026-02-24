import { useEffect, useRef, useState, useCallback } from "react";
import type { ConsoleEntry } from "../types";

let syncEntrySeq = 0;
function nextSyncId() {
  return `sync_${Date.now()}_${++syncEntrySeq}`;
}

interface SyncEvent {
  type: "sync_status" | "sync_start" | "sync_complete" | "sync_log";
  syncing?: boolean;
  success?: boolean;
  error?: string | null;
  level?: string;
  message?: string;
  timestamp?: string;
}

/**
 * Hook that tracks sync state via polling + SSE stream for real-time logs.
 * Polling is used as the primary mechanism for sync state (reliable through proxies).
 * SSE stream provides real-time log entries for the console.
 */
export function useSyncStream(onLog: (entry: ConsoleEntry) => void) {
  const [syncing, setSyncing] = useState(false);
  const onLogRef = useRef(onLog);
  onLogRef.current = onLog;
  const onSyncCompleteRef = useRef<(() => void) | null>(null);
  const prevSyncingRef = useRef(false);
  const sseConnectedRef = useRef(false);

  const setOnSyncComplete = useCallback((cb: (() => void) | null) => {
    onSyncCompleteRef.current = cb;
  }, []);

  // --- Poll /api/health for sync state ---
  useEffect(() => {
    let active = true;

    const poll = async () => {
      try {
        const res = await fetch("/api/health");
        if (!res.ok) return;
        const data = await res.json();
        const isSyncing = !!data.is_syncing;

        if (!active) return;

        setSyncing(isSyncing);

        // Detect transition: syncing -> not syncing = sync completed
        if (prevSyncingRef.current && !isSyncing) {
          // Always emit from polling as a fallback (SSE may also emit, duplicates are OK)
          if (!sseConnectedRef.current) {
            onLogRef.current({
              id: nextSyncId(),
              timestamp: Date.now(),
              type: "sync",
              title: "Data sync completed",
            });
          }
          onSyncCompleteRef.current?.();
        }

        // Detect transition: not syncing -> syncing = sync started
        if (!prevSyncingRef.current && isSyncing) {
          if (!sseConnectedRef.current) {
            onLogRef.current({
              id: nextSyncId(),
              timestamp: Date.now(),
              type: "sync",
              title: "Data sync started",
            });
          }
        }

        prevSyncingRef.current = isSyncing;
      } catch {
        // Ignore poll errors
      }
    };

    // Poll immediately and then every 2 seconds
    poll();
    const interval = setInterval(poll, 2000);

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  // --- SSE stream for real-time log entries ---
  useEffect(() => {
    let abortController: AbortController | null = null;
    let active = true;

    const connectSSE = async () => {
      try {
        abortController = new AbortController();
        const response = await fetch("/api/sync-stream", {
          signal: abortController.signal,
          headers: { Accept: "text/event-stream" },
        });

        if (!response.ok || !response.body) {
          console.warn("[useSyncStream] SSE connection failed:", response.status);
          return;
        }

        sseConnectedRef.current = true;
        console.log("[useSyncStream] SSE connected");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (active) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const data: SyncEvent = JSON.parse(line.slice(6));

                if (data.type === "sync_status") {
                  setSyncing(!!data.syncing);
                  prevSyncingRef.current = !!data.syncing;
                } else if (data.type === "sync_start") {
                  setSyncing(true);
                  prevSyncingRef.current = true;
                  onLogRef.current({
                    id: nextSyncId(),
                    timestamp: Date.now(),
                    type: "sync",
                    title: "Data sync started",
                  });
                } else if (data.type === "sync_complete") {
                  setSyncing(false);
                  prevSyncingRef.current = false;
                  onLogRef.current({
                    id: nextSyncId(),
                    timestamp: Date.now(),
                    type: "sync",
                    title: data.success
                      ? "Data sync completed successfully"
                      : `Data sync failed: ${data.error || "unknown error"}`,
                  });
                  onSyncCompleteRef.current?.();
                } else if (data.type === "sync_log") {
                  onLogRef.current({
                    id: nextSyncId(),
                    timestamp: Date.now(),
                    type: "sync",
                    title: `[${(data.level || "info").toUpperCase()}] ${data.message || ""}`,
                  });
                }
              } catch {
                // Skip malformed SSE data
              }
            }
          }
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name !== "AbortError") {
          console.warn("[useSyncStream] SSE error:", err.message);
        }
      } finally {
        sseConnectedRef.current = false;
      }

      // Reconnect after 3 seconds if still active
      if (active) {
        setTimeout(connectSSE, 3000);
      }
    };

    connectSSE();

    return () => {
      active = false;
      abortController?.abort();
    };
  }, []);

  return { syncing, setOnSyncComplete };
}
