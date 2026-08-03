import { useI18n } from "../contexts/I18nContext";

interface Props {
  value: "all" | "current_month";
  onChange: (v: "all" | "current_month") => void;
  /** Optional date window shown next to the switch, e.g. "2026-08-01 ~ 2026-08-31". */
  hint?: string;
}

/**
 * Switch between the full history and the running billing cycle.
 * Budgets reset monthly, so "current month" is what tells a user how much
 * allowance is actually left.
 */
export function PeriodToggle({ value, onChange, hint }: Props) {
  const { t } = useI18n();
  return (
    <div className="period-toggle">
      <div className="view-toggle">
        <button
          className={`btn btn-small btn-toggle ${value === "all" ? "btn-toggle-active" : ""}`}
          onClick={() => onChange("all")}
          title={t("period.historicalHint")}
        >
          {t("period.historical")}
        </button>
        <button
          className={`btn btn-small btn-toggle ${value === "current_month" ? "btn-toggle-active" : ""}`}
          onClick={() => onChange("current_month")}
          title={t("period.currentMonthHint")}
        >
          {t("period.currentMonth")}
        </button>
      </div>
      {value === "current_month" && hint && <span className="period-hint">{hint}</span>}
    </div>
  );
}
