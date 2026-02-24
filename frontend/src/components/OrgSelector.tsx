import { useState, useMemo } from "react";
import { useOrgs } from "../hooks/useData";
import { useI18n } from "../contexts/I18nContext";
import type { OrgInfo } from "../types";

type SortKey = "name" | "seats" | "active" | "inactive" | "waste";

function sortOrgs(orgs: OrgInfo[], sortKey: SortKey): OrgInfo[] {
  return [...orgs].sort((a, b) => {
    switch (sortKey) {
      case "name":
        return a.login.localeCompare(b.login);
      case "seats":
        return (b.total_seats ?? 0) - (a.total_seats ?? 0);
      case "active":
        return (b.active_seats ?? 0) - (a.active_seats ?? 0);
      case "inactive": {
        const ai = (a.total_seats ?? 0) - (a.active_seats ?? 0);
        const bi = (b.total_seats ?? 0) - (b.active_seats ?? 0);
        return bi - ai;
      }
      case "waste": {
        const priceA = a.price_per_seat ?? 19;
        const priceB = b.price_per_seat ?? 19;
        const wasteA = ((a.total_seats ?? 0) - (a.active_seats ?? 0)) * priceA;
        const wasteB = ((b.total_seats ?? 0) - (b.active_seats ?? 0)) * priceB;
        return wasteB - wasteA;
      }
      default:
        return 0;
    }
  });
}

export function OrgSelector() {
  const { orgs, loading } = useOrgs();
  const { t } = useI18n();
  const [sortKey, setSortKey] = useState<SortKey>("name");

  const sortedOrgs = useMemo(() => sortOrgs(orgs, sortKey), [orgs, sortKey]);

  // Group by enterprise
  const grouped = useMemo(() => {
    const groups: Record<string, OrgInfo[]> = {};
    for (const org of sortedOrgs) {
      const enterprise = org.enterprise || "Independent";
      (groups[enterprise] ||= []).push(org);
    }
    // Sort: named enterprises first, "Independent" last
    return Object.entries(groups).sort(([a], [b]) => {
      if (a === "Independent") return 1;
      if (b === "Independent") return -1;
      return a.localeCompare(b);
    });
  }, [sortedOrgs]);

  const sortOptions: { key: SortKey; label: string }[] = [
    { key: "name", label: t("sort.name") },
    { key: "seats", label: t("sort.seats") },
    { key: "active", label: t("sort.active") },
    { key: "inactive", label: t("sort.inactive") },
    { key: "waste", label: t("sort.waste") },
  ];

  if (loading) {
    return <div className="sidebar-section loading">{t("loading")}</div>;
  }

  return (
    <div className="sidebar-orgs">
      <div className="orgs-header">
        <select
          className="sort-select"
          value={sortKey}
          onChange={(e) => setSortKey(e.target.value as SortKey)}
        >
          {sortOptions.map((opt) => (
            <option key={opt.key} value={opt.key}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>
      <div className="org-list">
        {grouped.map(([enterprise, enterpriseOrgs]) => (
          <div key={enterprise}>
            {grouped.length > 1 && (
              <div className="enterprise-group-header">{enterprise}</div>
            )}
            {enterpriseOrgs.map((org) => (
              <div key={org.login} className={`org-item ${org.has_copilot ? "" : "disabled"}`}>
                <img
                  src={org.avatar_url || `https://github.com/${org.login}.png?size=32`}
                  alt={org.login}
                  className="org-avatar"
                />
                <div className="org-info">
                  <div className="org-name">{org.login}</div>
                  {org.has_copilot ? (
                    <div className="org-meta">
                      {org.plan_type} &middot; {org.total_seats} seats &middot; {org.active_seats} active
                    </div>
                  ) : (
                    <div className="org-meta muted">{t("sidebar.noCopilot")}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        ))}
        {orgs.length === 0 && <div className="empty">{t("sidebar.noOrgs")}</div>}
      </div>
    </div>
  );
}
