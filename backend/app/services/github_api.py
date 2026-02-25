"""
GitHub REST API client with auto-discovery.
Each instance is bound to a specific PAT token.
"""

import json

import httpx

from ..config import COPILOT_PRICING


class GitHubAPI:
    """GitHub REST API client bound to a specific PAT."""

    def __init__(self, token: str, base_url: str = "https://api.github.com"):
        self._token = token
        self._base_url = base_url
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self._token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # =========================================================================
    # Auto-Discovery
    # =========================================================================

    async def discover_user(self) -> dict:
        """Discover the authenticated user from PAT."""
        resp = await self.client.get("/user")
        resp.raise_for_status()
        return resp.json()

    async def discover_orgs(self) -> list[dict]:
        """Discover all organizations the PAT user belongs to."""
        orgs = []
        page = 1
        while True:
            resp = await self.client.get("/user/orgs", params={"per_page": 100, "page": page})
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            orgs.extend(batch)
            page += 1
        return orgs

    async def get_org_detail(self, org: str) -> dict:
        """Get detailed info for a specific organization."""
        resp = await self.client.get(f"/orgs/{org}")
        resp.raise_for_status()
        return resp.json()

    # =========================================================================
    # Copilot Billing & Plan Detection
    # =========================================================================

    async def get_copilot_billing(self, org: str) -> dict | None:
        """
        Get Copilot billing info for an org.
        Returns None if org doesn't have Copilot or PAT lacks permissions.
        Also auto-detects plan type and pricing.
        """
        try:
            resp = await self.client.get(f"/orgs/{org}/copilot/billing")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            billing = resp.json()

            # Auto-detect plan type from billing response
            plan_type = billing.get("plan_type", "business")
            if plan_type in COPILOT_PRICING:
                billing["_detected_price_per_seat"] = COPILOT_PRICING[plan_type]
            else:
                # Default to business pricing if unknown
                billing["_detected_price_per_seat"] = COPILOT_PRICING["business"]
            billing["_detected_plan_type"] = plan_type

            return billing
        except httpx.HTTPStatusError:
            return None

    # =========================================================================
    # Copilot Seats
    # =========================================================================

    async def get_copilot_seats(self, org: str) -> dict | None:
        """Get all Copilot seat assignments for an org."""
        try:
            all_seats = []
            page = 1
            total = 0
            while True:
                resp = await self.client.get(
                    f"/orgs/{org}/copilot/billing/seats",
                    params={"per_page": 100, "page": page},
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                data = resp.json()
                total = data.get("total_seats", 0)
                seats = data.get("seats", [])
                if not seats:
                    break
                all_seats.extend(seats)
                page += 1
            return {"total_seats": total, "seats": all_seats}
        except httpx.HTTPStatusError:
            return None

    # =========================================================================
    # Copilot Metrics (legacy /copilot/metrics endpoint)
    # =========================================================================

    async def get_copilot_metrics(self, org: str, since: str | None = None, until: str | None = None) -> list | None:
        """Get Copilot metrics for an org (legacy metrics API)."""
        try:
            params = {}
            if since:
                params["since"] = since
            if until:
                params["until"] = until
            resp = await self.client.get(f"/orgs/{org}/copilot/metrics", params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError:
            return None

    # =========================================================================
    # Billing: Premium Request Usage
    # Docs: https://docs.github.com/en/rest/billing/usage?apiVersion=2022-11-28
    # =========================================================================

    async def get_premium_request_usage(
        self,
        org: str,
        year: int | None = None,
        month: int | None = None,
        day: int | None = None,
    ) -> dict | None:
        """Get Copilot premium request usage for an org.
        API: GET /organizations/{org}/settings/billing/premium_request/usage
        Note: uses /organizations/ not /orgs/.
        """
        try:
            params: dict = {}
            if year is not None:
                params["year"] = year
            if month is not None:
                params["month"] = month
            if day is not None:
                params["day"] = day
            resp = await self.client.get(
                f"/organizations/{org}/settings/billing/premium_request/usage",
                params=params,
            )
            if resp.status_code in (404, 403):
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError:
            return None

    # =========================================================================
    # Copilot Usage Metrics Reports (new API with download_links)
    # Docs: https://docs.github.com/en/enterprise-cloud@latest/rest/copilot/copilot-usage-metrics
    # =========================================================================

    async def _fetch_report_download_links(self, path: str, params: dict | None = None) -> dict | None:
        """Call a usage metrics report endpoint and return the raw response with download_links.
        Returns dict with 'download_links', 'report_day' or 'report_start_day'/'report_end_day'.
        """
        try:
            resp = await self.client.get(path, params=params or {})
            if resp.status_code in (404, 403):
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError:
            return None

    async def _download_and_merge_reports(self, download_links: list[str]) -> list[dict]:
        """Download each signed URL and merge the results into a flat list.
        The download files use NDJSON format (one JSON object per line),
        not a standard JSON array. We parse each line individually.
        """
        all_records: list[dict] = []
        async with httpx.AsyncClient(timeout=60.0) as dl_client:
            for url in download_links:
                try:
                    resp = await dl_client.get(url)
                    resp.raise_for_status()
                    text = resp.text.strip()
                    if not text:
                        continue
                    # Try parsing as JSON array first (future-proofing)
                    if text.startswith("["):
                        data = json.loads(text)
                        if isinstance(data, list):
                            all_records.extend(data)
                        continue
                    # Parse as NDJSON (one JSON object per line)
                    for line in text.splitlines():
                        line = line.strip()
                        if line:
                            try:
                                record = json.loads(line)
                                if isinstance(record, dict):
                                    all_records.append(record)
                                elif isinstance(record, list):
                                    all_records.extend(record)
                            except json.JSONDecodeError:
                                continue
                except Exception:
                    # Skip individual download failures
                    continue
        return all_records

    async def _fetch_usage_report(self, path: str, params: dict | None = None) -> dict | None:
        """Fetch a usage metrics report: get download_links, download the actual data, return combined result."""
        meta = await self._fetch_report_download_links(path, params)
        if not meta or not meta.get("download_links"):
            return None

        records = await self._download_and_merge_reports(meta["download_links"])

        result = {
            "records": records,
            "total_records": len(records),
            "download_links_count": len(meta["download_links"]),
        }
        # Copy date metadata
        if "report_day" in meta:
            result["report_day"] = meta["report_day"]
        if "report_start_day" in meta:
            result["report_start_day"] = meta["report_start_day"]
        if "report_end_day" in meta:
            result["report_end_day"] = meta["report_end_day"]
        return result

    # --- Organization-level usage reports ---

    async def get_org_usage_report_28day(self, org: str) -> dict | None:
        """Get latest 28-day org-level Copilot usage report.
        API: GET /orgs/{org}/copilot/metrics/reports/organization-28-day/latest
        """
        return await self._fetch_usage_report(
            f"/orgs/{org}/copilot/metrics/reports/organization-28-day/latest"
        )

    async def get_org_usage_report_1day(self, org: str, day: str) -> dict | None:
        """Get org-level Copilot usage report for a specific day.
        API: GET /orgs/{org}/copilot/metrics/reports/organization-1-day?day={day}
        """
        return await self._fetch_usage_report(
            f"/orgs/{org}/copilot/metrics/reports/organization-1-day",
            params={"day": day},
        )

    async def get_org_users_usage_report_28day(self, org: str) -> dict | None:
        """Get latest 28-day org user-level Copilot usage report.
        API: GET /orgs/{org}/copilot/metrics/reports/users-28-day/latest
        """
        return await self._fetch_usage_report(
            f"/orgs/{org}/copilot/metrics/reports/users-28-day/latest"
        )

    async def get_org_users_usage_report_1day(self, org: str, day: str) -> dict | None:
        """Get org user-level Copilot usage report for a specific day.
        API: GET /orgs/{org}/copilot/metrics/reports/users-1-day?day={day}
        """
        return await self._fetch_usage_report(
            f"/orgs/{org}/copilot/metrics/reports/users-1-day",
            params={"day": day},
        )

    # --- Enterprise-level usage reports ---

    async def get_enterprise_usage_report_28day(self, enterprise: str) -> dict | None:
        """Get latest 28-day enterprise-level Copilot usage report.
        API: GET /enterprises/{enterprise}/copilot/metrics/reports/enterprise-28-day/latest
        """
        return await self._fetch_usage_report(
            f"/enterprises/{enterprise}/copilot/metrics/reports/enterprise-28-day/latest"
        )

    async def get_enterprise_usage_report_1day(self, enterprise: str, day: str) -> dict | None:
        """Get enterprise-level Copilot usage report for a specific day.
        API: GET /enterprises/{enterprise}/copilot/metrics/reports/enterprise-1-day?day={day}
        """
        return await self._fetch_usage_report(
            f"/enterprises/{enterprise}/copilot/metrics/reports/enterprise-1-day",
            params={"day": day},
        )

    async def get_enterprise_users_usage_report_28day(self, enterprise: str) -> dict | None:
        """Get latest 28-day enterprise user-level Copilot usage report.
        API: GET /enterprises/{enterprise}/copilot/metrics/reports/users-28-day/latest
        """
        return await self._fetch_usage_report(
            f"/enterprises/{enterprise}/copilot/metrics/reports/users-28-day/latest"
        )

    async def get_enterprise_users_usage_report_1day(self, enterprise: str, day: str) -> dict | None:
        """Get enterprise user-level Copilot usage report for a specific day.
        API: GET /enterprises/{enterprise}/copilot/metrics/reports/users-1-day?day={day}
        """
        return await self._fetch_usage_report(
            f"/enterprises/{enterprise}/copilot/metrics/reports/users-1-day",
            params={"day": day},
        )

    # =========================================================================
    # Copilot Seat Management (Operations)
    # =========================================================================

    async def add_copilot_seats(self, org: str, usernames: list[str]) -> dict | None:
        """Add Copilot seats for specified users.
        API: POST /orgs/{org}/copilot/billing/selected_users
        """
        try:
            resp = await self.client.post(
                f"/orgs/{org}/copilot/billing/selected_users",
                json={"selected_usernames": usernames},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            return {"error": str(e), "status_code": e.response.status_code}

    async def remove_copilot_seats(self, org: str, usernames: list[str]) -> dict | None:
        """Remove org-level Copilot seats for specified users.
        Only works for users assigned directly (no assigning_team).
        API: DELETE /orgs/{org}/copilot/billing/selected_users
        """
        try:
            resp = await self.client.request(
                "DELETE",
                f"/orgs/{org}/copilot/billing/selected_users",
                json={"selected_usernames": usernames},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            error_body = {}
            try:
                error_body = e.response.json()
            except Exception:
                error_body = {"text": e.response.text}
            return {"error": str(e), "status_code": e.response.status_code, "response": error_body}

    async def add_team_membership(self, org: str, team_slug: str, username: str, role: str = "member") -> dict:
        """Add or update team membership for a user.
        API: PUT /orgs/{org}/teams/{team_slug}/memberships/{username}
        Role can be 'member' (default) or 'maintainer'.
        """
        try:
            resp = await self.client.put(
                f"/orgs/{org}/teams/{team_slug}/memberships/{username}",
                json={"role": role},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            error_body = {}
            try:
                error_body = e.response.json()
            except Exception:
                error_body = {"text": e.response.text}
            return {"error": str(e), "status_code": e.response.status_code, "response": error_body}

    async def remove_team_membership(self, org: str, team_slug: str, username: str) -> dict:
        """Remove a user from a team, which revokes their team-assigned Copilot seat.
        API: DELETE /orgs/{org}/teams/{team_slug}/memberships/{username}
        Returns 204 on success.
        """
        try:
            resp = await self.client.request(
                "DELETE",
                f"/orgs/{org}/teams/{team_slug}/memberships/{username}",
            )
            resp.raise_for_status()
            return {"success": True, "username": username, "team": team_slug}
        except httpx.HTTPStatusError as e:
            error_body = {}
            try:
                error_body = e.response.json()
            except Exception:
                error_body = {"text": e.response.text}
            return {"error": str(e), "status_code": e.response.status_code, "response": error_body}
