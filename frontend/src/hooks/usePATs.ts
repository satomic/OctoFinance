import { useState, useEffect, useCallback } from "react";
import type { PATInfo } from "../types";

export interface SyncSettings {
  auto_sync_on_startup: boolean;
  sync_cron: string;
}

export function usePATs() {
  const [pats, setPats] = useState<PATInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [settings, setSettings] = useState<SyncSettings>({
    auto_sync_on_startup: true,
    sync_cron: "",
  });

  const loadPATs = useCallback(async () => {
    try {
      const res = await fetch("/api/pats");
      const data = await res.json();
      setPats(data.pats || []);
    } catch {
      setPats([]);
    }
  }, []);

  const loadSettings = useCallback(async () => {
    try {
      const res = await fetch("/api/settings");
      const data = await res.json();
      setSettings(data);
    } catch {
      // keep defaults
    }
  }, []);

  const updateSettings = useCallback(async (updates: Partial<SyncSettings>) => {
    try {
      const res = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      });
      if (res.ok) {
        const data = await res.json();
        setSettings(data);
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }, []);

  useEffect(() => {
    loadPATs();
    loadSettings();
  }, [loadPATs, loadSettings]);

  const addPAT = useCallback(async (label: string, token: string, enterprise_slugs: string[] = []) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/pats", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label, token, enterprise_slugs }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || "Failed to add PAT");
        return null;
      }
      await loadPATs();
      return data;
    } catch (err: any) {
      setError(err.message || "Network error");
      return null;
    } finally {
      setLoading(false);
    }
  }, [loadPATs]);

  const removePAT = useCallback(async (id: string) => {
    setError(null);
    try {
      const res = await fetch(`/api/pats/${id}`, { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json();
        setError(data.detail || "Failed to delete PAT");
        return false;
      }
      await loadPATs();
      return true;
    } catch (err: any) {
      setError(err.message || "Network error");
      return false;
    }
  }, [loadPATs]);

  const updatePAT = useCallback(async (id: string, label: string) => {
    setError(null);
    try {
      const res = await fetch(`/api/pats/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label }),
      });
      if (!res.ok) {
        const data = await res.json();
        setError(data.detail || "Failed to update PAT");
        return false;
      }
      await loadPATs();
      return true;
    } catch (err: any) {
      setError(err.message || "Network error");
      return false;
    }
  }, [loadPATs]);

  const clearError = useCallback(() => setError(null), []);

  return { pats, loading, error, loadPATs, addPAT, removePAT, updatePAT, clearError, settings, updateSettings };
}
