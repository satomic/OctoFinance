import { useState, useEffect, useCallback } from "react";
import type { OrgInfo, Overview, Recommendation, DashboardData, CsvInfo, CsvDashboardData } from "../types";

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

export function useCsvInfo() {
  const [info, setInfo] = useState<CsvInfo | null>(null);

  const fetchInfo = useCallback(async () => {
    try {
      const res = await fetch("/api/data/csv-info");
      const data = await res.json();
      setInfo(data);
    } catch {
      setInfo(null);
    }
  }, []);

  useEffect(() => {
    fetchInfo();
  }, [fetchInfo]);

  const uploadCsv = useCallback(async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch("/api/data/upload-csv", {
      method: "POST",
      body: formData,
    });
    const result = await res.json();
    await fetchInfo();
    return result;
  }, [fetchInfo]);

  return { info, refetch: fetchInfo, uploadCsv };
}

// Keep old hook for backward compat
export function usePremiumCsvInfo() {
  const { info, refetch, uploadCsv } = useCsvInfo();
  return { info: info?.premium_csv ?? null, refetch, uploadCsv };
}

export function useCsvDashboard(params: {
  orgs: string[];
  costCenters: string[];
  products: string[];
  skus: string[];
  dateFrom: string;
  dateTo: string;
}) {
  const [data, setData] = useState<CsvDashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const qp = new URLSearchParams();
      if (params.orgs.length) qp.set("orgs", params.orgs.join(","));
      if (params.costCenters.length) qp.set("cost_centers", params.costCenters.join(","));
      if (params.products.length) qp.set("products", params.products.join(","));
      if (params.skus.length) qp.set("skus", params.skus.join(","));
      if (params.dateFrom) qp.set("date_from", params.dateFrom);
      if (params.dateTo) qp.set("date_to", params.dateTo);
      const res = await fetch(`/api/data/csv-dashboard?${qp}`);
      const json = await res.json();
      setData(json);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [params.orgs.join(","), params.costCenters.join(","), params.products.join(","), // eslint-disable-line react-hooks/exhaustive-deps
      params.skus.join(","), params.dateFrom, params.dateTo]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { data, loading, refetch: fetchData };
}
