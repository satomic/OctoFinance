import { useState, useCallback, useRef, useEffect } from "react";
import { useI18n } from "../contexts/I18nContext";
import { useUIState } from "../contexts/UIStateContext";
import { useCostCenterDashboard, useDatasetSync } from "../hooks/useData";
import type { CostCenter, CostCenterShareInfo, UserCostCenterEntry } from "../types";

interface Props {
  refreshKey: number;
}

const SOURCE_TYPE_COLORS: Record<string, string> = {
  Org: "var(--accent)",
  User: "#3fb950",
  Team: "#d29922",
};

/* ---------- Multi-select dropdown (reused pattern) ---------- */
function MultiSelect({
  label, options, selected, onChange,
}: {
  label: string;
  options: string[];
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const isAll = selected.length === 0;
  const triggerLabel = isAll ? label : selected.length === 1 ? selected[0] : `${selected.length} / ${options.length}`;
  const toggle = (v: string) =>
    onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);

  return (
    <div className="org-dropdown" ref={ref} style={{ minWidth: 160 }}>
      <button className="org-dropdown-trigger" onClick={() => setOpen((o) => !o)}>
        <span>{triggerLabel}</span>
        <span className="org-dropdown-arrow">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div className="org-dropdown-menu">
          <label className={`org-dropdown-item ${isAll ? "org-dropdown-item-active" : ""}`}>
            <input type="checkbox" checked={isAll} onChange={() => onChange([])} />
            <span>{label}</span>
          </label>
          <div className="org-dropdown-divider" />
          {options.map((opt) => (
            <label key={opt} className={`org-dropdown-item ${selected.includes(opt) ? "org-dropdown-item-active" : ""}`}>
              <input type="checkbox" checked={selected.includes(opt)} onChange={() => toggle(opt)} />
              <span>{opt}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- Collapsible section ---------- */
function Section({ sectionKey, title, defaultOpen = true, children }: {
  sectionKey: string; title: string; defaultOpen?: boolean; children: React.ReactNode;
}) {
  const { dashboardSections, patch } = useUIState();
  const open = dashboardSections[`cc_${sectionKey}`] ?? defaultOpen;
  const toggle = useCallback(() => {
    patch({ dashboardSections: { ...dashboardSections, [`cc_${sectionKey}`]: !open } });
  }, [patch, dashboardSections, sectionKey, open]);
  return (
    <div className="dash-section">
      <div className="dash-section-header" onClick={toggle}>
        <span className="dash-section-chevron">{open ? "▼" : "▶"}</span>
        <h3 className="dash-section-title">{title}</h3>
      </div>
      {open && <div className="dash-section-body">{children}</div>}
    </div>
  );
}

/* ---------- Share settings modal ---------- */
function ShareModal({
  cc, share, onSave, onDisable, onClose,
}: {
  cc: CostCenter;
  share: CostCenterShareInfo | null;
  onSave: (mode: "public" | "password", password: string) => Promise<string | null>;
  onDisable: () => Promise<void>;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [mode, setMode] = useState<"public" | "password">(share?.mode ?? "public");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const shareUrl = share ? `${window.location.origin}${share.url}` : "";

  const handleSave = async () => {
    if (mode === "password" && !share && !password.trim()) {
      setError(t("ccDash.sharePasswordRequired"));
      return;
    }
    setBusy(true);
    setError("");
    const err = await onSave(mode, password.trim());
    setBusy(false);
    if (err) setError(err);
    else onClose();
  };

  const handleDisable = async () => {
    setBusy(true);
    await onDisable();
    setBusy(false);
    onClose();
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard unavailable */ }
  };

  return (
    <div className="settings-modal-overlay" onClick={() => !busy && onClose()}>
      <div className="settings-modal cc-share-modal" onClick={(e) => e.stopPropagation()}>
        <div className="settings-modal-header">
          <h2>{t("ccDash.shareModalTitle")} · {cc.name}</h2>
          <button className="settings-close-btn" onClick={onClose}>×</button>
        </div>
        <div className="settings-modal-body">
          {error && <div className="settings-error">{error}</div>}

          {share && (
            <div className="cc-share-link-row">
              <label className="cc-share-label">{t("ccDash.shareLink")}</label>
              <div className="cc-share-link-box">
                <a href={share.url} target="_blank" rel="noopener noreferrer" className="cc-share-link">
                  {shareUrl}
                </a>
                <button className="btn btn-small" onClick={handleCopy}>
                  {copied ? t("ccDash.shareCopied") : t("ccDash.shareCopy")}
                </button>
              </div>
            </div>
          )}

          <label className="cc-share-label">{t("ccDash.shareMode")}</label>
          <div className="cc-share-modes">
            <label className={`cc-share-mode ${mode === "public" ? "cc-share-mode-active" : ""}`}>
              <input
                type="radio"
                name="cc-share-mode"
                checked={mode === "public"}
                onChange={() => setMode("public")}
              />
              <span>🌐 {t("ccDash.shareModePublic")}</span>
            </label>
            <label className={`cc-share-mode ${mode === "password" ? "cc-share-mode-active" : ""}`}>
              <input
                type="radio"
                name="cc-share-mode"
                checked={mode === "password"}
                onChange={() => setMode("password")}
              />
              <span>🔒 {t("ccDash.shareModePassword")}</span>
            </label>
          </div>

          {mode === "password" && (
            <input
              type="password"
              className="cc-search-input cc-share-password"
              placeholder={
                share && share.mode === "password"
                  ? t("ccDash.sharePasswordKeep")
                  : t("ccDash.sharePasswordPlaceholder")
              }
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}

          <div className="cc-share-actions">
            {share && (
              <button className="btn btn-small btn-danger" onClick={handleDisable} disabled={busy}>
                {t("ccDash.shareDisable")}
              </button>
            )}
            <button className="btn btn-small" style={{ marginLeft: "auto" }} onClick={onClose} disabled={busy}>
              {t("ccDash.shareCancel")}
            </button>
            <button className="btn btn-small btn-approve" onClick={handleSave} disabled={busy}>
              {share ? t("ccDash.shareUpdate") : t("ccDash.shareEnable")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- Cost Center row (expandable members) ---------- */
function CostCenterRow({ cc, share, onOpenShare }: {
  cc: CostCenter;
  share: CostCenterShareInfo | null;
  onOpenShare: (cc: CostCenter) => void;
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <tr className="cc-table-row" onClick={() => setExpanded((v) => !v)} style={{ cursor: "pointer" }}>
        <td className="cc-td">
          <span className="cc-expand-icon">{expanded ? "▼" : "▶"}</span>
          <strong>{cc.name}</strong>
        </td>
        <td className="cc-td">
          <span className={`cc-state-badge cc-state-${cc.state}`}>{cc.state}</span>
        </td>
        <td className="cc-td">
          <div className="cc-resource-tags">
            {cc.resources.map((r, i) => (
              <span
                key={i}
                className="cc-resource-tag"
                style={{ borderColor: SOURCE_TYPE_COLORS[r.type] ?? "var(--border)" }}
              >
                <span className="cc-resource-type">{r.type}</span>
                {r.name}
              </span>
            ))}
          </div>
        </td>
        <td className="cc-td cc-td-num">
          <strong>{cc.member_count}</strong>
        </td>
        <td className="cc-td cc-td-share" onClick={(e) => e.stopPropagation()}>
          {share ? (
            <div className="cc-share-cell">
              <a
                href={share.url}
                target="_blank"
                rel="noopener noreferrer"
                className="cc-share-open-link"
                title={`${window.location.origin}${share.url}`}
              >
                {share.mode === "password" ? "🔒" : "🌐"} {t("ccDash.shareOpen")}
              </a>
              <button
                className="btn btn-small cc-share-gear"
                onClick={() => onOpenShare(cc)}
                title={t("ccDash.shareModalTitle")}
              >
                ⚙
              </button>
            </div>
          ) : (
            <button className="btn btn-small" onClick={() => onOpenShare(cc)}>
              ↗ {t("ccDash.shareBtn")}
            </button>
          )}
        </td>
      </tr>
      {expanded && cc.members.map((m) => (
        <tr key={m.login} className="cc-member-row">
          <td className="cc-td cc-td-member" colSpan={2}>
            <div className="cc-member-info">
              {m.avatar_url
                ? <img src={m.avatar_url} alt={m.login} className="cc-member-avatar" />
                : <div className="cc-member-avatar cc-member-avatar-placeholder" />}
              <a href={m.html_url} target="_blank" rel="noopener noreferrer" className="cc-member-login">
                {m.login}
              </a>
            </div>
          </td>
          <td className="cc-td">
            <span
              className="cc-resource-tag"
              style={{ borderColor: SOURCE_TYPE_COLORS[m.source_type] ?? "var(--border)" }}
            >
              <span className="cc-resource-type">{m.source_type}</span>
              {m.source_name}
            </span>
          </td>
          <td className="cc-td" />
          <td className="cc-td" />
        </tr>
      ))}
    </>
  );
}

/* ---------- User map table ---------- */
function UserMapTable({ users }: { users: UserCostCenterEntry[] }) {
  const { t } = useI18n();

  if (!users.length) return null;

  return (
    <div className="cc-table-wrap">
      <table className="cc-table">
        <thead>
          <tr>
            <th className="cc-th">{t("ccDash.colUser")}</th>
            <th className="cc-th">{t("ccDash.colCostCenters")}</th>
            <th className="cc-th">{t("ccDash.colSource")}</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.login} className="cc-table-row">
              <td className="cc-td">
                <div className="cc-member-info">
                  {u.avatar_url
                    ? <img src={u.avatar_url} alt={u.login} className="cc-member-avatar" />
                    : <div className="cc-member-avatar cc-member-avatar-placeholder" />}
                  <a href={u.html_url} target="_blank" rel="noopener noreferrer" className="cc-member-login">
                    {u.login}
                  </a>
                </div>
              </td>
              <td className="cc-td">
                <div className="cc-resource-tags">
                  {u.cost_centers.map((cc, i) => (
                    <span key={i} className="cc-cc-tag">{cc.name}</span>
                  ))}
                </div>
              </td>
              <td className="cc-td">
                <div className="cc-resource-tags">
                  {u.cost_centers.map((cc, i) => (
                    <span
                      key={i}
                      className="cc-resource-tag"
                      style={{ borderColor: SOURCE_TYPE_COLORS[cc.source_type] ?? "var(--border)" }}
                    >
                      <span className="cc-resource-type">{cc.source_type}</span>
                      {cc.source_name}
                    </span>
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- Main component ---------- */
export function CostCenterDashboard({ refreshKey: _ }: Props) {
  const { t } = useI18n();
  const ui = useUIState();

  const enterprise = ui.ccDashEnterprise;
  const costCenters = ui.ccDashCostCenters;
  const state = ui.ccDashState || "active";

  // Local search state — only flushed to UIState (triggering re-fetch) on blur or Enter
  const [searchInput, setSearchInput] = useState(ui.ccDashSearch);
  const [downloading, setDownloading] = useState(false);
  const commitSearch = useCallback(
    (v: string) => ui.patch({ ccDashSearch: v }),
    [ui.patch],
  );

  const handleDownload = useCallback(async () => {
    setDownloading(true);
    try {
      const url = `/api/data/cost-center-report${enterprise ? `?enterprise=${encodeURIComponent(enterprise)}` : ""}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `cc-report-${enterprise || "export"}.zip`;
      a.click();
      URL.revokeObjectURL(a.href);
    } finally {
      setDownloading(false);
    }
  }, [enterprise]);

  const { data, loading, refetch } = useCostCenterDashboard({
    enterprise, costCenters, state, search: ui.ccDashSearch,
  });
  const { syncing: ccSyncing, runSync } = useDatasetSync();
  const handleSync = useCallback(() => {
    runSync("cost_centers", refetch);
  }, [runSync, refetch]);

  // ---- Share settings ----
  const [shares, setShares] = useState<Record<string, CostCenterShareInfo>>({});
  const [shareModalCC, setShareModalCC] = useState<CostCenter | null>(null);
  const effectiveEnterprise = data?.selected_enterprise || enterprise;

  const fetchShares = useCallback(async (ent: string) => {
    if (!ent) return;
    try {
      const res = await fetch(`/api/data/cost-center-shares?enterprise=${encodeURIComponent(ent)}`);
      const json = await res.json();
      setShares(json.shares ?? {});
    } catch {
      setShares({});
    }
  }, []);

  useEffect(() => {
    fetchShares(effectiveEnterprise);
  }, [effectiveEnterprise, fetchShares]);

  const handleShareSave = useCallback(
    async (cc: CostCenter, mode: "public" | "password", password: string): Promise<string | null> => {
      try {
        const res = await fetch("/api/data/cost-center-share", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            enterprise: effectiveEnterprise,
            cc_id: cc.id,
            cc_name: cc.name,
            mode,
            password,
          }),
        });
        const json = await res.json();
        if (json.error) return json.error;
        await fetchShares(effectiveEnterprise);
        return null;
      } catch (e) {
        return String(e);
      }
    },
    [effectiveEnterprise, fetchShares],
  );

  const handleShareDisable = useCallback(
    async (cc: CostCenter) => {
      try {
        await fetch(
          `/api/data/cost-center-share?enterprise=${encodeURIComponent(effectiveEnterprise)}&cc_id=${encodeURIComponent(cc.id)}`,
          { method: "DELETE" },
        );
      } finally {
        await fetchShares(effectiveEnterprise);
      }
    },
    [effectiveEnterprise, fetchShares],
  );

  const setEnterprise = useCallback(
    (v: string) => ui.patch({ ccDashEnterprise: v }),
    [ui.patch],
  );
  const setCostCenters = useCallback(
    (v: string[]) => ui.patch({ ccDashCostCenters: v }),
    [ui.patch],
  );
  const setState = useCallback(
    (v: string) => ui.patch({ ccDashState: v }),
    [ui.patch],
  );

  if (loading) return <div className="dashboard-loading">{t("loading")}</div>;

  if (!data || data.no_data) {
    return <div className="dashboard-empty">{t("ccDash.noData")}</div>;
  }

  const enterpriseOptions = data.enterprises.map((e) => e.slug);

  // When enterprise changes via the dropdown, sync to state
  const handleEnterpriseSelect = (slug: string) => {
    setEnterprise(slug);
    setCostCenters([]);
  };

  return (
    <div className="csv-dashboard">
      {/* Filters */}
      <div className="csv-filters">
        {/* Enterprise selector */}
        {enterpriseOptions.length > 1 && (
          <div className="org-dropdown" style={{ minWidth: 160 }}>
            <select
              className="cc-native-select"
              value={enterprise || data.selected_enterprise}
              onChange={(e) => handleEnterpriseSelect(e.target.value)}
            >
              {enterpriseOptions.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
        )}

        {/* Cost Center filter */}
        <MultiSelect
          label={t("ccDash.allCostCenters")}
          options={data.cost_centers.map((cc) => cc.name)}
          selected={costCenters}
          onChange={setCostCenters}
        />

        {/* State filter */}
        <div className="org-dropdown" style={{ minWidth: 120 }}>
          <select
            className="cc-native-select"
            value={state}
            onChange={(e) => setState(e.target.value)}
          >
            <option value="active">{t("ccDash.stateActive")}</option>
            <option value="archived">{t("ccDash.stateArchived")}</option>
            <option value="all">{t("ccDash.stateAll")}</option>
          </select>
        </div>

        {/* Search — commits on blur or Enter */}
        <input
          type="text"
          className="cc-search-input"
          placeholder={t("ccDash.search")}
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onBlur={() => commitSearch(searchInput)}
          onKeyDown={(e) => { if (e.key === "Enter") commitSearch(searchInput); }}
        />

        {/* Sync + Download buttons — pushed to the right */}
        <button
          className="btn btn-small"
          style={{ marginLeft: "auto" }}
          onClick={handleSync}
          disabled={ccSyncing}
          title={t("ccDash.syncHint")}
        >
          {ccSyncing ? t("status.syncing") : `⟳ ${t("ccDash.sync")}`}
        </button>

        {/* Download report button */}
        <button
          className="btn btn-small cc-download-btn"
          style={{ marginLeft: 0 }}
          onClick={handleDownload}
          disabled={downloading}
          title={t("ccDash.downloadReport")}
        >
          {downloading ? t("ccDash.downloading") : `⬇ ${t("ccDash.downloadReport")}`}
        </button>
      </div>

      {/* KPI cards */}
      <div className="dashboard-kpi">
        <div className="stat-card">
          <div className="stat-value">{data.total_cost_centers}</div>
          <div className="stat-label">{t("ccDash.totalCostCenters")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{data.total_unique_members}</div>
          <div className="stat-label">{t("ccDash.totalMembers")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{data.enterprise_name || data.selected_enterprise}</div>
          <div className="stat-label">Enterprise</div>
        </div>
      </div>

      {/* Cost Centers → Members table */}
      <Section sectionKey="costcenters" title={t("ccDash.sectionCostCenters")}>
        <div className="cc-table-wrap">
          <table className="cc-table">
            <thead>
              <tr>
                <th className="cc-th">{t("ccDash.colCostCenter")}</th>
                <th className="cc-th">{t("ccDash.colState")}</th>
                <th className="cc-th">{t("ccDash.colResources")}</th>
                <th className="cc-th cc-th-num">{t("ccDash.colMembers")}</th>
                <th className="cc-th">{t("ccDash.colShare")}</th>
              </tr>
            </thead>
            <tbody>
              {data.cost_centers.map((cc) => (
                <CostCenterRow
                  key={cc.id}
                  cc={cc}
                  share={shares[cc.id] ?? null}
                  onOpenShare={setShareModalCC}
                />
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      {/* Share settings modal */}
      {shareModalCC && (
        <ShareModal
          cc={shareModalCC}
          share={shares[shareModalCC.id] ?? null}
          onSave={(mode, password) => handleShareSave(shareModalCC, mode, password)}
          onDisable={() => handleShareDisable(shareModalCC)}
          onClose={() => setShareModalCC(null)}
        />
      )}

      {/* User → Cost Centers mapping */}
      <Section sectionKey="usermap" title={t("ccDash.sectionUserMap")}>
        <UserMapTable users={data.user_map} />
      </Section>
    </div>
  );
}
