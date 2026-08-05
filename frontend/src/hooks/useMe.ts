import { useState, useEffect, useCallback } from "react";
import type { BudgetAuditEntry, BudgetRequestsData, MyCostCentersData, MyDashboardData } from "../types";

/** Personal dashboard data for the currently logged-in GitHub user. */
export function useMyDashboard(
  refreshKey = 0,
  period: "all" | "current_month" = "all",
) {
  const [data, setData] = useState<MyDashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async (live = false) => {
    setLoading(true);
    try {
      const qp = new URLSearchParams({ period });
      // Current month is budget-critical, so always read it straight from GitHub
      if (live || period === "current_month") qp.set("live", "true");
      const res = await fetch(`/api/me/dashboard?${qp}`);
      setData(await res.json());
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    fetchData();
  }, [fetchData, refreshKey]);

  return { data, loading, refetch: fetchData };
}

export interface CreateBudgetRequestPayload {
  request_type: "budget" | "cost_center";
  /** Budget requests only. GitHub budgets run on a single monthly cycle. */
  amount?: number;
  org?: string;
  /** Cost center requests only — the single cost center to move to ("" = unassign). */
  cost_center_id?: string;
  reason?: string;
}

/** Cost centers the user may join or leave, with current membership flagged. */
export function useMyCostCenters(refreshKey = 0) {
  const [data, setData] = useState<MyCostCentersData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/me/cost-centers");
      setData(await res.json());
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData, refreshKey]);

  return { data, loading, refetch: fetchData };
}

/** Budget requests — own requests for regular users, all requests for admins. */
export function useBudgetRequests(status = "all") {
  const [data, setData] = useState<BudgetRequestsData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const qp = new URLSearchParams();
      if (status && status !== "all") qp.set("status", status);
      const res = await fetch(`/api/budget-requests?${qp}`);
      setData(await res.json());
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const create = useCallback(
    async (payload: CreateBudgetRequestPayload) => {
      const res = await fetch("/api/budget-requests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const json = await res.json();
      if (json.ok) await fetchData();
      return json;
    },
    [fetchData],
  );

  const review = useCallback(
    async (
      requestId: string,
      decision: "approve" | "reject",
      approvedAmount?: number,
      comment = "",
      opts: { applyToGithub?: boolean; preventFurtherUsage?: boolean } = {},
    ) => {
      const res = await fetch("/api/budget-requests/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: requestId,
          decision,
          approved_amount: approvedAmount ?? null,
          comment,
          apply_to_github: opts.applyToGithub ?? true,
          prevent_further_usage: opts.preventFurtherUsage ?? true,
        }),
      });
      const json = await res.json();
      if (json.ok) await fetchData();
      return json;
    },
    [fetchData],
  );

  const updateAmount = useCallback(
    async (
      requestId: string,
      approvedAmount: number,
      comment = "",
      opts: { applyToGithub?: boolean; preventFurtherUsage?: boolean } = {},
    ) => {
      const res = await fetch("/api/budget-requests/amount", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: requestId,
          decision: "approve",
          approved_amount: approvedAmount,
          comment,
          apply_to_github: opts.applyToGithub ?? true,
          prevent_further_usage: opts.preventFurtherUsage ?? true,
        }),
      });
      const json = await res.json();
      if (json.ok) await fetchData();
      return json;
    },
    [fetchData],
  );

  const resync = useCallback(
    async (requestId: string, preventFurtherUsage = true) => {
      const res = await fetch("/api/budget-requests/resync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: requestId,
          decision: "approve",
          prevent_further_usage: preventFurtherUsage,
        }),
      });
      const json = await res.json();
      if (json.ok) await fetchData();
      return json;
    },
    [fetchData],
  );

  const remove = useCallback(
    async (requestId: string) => {
      const res = await fetch(`/api/budget-requests/${requestId}`, { method: "DELETE" });
      const json = await res.json();
      if (json.ok) await fetchData();
      return json;
    },
    [fetchData],
  );

  return { data, loading, refetch: fetchData, create, review, updateAmount, resync, remove };
}

/** Flat approval audit trail (admins only). */
export function useBudgetAudit(refreshKey = 0) {
  const [entries, setEntries] = useState<BudgetAuditEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/budget-requests/audit");
      const json = await res.json();
      setEntries(json.entries || []);
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData, refreshKey]);

  return { entries, loading, refetch: fetchData };
}
