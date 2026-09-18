import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useI18n } from "../contexts/I18nContext";
import { useSortableRows } from "../hooks/useSortableRows";
import type { AiUsageMetricValues } from "../types";
import { AI_USAGE_METRICS, formatAiMetric } from "../utils/aiUsageMetrics";
import { SortTh } from "./SortTh";

export function AiUsageMetricsPanel({ totals = {}, daily = [], models = [] }: {
  totals?: AiUsageMetricValues;
  daily?: (AiUsageMetricValues & { day: string })[];
  models?: (AiUsageMetricValues & { model: string })[];
}) {
  const { t, lang } = useI18n();
  const sorter = useSortableRows(models);
  const available = AI_USAGE_METRICS.filter(({ key }) => daily.some((row) => row[key] != null));
  const format = (value: number | null | undefined) => formatAiMetric(value, t("aiMetrics.notReported"), lang);

  return (
    <div className="ai-metrics-panel" role="group" aria-label={t("aiMetrics.title")}>
      <div className="dashboard-kpi ai-metrics-summary">
        {AI_USAGE_METRICS.map(({ key, label, color }) => (
          <div className="stat-card" key={key} title={key}>
            <div className="stat-value" style={{ color }}>{format(totals[key])}</div>
            <div className="stat-label">{t(label)}</div>
          </div>
        ))}
      </div>
      {available.length > 0 && <div className="ai-metrics-chart">
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <LineChart data={daily} margin={{ top: 8, right: 12, bottom: 8, left: 0 }} accessibilityLayer>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="day" tick={{ fontSize: 11, fill: "var(--text-muted)" }} tickFormatter={(day: string) => day.slice(5)} />
            <YAxis width={56} tick={{ fontSize: 11, fill: "var(--text-muted)" }} tickFormatter={(value: number) => value.toLocaleString(lang, { notation: "compact" })} />
            <Tooltip
              contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12 }}
              formatter={(value) => format(Number(value))}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {available.map(({ key, label, color }) => <Line key={key} dataKey={key} name={t(label)} stroke={color} strokeWidth={2} dot={daily.length === 1} connectNulls={false} isAnimationActive={false} />)}
          </LineChart>
        </ResponsiveContainer>
      </div>}
      {models.length > 0 && <div className="dashboard-table-wrap">
        <table className="dashboard-table">
          <thead><tr>
            <SortTh label={t("csvDash.model")} sortKey="model" sorter={sorter} />
            {AI_USAGE_METRICS.map(({ key, label }) => <SortTh key={key} label={t(label)} sortKey={key} sorter={sorter} />)}
          </tr></thead>
          <tbody>{sorter.rows.map((model) => <tr key={model.model}>
            <td>{model.model}</td>
            {AI_USAGE_METRICS.map(({ key }) => <td key={key}>{format(model[key])}</td>)}
          </tr>)}</tbody>
        </table>
      </div>}
    </div>
  );
}