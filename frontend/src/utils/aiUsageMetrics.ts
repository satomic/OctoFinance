export const AI_USAGE_METRICS = [
  { key: "input", label: "aiMetrics.input", color: "#58a6ff" },
  { key: "output", label: "aiMetrics.output", color: "#3fb950" },
  { key: "cache_read", label: "aiMetrics.cacheRead", color: "#d29922" },
  { key: "cache_write", label: "aiMetrics.cacheWrite", color: "#39c5cf" },
] as const;

export function formatAiMetric(value: number | null | undefined, unavailable: string, lang?: string): string {
  return value == null || !Number.isFinite(value)
    ? unavailable
    : value.toLocaleString(lang, { maximumFractionDigits: 4 });
}