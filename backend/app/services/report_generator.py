"""
Cost Center HTML report generator.

Produces self-contained HTML files (no external dependencies) with embedded
dark-theme CSS and server-generated SVG charts.  One file per cost center,
packaged into a ZIP archive.
"""
from __future__ import annotations

import io
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from html import escape

# ── colour palette ────────────────────────────────────────────────────────────

_TYPE_COLORS: dict[str, str] = {
    "Org":  "#539bf5",
    "User": "#3fb950",
    "Team": "#d29922",
}
_ACCENT  = "#539bf5"
_GREEN   = "#3fb950"
_YELLOW  = "#d29922"
_RED     = "#e5534b"
_MUTED   = "#768390"
_BG      = "#0d1117"
_CARD    = "#161b22"
_CARD2   = "#21262d"
_BORDER  = "#30363d"
_TEXT    = "#e6edf3"

# ── helpers ───────────────────────────────────────────────────────────────────

def _e(v) -> str:
    return escape(str(v) if v is not None else "")


def _money(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (ValueError, TypeError):
        return "-"


def _num(v) -> str:
    try:
        return f"{int(float(v)):,}"
    except (ValueError, TypeError):
        return str(v)


def _pct(v) -> str:
    try:
        return f"{float(v):.1f}%"
    except (ValueError, TypeError):
        return "-"


# ── SVG chart ─────────────────────────────────────────────────────────────────

def _svg_line_chart(
    data: list[dict],
    x_key: str,
    y_key: str,
    y_label: str,
    chart_id: str,
    w: int = 780,
    h: int = 200,
) -> str:
    if not data:
        return f'<p class="no-data">No trend data available.</p>'

    values = [float(d.get(y_key, 0) or 0) for d in data]
    labels = [str(d.get(x_key, "")) for d in data]
    n = len(values)

    PL, PR, PT, PB = 62, 16, 16, 46
    iw = w - PL - PR
    ih = h - PT - PB

    max_v = max(values) if values else 1
    min_v = min(values) if values else 0
    rng   = (max_v - min_v) or 1

    def xp(i: int) -> float:
        return PL + (i / max(n - 1, 1)) * iw

    def yp(v: float) -> float:
        return PT + ih - ((v - min_v) / rng) * ih

    pts = " ".join(f"{xp(i):.1f},{yp(v):.1f}" for i, v in enumerate(values))
    area = (
        f"{xp(0):.1f},{PT + ih:.1f} "
        + pts
        + f" {xp(n - 1):.1f},{PT + ih:.1f}"
    )

    # y-axis grid + labels
    n_ticks = 4
    grid_lines = ""
    for ti in range(n_ticks + 1):
        v = min_v + rng * ti / n_ticks
        y = yp(v)
        lbl = f"{v / 1000:.1f}k" if abs(v) >= 1000 else f"{v:.1f}"
        grid_lines += (
            f'<line x1="{PL}" y1="{y:.1f}" x2="{w - PR}" y2="{y:.1f}"'
            f' class="chart-grid" stroke-dasharray="4,3"/>'
            f'<text x="{PL - 5}" y="{y + 4:.1f}" text-anchor="end"'
            f' font-size="10" class="chart-label">{_e(lbl)}</text>'
        )

    # x-axis labels (at most 8)
    step = max(1, n // 8)
    x_labels = ""
    for i, lbl in enumerate(labels):
        if i % step == 0 or i == n - 1:
            x_labels += (
                f'<text x="{xp(i):.1f}" y="{PT + ih + 18}" text-anchor="middle"'
                f' font-size="10" class="chart-label">{_e(lbl)}</text>'
            )

    # dots only if few points
    dots = ""
    if n <= 60:
        dots = "".join(
            f'<circle cx="{xp(i):.1f}" cy="{yp(v):.1f}" r="2.5" fill="{_ACCENT}"/>'
            for i, v in enumerate(values)
        )

    gid = f"g{chart_id}"
    return (
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg"'
        f' style="width:100%;height:{h}px;display:block;">'
        f"<defs>"
        f'<linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{_ACCENT}" stop-opacity="0.25"/>'
        f'<stop offset="100%" stop-color="{_ACCENT}" stop-opacity="0.02"/>'
        f"</linearGradient>"
        f"</defs>"
        f'<rect class="chart-bg" width="{w}" height="{h}"/>'
        f"{grid_lines}"
        f"{x_labels}"
        f'<polygon points="{area}" fill="url(#{gid})"/>'
        f'<polyline points="{pts}" fill="none" stroke="{_ACCENT}" stroke-width="2"'
        f' stroke-linejoin="round" stroke-linecap="round"/>'
        f"{dots}"
        f'<text x="{PL + iw / 2:.0f}" y="{h - 4}" text-anchor="middle"'
        f' font-size="11" class="chart-label">{_e(y_label)}</text>'
        f"</svg>"
    )


# ── HTML building blocks ──────────────────────────────────────────────────────

def _kpi_card(label: str, value: str, sub: str = "") -> str:
    sub_html = f'<div class="kpi-sub">{_e(sub)}</div>' if sub else ""
    return (
        f'<div class="kpi-card">'
        f'<div class="kpi-value">{_e(value)}</div>'
        f'<div class="kpi-label">{_e(label)}</div>'
        f"{sub_html}"
        f"</div>"
    )


def _type_badge(source_type: str) -> str:
    color = _TYPE_COLORS.get(source_type, _MUTED)
    return (
        f'<span class="badge" style="border-color:{color};color:{color}">'
        f"{_e(source_type)}</span>"
    )


def _state_badge(state: str) -> str:
    color = _GREEN if state == "active" else (_MUTED if state == "archived" else _ACCENT)
    return f'<span class="badge" style="border-color:{color};color:{color}">{_e(state)}</span>'


# ── section renderers ─────────────────────────────────────────────────────────

def _section_resources(cc: dict) -> str:
    resources = cc.get("resources", [])
    rows = "".join(
        f"<tr><td class='td'>{_type_badge(r.get('type',''))}</td>"
        f"<td class='td'>{_e(r.get('name',''))}</td></tr>"
        for r in resources
    )
    return (
        f"<details open class='section'>"
        f"<summary class='section-title'>Resources <span class='count'>({len(resources)})</span></summary>"
        f"<div class='table-wrap'><table class='table'>"
        f"<thead><tr><th>Type</th><th>Name</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        f"</details>"
    )


def _section_members(cc: dict) -> str:
    members = cc.get("members", [])
    rows = ""
    for m in members:
        avatar = (
            f'<img src="{_e(m["avatar_url"])}" class="avatar" '
            f'onerror="this.style.display=\'none\'" />'
            if m.get("avatar_url")
            else '<div class="avatar-placeholder"></div>'
        )
        gh_url = m.get("html_url") or f'https://github.com/{_e(m["login"])}'
        rows += (
            f"<tr>"
            f"<td class='td'><div class='user-cell'>{avatar}"
            f"<a href='{_e(gh_url)}' target='_blank' class='user-link'>{_e(m['login'])}</a></div></td>"
            f"<td class='td'>{_type_badge(m.get('source_type',''))}</td>"
            f"<td class='td muted'>{_e(m.get('source_name',''))}</td>"
            f"</tr>"
        )
    return (
        f"<details open class='section'>"
        f"<summary class='section-title'>Members <span class='count'>({len(members)})</span></summary>"
        f"<div class='table-wrap'><table class='table'>"
        f"<thead><tr><th>User</th><th>Source Type</th><th>Source Name</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        f"</details>"
    )


def _section_premium(premium: dict, chart_id: str) -> str:
    if not premium.get("has_data"):
        return (
            "<details open class='section'>"
            "<summary class='section-title'>Premium Requests Analysis</summary>"
            "<p class='no-data'>No premium request CSV data available for this cost center.</p>"
            "</details>"
        )

    kpi = premium.get("kpi", {})
    dr  = premium.get("date_range", {})
    pr_date_str = dr.get("start", "") + " → " + dr.get("end", "")

    kpi_row = (
        f"<div class='kpi-row'>"
        f"{_kpi_card('Total Requests', _num(kpi.get('total_requests', 0)))}"
        f"{_kpi_card('Total Cost', _money(kpi.get('total_cost', 0)))}"
        f"{_kpi_card('Unique Users', _num(kpi.get('unique_users', 0)))}"
        f"{_kpi_card('Date Range', pr_date_str)}"
        f"</div>"
    )

    chart = _svg_line_chart(
        premium.get("daily_trend", []), "day", "requests",
        "Daily Premium Requests", f"{chart_id}pr",
    )

    # Model breakdown
    models     = premium.get("model_breakdown", [])
    total_req  = float(kpi.get("total_requests", 1)) or 1
    model_rows = ""
    for m in models:
        pct = round(m["requests"] / total_req * 100, 1)
        model_rows += (
            f"<tr>"
            f"<td class='td small'>{_e(m['model'])}</td>"
            f"<td class='td num'>{_num(m['requests'])}</td>"
            f"<td class='td num'>{_money(m['amount'])}</td>"
            f"<td class='td num'>{_num(m['user_count'])}</td>"
            f"<td class='td'>"
            f"<div class='pb-wrap'><div class='pb-fill' style='width:{min(pct,100):.1f}%'></div></div>"
            f"<span class='muted'>{pct:.1f}%</span></td>"
            f"</tr>"
        )
    model_table = (
        "<h3 class='sub-title'>Model Breakdown</h3>"
        "<div class='table-wrap'><table class='table'>"
        "<thead><tr><th>Model</th><th class='num'>Requests</th>"
        "<th class='num'>Cost</th><th class='num'>Users</th><th>Share</th></tr></thead>"
        f"<tbody>{model_rows}</tbody></table></div>"
    )

    # Per-user table
    user_rows = ""
    for u in premium.get("users", []):
        top_model = u["models"][0]["model"] if u.get("models") else "—"
        uname = u["user"]
        user_rows += (
            f"<tr>"
            f"<td class='td'><a href='https://github.com/{_e(uname)}'"
            f" target='_blank' class='user-link'>{_e(uname)}</a></td>"
            f"<td class='td muted small'>{_e(u.get('org',''))}</td>"
            f"<td class='td num'>{_num(u['requests'])}</td>"
            f"<td class='td num'>{_money(u['gross_amount'])}</td>"
            f"<td class='td num'>{_num(u.get('quota', 0))}</td>"
            f"<td class='td num'>{_pct(u.get('usage_pct', 0))}</td>"
            f"<td class='td num'>{u.get('days_active', 0)}</td>"
            f"<td class='td muted small'>{_e(top_model)}</td>"
            f"</tr>"
        )
    user_table = (
        "<h3 class='sub-title'>Per-User Details</h3>"
        "<div class='table-wrap'><table class='table'>"
        "<thead><tr><th>User</th><th>Org</th><th class='num'>Requests</th>"
        "<th class='num'>Cost</th><th class='num'>Quota</th>"
        "<th class='num'>Usage%</th><th class='num'>Active Days</th>"
        "<th>Top Model</th></tr></thead>"
        f"<tbody>{user_rows}</tbody></table></div>"
    )

    return (
        "<details open class='section'>"
        "<summary class='section-title'>💰 Premium Requests Analysis</summary>"
        f"{kpi_row}<div class='chart-wrap'>{chart}</div>"
        f"{model_table}{user_table}"
        "</details>"
    )


def _section_usage(usage: dict, chart_id: str) -> str:
    if not usage.get("has_data"):
        return (
            "<details open class='section'>"
            "<summary class='section-title'>Usage Report Analysis</summary>"
            "<p class='no-data'>No usage report CSV data available for this cost center.</p>"
            "</details>"
        )

    kpi = usage.get("kpi", {})
    dr  = usage.get("date_range", {})
    ur_date_str = dr.get("start", "") + " → " + dr.get("end", "")

    kpi_row = (
        f"<div class='kpi-row'>"
        f"{_kpi_card('Total Gross', _money(kpi.get('total_gross', 0)))}"
        f"{_kpi_card('Total Net', _money(kpi.get('total_net', 0)))}"
        f"{_kpi_card('Discount', _money(kpi.get('total_discount', 0)), 'saved')}"
        f"{_kpi_card('Unique Users', _num(kpi.get('unique_users', 0)))}"
        f"{_kpi_card('Date Range', ur_date_str)}"
        f"</div>"
    )

    chart = _svg_line_chart(
        usage.get("daily_trend", []), "day", "gross_amount",
        "Daily Gross Amount ($)", f"{chart_id}ur",
    )

    # SKU breakdown
    skus       = usage.get("sku_breakdown", [])
    total_gross = float(kpi.get("total_gross", 1)) or 1
    sku_rows   = ""
    for s in skus:
        pct = round(s["gross_amount"] / total_gross * 100, 1)
        sku_rows += (
            f"<tr>"
            f"<td class='td small'>{_e(s['sku'])}</td>"
            f"<td class='td num'>{_money(s['gross_amount'])}</td>"
            f"<td class='td num'>{_money(s['net_amount'])}</td>"
            f"<td class='td num'>{_num(s['user_count'])}</td>"
            f"<td class='td'>"
            f"<div class='pb-wrap'><div class='pb-fill' style='width:{min(pct,100):.1f}%'></div></div>"
            f"<span class='muted'>{pct:.1f}%</span></td>"
            f"</tr>"
        )
    sku_table = (
        "<h3 class='sub-title'>SKU Breakdown</h3>"
        "<div class='table-wrap'><table class='table'>"
        "<thead><tr><th>SKU</th><th class='num'>Gross</th>"
        "<th class='num'>Net</th><th class='num'>Users</th><th>Share</th></tr></thead>"
        f"<tbody>{sku_rows}</tbody></table></div>"
    )

    # Per-user table
    user_rows = ""
    for u in usage.get("users", []):
        top_sku = u["skus"][0]["sku"] if u.get("skus") else "—"
        uname = u["user"]
        user_rows += (
            f"<tr>"
            f"<td class='td'><a href='https://github.com/{_e(uname)}'"
            f" target='_blank' class='user-link'>{_e(uname)}</a></td>"
            f"<td class='td muted small'>{_e(u.get('org',''))}</td>"
            f"<td class='td num'>{_money(u['gross_amount'])}</td>"
            f"<td class='td num'>{_money(u['net_amount'])}</td>"
            f"<td class='td num'>{u.get('days_active', 0)}</td>"
            f"<td class='td muted small'>{_e(top_sku)}</td>"
            f"</tr>"
        )
    user_table = (
        "<h3 class='sub-title'>Per-User Details</h3>"
        "<div class='table-wrap'><table class='table'>"
        "<thead><tr><th>User</th><th>Org</th><th class='num'>Gross</th>"
        "<th class='num'>Net</th><th class='num'>Active Days</th>"
        "<th>Top SKU</th></tr></thead>"
        f"<tbody>{user_rows}</tbody></table></div>"
    )

    return (
        "<details open class='section'>"
        "<summary class='section-title'>📊 Usage Report Analysis</summary>"
        f"{kpi_row}<div class='chart-wrap'>{chart}</div>"
        f"{sku_table}{user_table}"
        "</details>"
    )


def _section_insights(cc: dict, premium: dict, usage: dict) -> str:
    member_logins  = {m["login"] for m in cc.get("members", [])}
    premium_users  = {u["user"] for u in premium.get("users", [])} if premium.get("has_data") else set()

    # Top 5 by premium cost
    all_users = premium.get("users", []) if premium.get("has_data") else []
    top5 = sorted(all_users, key=lambda u: -float(u.get("gross_amount", 0)))[:5]

    zero_premium = sorted(member_logins - premium_users) if premium.get("has_data") else []

    parts = []

    if top5:
        def _top5_row(i: int, u: dict) -> str:
            uname = u["user"]
            return (
                f"<tr>"
                f"<td class='td num muted'>{i}</td>"
                f"<td class='td'><a href='https://github.com/{_e(uname)}'"
                f" target='_blank' class='user-link'>{_e(uname)}</a></td>"
                f"<td class='td num'>{_money(u['gross_amount'])}</td>"
                f"<td class='td num'>{_num(u['requests'])}</td>"
                f"<td class='td num'>{_pct(u.get('usage_pct', 0))}</td>"
                f"</tr>"
            )
        rows = "".join(_top5_row(i, u) for i, u in enumerate(top5, 1))
        parts.append(
            "<div class='insight-card'>"
            "<h3 class='sub-title'>🏆 Top 5 by Premium Cost</h3>"
            "<div class='table-wrap'><table class='table'>"
            "<thead><tr><th>#</th><th>User</th><th class='num'>Cost</th>"
            "<th class='num'>Requests</th><th class='num'>Quota%</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
            "</div>"
        )

    if zero_premium:
        tags = " ".join(
            f"<a href='https://github.com/{_e(u)}' target='_blank' class='user-tag'>{_e(u)}</a>"
            for u in zero_premium
        )
        parts.append(
            "<div class='insight-card insight-warn'>"
            f"<h3 class='sub-title'>⚠️ Zero Premium Usage ({len(zero_premium)} member{'s' if len(zero_premium)!=1 else ''})</h3>"
            "<p class='insight-desc'>These cost center members had no premium request activity "
            "in the data period. Review their Copilot seat assignment.</p>"
            f"<div class='tag-list'>{tags}</div>"
            "</div>"
        )

    if not parts:
        return ""

    return (
        "<details open class='section'>"
        "<summary class='section-title'>🔍 Insights &amp; Analysis</summary>"
        + "".join(parts)
        + "</details>"
    )


# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
/* ── Themes ── */
:root {
  --bg:#ffffff; --card:#f6f8fa; --card2:#eaeef2; --border:#d0d7de;
  --text:#1f2328; --muted:#6e7781; --accent:#0969da; --green:#1a7f37;
  --warn-border:rgba(207,34,46,.25); --hover:rgba(0,0,0,.04);
}
[data-theme="dark"] {
  --bg:#0d1117; --card:#161b22; --card2:#21262d; --border:#30363d;
  --text:#e6edf3; --muted:#768390; --accent:#539bf5; --green:#3fb950;
  --warn-border:rgba(214,83,35,.35); --hover:rgba(255,255,255,.03);
}

*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{font-size:14px}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.5;min-height:100vh;
  transition:background .2s,color .2s}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}

