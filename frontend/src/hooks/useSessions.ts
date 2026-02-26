import { useState, useCallback, useEffect } from "react";
import { useUIState } from "../contexts/UIStateContext";
import type { SessionInfo } from "../types";

export function useSessions() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const ui = useUIState();
  const currentSessionId = ui.currentSessionId;
  const setCurrentSessionId = useCallback(
    (v: string | null | ((prev: string | null) => string | null)) => {
      const next = typeof v === "function" ? v(ui.currentSessionId) : v;
      ui.patch({ currentSessionId: next });
    },
    [ui.patch, ui.currentSessionId],
  );

  const loadSessions = useCallback(async () => {
    try {
      const res = await fetch("/api/sessions");
      if (res.ok) {
        const data: SessionInfo[] = await res.json();
        setSessions(data);
      }
    } catch {
      // Silently fail
    }
  }, []);

  const createSession = useCallback(async (title = "New Session"): Promise<SessionInfo | null> => {
    try {
      const res = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (res.ok) {
        const session: SessionInfo = await res.json();
        setSessions((prev) => [session, ...prev]);
        return session;
      }
    } catch {
      // Silently fail
    }
    return null;
  }, []);

  const deleteSession = useCallback(async (sessionId: string) => {
    try {
      const res = await fetch(`/api/sessions/${sessionId}`, { method: "DELETE" });
      if (res.ok) {
        setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
        // If we deleted the current session, clear it
        if (ui.currentSessionId === sessionId) {
          ui.patch({ currentSessionId: null });
        }
      }
    } catch {
      // Silently fail
    }
  }, [ui.currentSessionId, ui.patch]);

  const updateSessionTitle = useCallback(async (sessionId: string, title: string) => {
    try {
      const res = await fetch(`/api/sessions/${sessionId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (res.ok) {
        setSessions((prev) =>
          prev.map((s) => (s.session_id === sessionId ? { ...s, title } : s))
        );
      }
    } catch {
      // Silently fail
    }
  }, []);

  const switchSession = useCallback((sessionId: string) => {
    ui.patch({ currentSessionId: sessionId });
  }, [ui.patch]);

  // Load sessions on mount
  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  return {
    sessions,
    currentSessionId,
    loadSessions,
    createSession,
    deleteSession,
    updateSessionTitle,
    switchSession,
    setCurrentSessionId,
  };
}
