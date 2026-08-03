/** First and last day of the current month as `YYYY-MM-DD`. */
export function currentMonthRange(): { start: string; end: string } {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const y = now.getFullYear();
  const m = now.getMonth();
  const last = new Date(y, m + 1, 0).getDate();
  return { start: `${y}-${pad(m + 1)}-01`, end: `${y}-${pad(m + 1)}-${pad(last)}` };
}

/**
 * Resolve the effective date window for a dashboard.
 * `current_month` overrides any manually picked range so the toggle is always
 * authoritative — budgets and quotas reset with the billing cycle.
 */
export function resolveRange(
  periodMode: "all" | "current_month" | undefined,
  dateFrom: string,
  dateTo: string,
): { from: string; to: string; locked: boolean } {
  if (periodMode === "current_month") {
    const { start, end } = currentMonthRange();
    return { from: start, to: end, locked: true };
  }
  return { from: dateFrom, to: dateTo, locked: false };
}