/* ── Header ── */
.report-header{background:var(--card);border-bottom:1px solid var(--border);padding:24px 32px;
  transition:background .2s,border-color .2s}
.header-inner{max-width:1100px;margin:0 auto;display:flex;justify-content:space-between;
  align-items:flex-start;gap:24px;flex-wrap:wrap}
.header-brand{font-size:11px;text-transform:uppercase;letter-spacing:.08em;
  color:var(--muted);margin-bottom:6px}
.header-title{font-size:24px;font-weight:700;margin-bottom:8px}
.header-meta{display:flex;align-items:center;gap:12px;flex-wrap:wrap;font-size:13px;color:var(--muted)}
.header-right{text-align:right;flex-shrink:0}
.header-cost-label{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.header-cost-value{font-size:32px;font-weight:700;color:var(--text);margin:4px 0}
.header-gen{font-size:11px;color:var(--muted)}

/* ── Theme toggle ── */
.theme-btn{margin-top:10px;padding:5px 12px;border-radius:6px;border:1px solid var(--border);
  background:var(--card2);color:var(--text);font-size:12px;cursor:pointer;
  transition:background .2s,border-color .2s,color .2s}
.theme-btn:hover{border-color:var(--accent);color:var(--accent)}

/* ── Layout ── */
.main-content{max-width:1100px;margin:0 auto;padding:24px 32px;display:flex;
  flex-direction:column;gap:16px}

/* ── Sections ── */
details.section{background:var(--card);border:1px solid var(--border);border-radius:8px;
  overflow:hidden;transition:background .2s,border-color .2s}
details.section[open] summary.section-title{border-bottom:1px solid var(--border)}
summary.section-title{display:flex;align-items:center;gap:8px;padding:14px 18px;
  font-size:15px;font-weight:600;cursor:pointer;list-style:none;user-select:none}
summary.section-title::-webkit-details-marker{display:none}
summary.section-title::before{content:"▶";font-size:10px;color:var(--muted);
  transition:transform .2s;display:inline-block}
details[open] summary.section-title::before{transform:rotate(90deg)}
.count{font-size:12px;color:var(--muted);font-weight:400}
.section > *:not(summary){padding:16px 18px}

/* ── KPI ── */
.kpi-row{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:16px}
.kpi-card{background:var(--card2);border:1px solid var(--border);border-radius:6px;
  padding:14px 18px;min-width:130px;flex:1;transition:background .2s,border-color .2s}
.kpi-value{font-size:22px;font-weight:700;line-height:1.2}
.kpi-label{font-size:11px;color:var(--muted);margin-top:4px;text-transform:uppercase;letter-spacing:.05em}
.kpi-sub{font-size:11px;color:var(--green);margin-top:2px}

/* ── Tables ── */
.table-wrap{overflow-x:auto}
.table{width:100%;border-collapse:collapse;font-size:13px}
.table thead tr{background:var(--card2);border-bottom:1px solid var(--border)}
.table th{padding:8px 12px;text-align:left;font-weight:600;color:var(--muted);
  font-size:11px;text-transform:uppercase;letter-spacing:.05em;white-space:nowrap}
.table th.num{text-align:right}
.table td.td{padding:8px 12px;border-bottom:1px solid var(--border);vertical-align:middle}
.table td.num{text-align:right;font-variant-numeric:tabular-nums}
.table tbody tr:last-child td{border-bottom:none}
.table tbody tr:hover{background:var(--hover)}
.small{font-size:12px}
.muted{color:var(--muted)}

/* ── User cell ── */
.user-cell{display:flex;align-items:center;gap:8px}
.avatar{width:22px;height:22px;border-radius:50%;vertical-align:middle}
.avatar-placeholder{width:22px;height:22px;border-radius:50%;background:var(--border)}
.user-link{color:var(--accent)}

/* ── Badge ── */
.badge{display:inline-block;font-size:11px;font-weight:500;padding:1px 7px;
  border-radius:12px;border:1px solid;white-space:nowrap}

/* ── Progress bar ── */
.pb-wrap{display:inline-block;width:80px;height:6px;background:var(--border);
  border-radius:3px;vertical-align:middle;margin-right:6px}
.pb-fill{height:100%;background:var(--accent);border-radius:3px}

/* ── Chart ── */
.chart-wrap{border:1px solid var(--border);border-radius:6px;overflow:hidden;
  margin-bottom:16px;background:var(--bg);transition:background .2s,border-color .2s}
.chart-bg{fill:var(--bg);transition:fill .2s}
.chart-grid{stroke:var(--border)}
.chart-label{fill:var(--muted)}

/* ── Sub-titles ── */
.sub-title{font-size:13px;font-weight:600;color:var(--muted);text-transform:uppercase;
  letter-spacing:.06em;margin:16px 0 10px}

/* ── Insights ── */
.insight-card{background:var(--card2);border:1px solid var(--border);border-radius:6px;
  padding:16px;margin-bottom:12px;transition:background .2s,border-color .2s}
.insight-card:last-child{margin-bottom:0}
.insight-warn{border-color:var(--warn-border)}
.insight-desc{font-size:13px;color:var(--muted);margin:6px 0 10px}
.tag-list{display:flex;flex-wrap:wrap;gap:8px}
.user-tag{display:inline-block;padding:2px 10px;border-radius:12px;
  border:1px solid var(--border);font-size:12px;color:var(--accent)}
.user-tag:hover{border-color:var(--accent)}

/* ── No data ── */
.no-data{color:var(--muted);font-size:13px;padding:8px 0}

/* ── Footer ── */
.report-footer{max-width:1100px;margin:16px auto;padding:0 32px 32px;
  font-size:11px;color:var(--muted)}
"""

# ── aggregation helpers (mirrors data.py logic on pre-filtered records) ────────

def _build_premium_section(records: list[dict]) -> dict:
    if not records:
        return {"has_data": False}

    dates = [r.get("date", "") for r in records if r.get("date")]
    date_range = {"start": min(dates), "end": max(dates)} if dates else {}

    user_map: dict[str, dict] = defaultdict(lambda: {
        "requests": 0.0, "gross_amount": 0.0, "net_amount": 0.0,
        "models": defaultdict(float), "days_active": set(), "org": "", "quota": 0,
    })
    day_map:   dict[str, dict] = defaultdict(lambda: {"requests": 0.0, "amount": 0.0, "users": set()})
    model_map: dict[str, dict] = defaultdict(lambda: {"requests": 0.0, "amount": 0.0, "users": set()})

    for r in records:
        user  = r.get("username", "")
        qty   = float(r.get("quantity", 0) or 0)
        gross = float(r.get("gross_amount", 0) or 0)
        net   = float(r.get("net_amount", 0) or 0)
        model = r.get("model", "unknown") or "unknown"
        day   = r.get("date", "")

        u = user_map[user]
        u["requests"]     += qty
        u["gross_amount"] += gross
        u["net_amount"]   += net
        u["models"][model]+= qty
        u["days_active"].add(day)
        u["org"] = r.get("organization", "") or ""
        try:
            u["quota"] = int(r.get("total_monthly_quota", 0) or 0)
        except (ValueError, TypeError):
            pass

        dm = day_map[day]
        dm["requests"] += qty
        dm["amount"]   += gross
        dm["users"].add(user)

        mm = model_map[model]
        mm["requests"] += qty
        mm["amount"]   += gross
        mm["users"].add(user)

    users = []
    for username, info in sorted(user_map.items(), key=lambda x: -x[1]["requests"]):
        models = [{"model": m, "requests": q}
                  for m, q in sorted(info["models"].items(), key=lambda x: -x[1])]
        users.append({
            "user": username, "org": info["org"],
            "requests": round(info["requests"], 2),
            "gross_amount": round(info["gross_amount"], 4),
            "net_amount": round(info["net_amount"], 4),
            "days_active": len(info["days_active"]),
            "quota": info["quota"],
            "usage_pct": round(info["requests"] / info["quota"] * 100, 1) if info["quota"] > 0 else 0,
            "models": models,
        })

    daily_trend = [
        {"day": d, "requests": round(v["requests"], 2),
         "amount": round(v["amount"], 4), "active_users": len(v["users"])}
        for d, v in sorted(day_map.items())
    ]
    model_breakdown = [
        {"model": m, "requests": round(v["requests"], 2),
         "amount": round(v["amount"], 4), "user_count": len(v["users"])}
        for m, v in sorted(model_map.items(), key=lambda x: -x[1]["requests"])
    ]

    total_req  = sum(u["requests"] for u in users)
    total_cost = sum(u["gross_amount"] for u in users)

    return {
        "has_data": True,
        "date_range": date_range,
        "kpi": {
            "total_requests": round(total_req, 2),
            "total_cost": round(total_cost, 4),
            "unique_users": len(users),
        },
        "daily_trend": daily_trend,
        "model_breakdown": model_breakdown,
        "users": users,
    }


def _build_usage_section(records: list[dict]) -> dict:
    if not records:
        return {"has_data": False}

    dates = [r.get("date", "") for r in records if r.get("date")]
    date_range = {"start": min(dates), "end": max(dates)} if dates else {}

    user_map: dict[str, dict] = defaultdict(lambda: {
        "gross": 0.0, "net": 0.0, "quantity": 0.0,
        "org": "", "skus": defaultdict(float), "days_active": set(),
    })
    day_map: dict[str, dict] = defaultdict(lambda: {"gross": 0.0, "net": 0.0, "users": set()})
    sku_map: dict[str, dict] = defaultdict(lambda: {"gross": 0.0, "net": 0.0, "users": set(), "qty": 0.0})

    for r in records:
        user  = r.get("username", "")
        gross = float(r.get("gross_amount", 0) or 0)
        net   = float(r.get("net_amount", 0) or 0)
        qty   = float(r.get("quantity", 0) or 0)
        sku   = r.get("sku", "unknown") or "unknown"
        day   = r.get("date", "")

        um = user_map[user]
        um["gross"]    += gross
        um["net"]      += net
        um["quantity"] += qty
        um["org"]       = r.get("organization", "") or ""
        um["skus"][sku]+= gross
        um["days_active"].add(day)

        dm = day_map[day]
        dm["gross"] += gross
        dm["net"]   += net
        dm["users"].add(user)

        sm = sku_map[sku]
        sm["gross"] += gross
        sm["net"]   += net
        sm["qty"]   += qty
        sm["users"].add(user)

    users = []
    for username, info in sorted(user_map.items(), key=lambda x: -x[1]["gross"]):
        skus = [{"sku": s, "amount": round(a, 4)}
                for s, a in sorted(info["skus"].items(), key=lambda x: -x[1])]
        users.append({
            "user": username, "org": info["org"],
            "gross_amount": round(info["gross"], 4),
            "net_amount": round(info["net"], 4),
            "quantity": round(info["quantity"], 4),
            "days_active": len(info["days_active"]),
            "skus": skus,
        })

    daily_trend = [
        {"day": d, "gross_amount": round(v["gross"], 4),
         "net_amount": round(v["net"], 4), "active_users": len(v["users"])}
        for d, v in sorted(day_map.items())
    ]
    sku_breakdown = [
        {"sku": s, "gross_amount": round(v["gross"], 4),
         "net_amount": round(v["net"], 4),
         "quantity": round(v["qty"], 4), "user_count": len(v["users"])}
        for s, v in sorted(sku_map.items(), key=lambda x: -x[1]["gross"])
    ]

    total_gross    = sum(float(r.get("gross_amount", 0) or 0) for r in records)
    total_net      = sum(float(r.get("net_amount", 0) or 0) for r in records)
    total_discount = sum(float(r.get("discount_amount", 0) or 0) for r in records)

    return {
        "has_data": True,
        "date_range": date_range,
        "kpi": {
            "total_gross": round(total_gross, 4),
            "total_net": round(total_net, 4),
            "total_discount": round(total_discount, 4),
            "unique_users": len(users),
        },
        "daily_trend": daily_trend,
        "sku_breakdown": sku_breakdown,
        "users": users,
    }


# ── main HTML renderer ────────────────────────────────────────────────────────

def _render_html(
    enterprise: str,
    enterprise_name: str,
    cc: dict,
    premium: dict,
    usage: dict,
    generated_at: str,
    chart_id: str,
) -> str:
    name         = cc.get("name", "Unknown")
    state        = cc.get("state", "active")
    member_count = cc.get("member_count", len(cc.get("members", [])))

    # overall date range
    all_dates: list[str] = []
    for sect in (premium, usage):
        dr = sect.get("date_range", {})
        for k in ("start", "end"):
            if dr.get(k):
                all_dates.append(dr[k])
    date_range_str = f"{min(all_dates)} → {max(all_dates)}" if all_dates else "No data"

    # total cost
    total_cost = 0.0
    if premium.get("has_data"):
        total_cost += float(premium.get("kpi", {}).get("total_cost", 0) or 0)
    if usage.get("has_data"):
        total_cost += float(usage.get("kpi", {}).get("total_gross", 0) or 0)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cost Center Report · {_e(name)}</title>
<style>{_CSS}</style>
<script>
(function(){{
  var t = localStorage.getItem('report-theme');
  if (t === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
}})();
</script>
</head>
<body>
<header class="report-header">
  <div class="header-inner">
    <div class="header-left">
      <div class="header-brand">OctoFinance · Cost Center Report</div>
      <h1 class="header-title">{_e(name)}</h1>
      <div class="header-meta">
        <span>Enterprise: <strong>{_e(enterprise_name or enterprise)}</strong></span>
        {_state_badge(state)}
        <span>{_e(member_count)} members</span>
        <span>Period: {_e(date_range_str)}</span>
      </div>
    </div>
    <div class="header-right">
      <div class="header-cost-label">Total Cost</div>
      <div class="header-cost-value">{_money(total_cost)}</div>
      <div class="header-gen">Generated {_e(generated_at)}</div>
      <button id="theme-btn" class="theme-btn" onclick="toggleTheme()">🌙 Dark</button>
    </div>
  </div>
</header>

<main class="main-content">
  {_section_resources(cc)}
  {_section_members(cc)}
  {_section_premium(premium, chart_id)}
  {_section_usage(usage, chart_id)}
  {_section_insights(cc, premium, usage)}
</main>

<footer class="report-footer">
  Generated by <strong>OctoFinance</strong> on {_e(generated_at)} ·
  Enterprise: {_e(enterprise_name or enterprise)} · Cost Center: {_e(name)}
</footer>
<script>
function toggleTheme() {{
  var d = document.documentElement;
  var isDark = d.getAttribute('data-theme') === 'dark';
  d.setAttribute('data-theme', isDark ? '' : 'dark');
  document.getElementById('theme-btn').textContent = isDark ? '🌙 Dark' : '☀️ Light';
  localStorage.setItem('report-theme', isDark ? '' : 'dark');
}}
(function() {{
  var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  document.getElementById('theme-btn').textContent = isDark ? '☀️ Light' : '🌙 Dark';
}})();
</script>
</body>
</html>"""


# ── public API ────────────────────────────────────────────────────────────────

def generate_report_zip(
    enterprise: str,
    enterprise_name: str,
    cost_centers: list[dict],
    all_premium_records: list[dict],
    all_usage_records: list[dict],
) -> bytes:
    """Return ZIP bytes with one self-contained HTML file per cost center."""
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, cc in enumerate(cost_centers):
            cc_name = cc.get("name", f"cc_{idx}")

            pr_records = [r for r in all_premium_records if r.get("cost_center_name") == cc_name]
            ur_records = [r for r in all_usage_records  if r.get("cost_center_name") == cc_name]

            premium = _build_premium_section(pr_records)
            usage   = _build_usage_section(ur_records)

            html = _render_html(
                enterprise=enterprise,
                enterprise_name=enterprise_name,
                cc=cc,
                premium=premium,
                usage=usage,
                generated_at=generated_at,
                chart_id=str(idx),
            )

            safe_name = (
                cc_name.replace("/", "_").replace("\\", "_")
                       .replace(" ", "_").replace(":", "_")
            )
            zf.writestr(f"{safe_name}.html", html.encode("utf-8"))

    return buf.getvalue()
