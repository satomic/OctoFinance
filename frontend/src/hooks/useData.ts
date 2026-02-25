import { useState, useEffect, useCallback } from "react";
import type { OrgInfo, Overview, Recommendation, DashboardData } from "../types";

export function useOrgs() {
  const [orgs, setOrgs] = useState<OrgInfo[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchOrgs = useCallback(async () => {
    try {
      const res = await fetch("/api/data/orgs");
      const data = await res.json();
      setOrgs(data.orgs || []);
    } catch {
      setOrgs([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOrgs();
  }, [fetchOrgs]);

  return { orgs, loading, refetch: fetchOrgs };
}

export function useOverview() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchOverview = useCallback(async () => {
    try {
      const res = await fetch("/api/data/overview");
      const data = await res.json();
      setOverview(data);
    } catch {
      setOverview(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOverview();
  }, [fetchOverview]);

  return { overview, loading, refetch: fetchOverview };
}

export function usePendingActions() {
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchPending = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/actions/pending");
      const data = await res.json();
      setRecommendations(data.recommendations || []);
    } catch {
      setRecommendations([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPending();
  }, [fetchPending]);

  const executeAction = useCallback(async (id: string) => {
    const res = await fetch("/api/actions/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recommendation_id: id }),
    });
    const result = await res.json();
    await fetchPending();
    return result;
  }, [fetchPending]);

  const rejectAction = useCallback(async (id: string) => {
    const res = await fetch("/api/actions/reject", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recommendation_id: id }),
    });
    const result = await res.json();
    await fetchPending();
    return result;
  }, [fetchPending]);

  return { recommendations, loading, refetch: fetchPending, executeAction, rejectAction };
}

export function useSync() {
  const sync = useCallback(async () => {
    await fetch("/api/sync", { method: "POST" });
  }, []);

  return { sync };
}

export function useDashboard(selectedOrgs: string[]) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const params = selectedOrgs.length > 0 ? `?orgs=${selectedOrgs.join(",")}` : "";
      const res = await fetch(`/api/data/dashboard${params}`);
      const json = await res.json();
      setData(json);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [selectedOrgs.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  return { data, loading, refetch: fetchDashboard };
}
