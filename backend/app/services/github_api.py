"""
GitHub REST API client with auto-discovery.
Each instance is bound to a specific PAT token.
"""

import json
import logging

import httpx

from ..config import COPILOT_PRICING

logger = logging.getLogger(__name__)


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
                    "Content-Type": "application/json",
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

    async def discover_enterprises(self) -> list[dict]:
        """Discover all enterprises the authenticated user belongs to.
        API: GET /user/enterprise-memberships
        Returns list of dicts with enterprise slug, name, and role.
        """
        try:
            memberships = []
            page = 1
            while True:
                resp = await self.client.get(
                    "/user/enterprise-memberships",
                    params={"per_page": 100, "page": page},
                )
                if resp.status_code in (404, 403):
                    return []
                resp.raise_for_status()
                batch = resp.json()
                if not batch:
                    break
                memberships.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
            return [
                {
                    "slug": m.get("enterprise", {}).get("slug", ""),
                    "name": m.get("enterprise", {}).get("name", ""),
                    "id": m.get("enterprise", {}).get("id"),
                    "role": m.get("role", ""),
                }
                for m in memberships
                if m.get("enterprise", {}).get("slug")
            ]
        except Exception:
            return []

    async def get_org_members(self, org: str) -> list[dict]:
        """Get all members of an organization.
        API: GET /orgs/{org}/members
        Returns list of member objects with login, avatar_url, html_url.
        """
        try:
            members = []
            page = 1
            while True:
                resp = await self.client.get(
                    f"/orgs/{org}/members",
                    params={"per_page": 100, "page": page},
                )
                if resp.status_code in (404, 403):
                    return []
                resp.raise_for_status()
                batch = resp.json()
                if not batch:
                    break
                members.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
            return members
        except Exception:
            return []

    async def get_team_members(self, org: str, team_slug: str) -> list[dict]:
        """Get all members of a team within an organization.
        API: GET /orgs/{org}/teams/{team_slug}/members
        Returns list of member objects with login, avatar_url, html_url.
        """
        try:
            members = []
            page = 1
            while True:
                resp = await self.client.get(
                    f"/orgs/{org}/teams/{team_slug}/members",
                    params={"per_page": 100, "page": page},
                )
                if resp.status_code in (404, 403):
                    return []
                resp.raise_for_status()
                batch = resp.json()
                if not batch:
                    break
                members.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
            return members
        except Exception:
            return []

    async def get_enterprise_cost_centers(self, enterprise: str) -> list[dict]:
        """List all cost centers for an enterprise (active + archived).
        API: GET /enterprises/{enterprise}/settings/billing/cost-centers
        Uses API version 2026-03-10.
        Note: 'state' only accepts 'active' or 'archived' — 'all' returns 400.
        We fetch both states and merge them.
        """
        _headers = {"X-GitHub-Api-Version": "2026-03-10"}
        results = []
        seen_ids: set[str] = set()

        for state in ("active", "archived"):
            page = 1
            while True:
                resp = await self.client.get(
                    f"/enterprises/{enterprise}/settings/billing/cost-centers",
                    params={"per_page": 100, "page": page, "state": state},
                    headers=_headers,
                )
                if resp.status_code in (404, 403, 400):
                    break
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    batch = data
                else:
                    batch = data.get("costCenters") or data.get("cost_centers") or []
                if not batch:
                    break
                for item in batch:
                    cc_id = item.get("id", "")
                    if cc_id not in seen_ids:
                        seen_ids.add(cc_id)
                        results.append(item)
                if len(batch) < 100:
                    break
                page += 1

        return results

    async def get_enterprise_orgs(self, enterprise: str) -> list[dict]:
        """List organizations owned by an enterprise.
        API: GET /enterprises/{enterprise}/organizations
        """
        try:
            orgs = []
            page = 1
            while True:
                resp = await self.client.get(
                    f"/enterprises/{enterprise}/organizations",
                    params={"per_page": 100, "page": page},
                )
                if resp.status_code in (404, 403):
                    return []
                resp.raise_for_status()
                batch = resp.json()
                if not batch:
                    break
                orgs.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
            return orgs
        except Exception:
            return []

    async def add_cost_center_resources(
        self,
        enterprise: str,
        cost_center_id: str,
        users: list[str] | None = None,
        organizations: list[str] | None = None,
        repositories: list[str] | None = None,
    ) -> dict:
        """Add users, organizations, or repositories to an enterprise cost center."""
        body: dict = {}
        if users:
            body["users"] = users
        if organizations:
            body["organizations"] = organizations
        if repositories:
            body["repositories"] = repositories

        resp = await self.client.post(
            f"/enterprises/{enterprise}/settings/billing/cost-centers/{cost_center_id}/resource",
            json=body,
            headers={"X-GitHub-Api-Version": "2026-03-10"},
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {"success": True}

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
    # Billing: AI Credit Usage (UBB)
    # Docs: https://docs.github.com/en/enterprise-cloud@latest/rest/billing/usage
    # =========================================================================

    async def get_ai_credit_usage(
        self,
        org: str,
        year: int | None = None,
        month: int | None = None,
        day: int | None = None,
    ) -> dict | None:
        """Get Copilot AI credit usage for an org (UBB - Usage-Based Billing).
        API: GET /organizations/{org}/settings/billing/ai_credit/usage
        Note: uses /organizations/ not /orgs/.
        This is the current billing usage endpoint (UBB, effective June 2026).
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
                f"/organizations/{org}/settings/billing/ai_credit/usage",
                params=params,
                headers={"X-GitHub-Api-Version": "2026-03-10"},
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

    # =========================================================================
    # Budget API (UBB - Usage-Based Billing)
    # Docs: https://docs.github.com/en/rest/billing/budgets?apiVersion=2026-03-10
    # Note: Requires API version 2026-03-10 and PAT with manage_billing:copilot scope
    # =========================================================================

    async def get_budgets(
        self,
        entity_type: str,
        entity_name: str,
        scope: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
    ) -> dict | None:
        """Get budgets for an enterprise or organization.

        Args:
            entity_type: 'enterprise' or 'organization'
            entity_name: Enterprise slug or organization name
            scope: Optional filter by budget scope:
                   - 'multi_user_customer' (Universal user-level budget)
                   - 'user' (Individual user-level budget)
                   - 'enterprise' (Enterprise budget)
                   - 'cost_center' (Cost center budget)
                   - 'organization' (Organization budget)
                   - 'repository' (Repository budget)
            page: Optional page number (default 1).
            per_page: Optional results per page (max 100, default 10).

        API: GET /enterprises/{slug}/settings/billing/budgets
             or GET /organizations/{org}/settings/billing/budgets
        """
        try:
            if entity_type == "enterprise":
                path = f"/enterprises/{entity_name}/settings/billing/budgets"
            else:
                path = f"/organizations/{entity_name}/settings/billing/budgets"

            params: dict = {}
            if scope:
                params["scope"] = scope
            if page is not None:
                params["page"] = page
            if per_page is not None:
                params["per_page"] = per_page

            # Log request
            logger.info(f"[GET_BUDGETS] REQUEST: GET {self._base_url}{path}")
            logger.debug(f"[GET_BUDGETS] Params: {params}")
            logger.debug(f"[GET_BUDGETS] Headers: X-GitHub-Api-Version=2026-03-10")

            resp = await self.client.get(
                path,
                params=params,
                headers={"X-GitHub-Api-Version": "2026-03-10"},
            )

            # Log response
            logger.info(f"[GET_BUDGETS] RESPONSE: {resp.status_code} {resp.reason_phrase}")
            logger.debug(f"[GET_BUDGETS] Response Headers: {dict(resp.headers)}")

            if resp.status_code in (404, 403):
                logger.warning(f"[GET_BUDGETS] Failed with {resp.status_code}, returning None")
                logger.debug(f"[GET_BUDGETS] Response Body: {resp.text}")
                return None

            resp.raise_for_status()
            result = resp.json()
            logger.info(f"[GET_BUDGETS] Success - Found {result.get('total_count', 0)} budgets")
            logger.debug(f"[GET_BUDGETS] Response Body: {json.dumps(result, indent=2)}")
            return result
        except httpx.HTTPStatusError as e:
            logger.error(f"[GET_BUDGETS] HTTPStatusError: {e}")
            logger.debug(f"[GET_BUDGETS] Error Response: {e.response.text}")
            return {"error": str(e), "status_code": e.response.status_code}

    async def get_all_budgets_paginated(
        self,
        entity_type: str,
        entity_name: str,
        scope: str | None = None,
    ) -> list[dict]:
        """Fetch all budgets across pages for an enterprise/organization.

        Returns a flat list of budget dicts (empty list on error or no data).
        """
        all_budgets: list[dict] = []
        page = 1
        while True:
            result = await self.get_budgets(
                entity_type, entity_name, scope=scope, page=page, per_page=100
            )
            if not isinstance(result, dict) or result.get("error"):
                break
            batch = result.get("budgets", []) or []
            all_budgets.extend(batch)
            if not result.get("has_next_page") or not batch:
                break
            page += 1
        return all_budgets

    async def get_budget(
        self,
        entity_type: str,
        entity_name: str,
        budget_id: str,
    ) -> dict | None:
        """Get a specific budget by ID.

        Args:
            entity_type: 'enterprise' or 'organization'
            entity_name: Enterprise slug or organization name
            budget_id: Budget ID

        API: GET /enterprises/{slug}/settings/billing/budgets/{budget_id}
             or GET /organizations/{org}/settings/billing/budgets/{budget_id}
        """
        try:
            if entity_type == "enterprise":
                path = f"/enterprises/{entity_name}/settings/billing/budgets/{budget_id}"
            else:
                path = f"/organizations/{entity_name}/settings/billing/budgets/{budget_id}"

            # Log request
            logger.info(f"[GET_BUDGET] REQUEST: GET {self._base_url}{path}")
            logger.debug(f"[GET_BUDGET] Budget ID: {budget_id}")

            resp = await self.client.get(
                path,
                headers={"X-GitHub-Api-Version": "2026-03-10"},
            )

            # Log response
            logger.info(f"[GET_BUDGET] RESPONSE: {resp.status_code} {resp.reason_phrase}")

            if resp.status_code in (404, 403):
                logger.warning(f"[GET_BUDGET] Failed with {resp.status_code}, returning None")
                return None

            resp.raise_for_status()
            result = resp.json()
            logger.debug(f"[GET_BUDGET] Response Body: {json.dumps(result, indent=2)}")
            return result
        except httpx.HTTPStatusError as e:
            logger.error(f"[GET_BUDGET] HTTPStatusError: {e}")
            return {"error": str(e), "status_code": e.response.status_code}

    async def create_budget(
        self,
        entity_type: str,
        entity_name: str,
        budget_data: dict,
    ) -> dict | None:
        """Create a new budget.

        Args:
            entity_type: 'enterprise' or 'organization'
            entity_name: Enterprise slug or organization name
            budget_data: Budget configuration dict with fields:
                - budget_type: 'BundlePricing' for AI credits
                - budget_product_sku: 'ai_credits'
                - budget_scope: 'multi_user_customer', 'user', 'enterprise', 'cost_center', etc.
                - budget_entity_name: Entity name (enterprise/org/username)
                - budget_amount: Budget amount in USD
                - prevent_further_usage: true to block usage when limit is reached
                - user: (optional) GitHub username for 'user' scope
                - budget_alerting: (optional) Alert configuration
                - budget_thresholds: (optional) Alert thresholds

        API: POST /enterprises/{slug}/settings/billing/budgets
             or POST /organizations/{org}/settings/billing/budgets
        """
        try:
            if entity_type == "enterprise":
                path = f"/enterprises/{entity_name}/settings/billing/budgets"
            else:
                path = f"/organizations/{entity_name}/settings/billing/budgets"

            # Log request
            logger.info(f"[CREATE_BUDGET] REQUEST: POST {self._base_url}{path}")
            logger.debug(f"[CREATE_BUDGET] Request Body: {json.dumps(budget_data, indent=2)}")

            resp = await self.client.post(
                path,
                json=budget_data,
                headers={"X-GitHub-Api-Version": "2026-03-10"},
            )

            # Log response
            logger.info(f"[CREATE_BUDGET] RESPONSE: {resp.status_code} {resp.reason_phrase}")
            logger.debug(f"[CREATE_BUDGET] Response Body: {resp.text}")

            resp.raise_for_status()
            result = resp.json()
            logger.info(f"[CREATE_BUDGET] Success - Created budget ID: {result.get('budget', {}).get('id', 'unknown')}")
            return result
        except httpx.HTTPStatusError as e:
            error_body = {}
            try:
                error_body = e.response.json()
                logger.error(f"[CREATE_BUDGET] Error (JSON): {json.dumps(error_body, indent=2)}")
            except Exception:
                error_body = {"text": e.response.text}
                logger.error(f"[CREATE_BUDGET] Error (Text): {error_body['text']}")
            logger.error(f"[CREATE_BUDGET] HTTPStatusError: {e}")
            return {"error": str(e), "status_code": e.response.status_code, "response": error_body}

    async def update_budget(
        self,
        entity_type: str,
        entity_name: str,
        budget_id: str,
        budget_data: dict,
    ) -> dict | None:
        """Update an existing budget.

        Args:
            entity_type: 'enterprise' or 'organization'
            entity_name: Enterprise slug or organization name
            budget_id: Budget ID to update
            budget_data: Budget update fields (budget_amount, prevent_further_usage, budget_alerting)

        Note: Cannot change budget_scope. Delete and recreate if scope needs to change.

        API: PATCH /enterprises/{slug}/settings/billing/budgets/{budget_id}
             or PATCH /organizations/{org}/settings/billing/budgets/{budget_id}
        """
        try:
            if entity_type == "enterprise":
                path = f"/enterprises/{entity_name}/settings/billing/budgets/{budget_id}"
            else:
                path = f"/organizations/{entity_name}/settings/billing/budgets/{budget_id}"

            # Log request
            logger.info(f"[UPDATE_BUDGET] REQUEST: PATCH {self._base_url}{path}")
            logger.debug(f"[UPDATE_BUDGET] Budget ID: {budget_id}")
            logger.debug(f"[UPDATE_BUDGET] Request Body: {json.dumps(budget_data, indent=2)}")

            resp = await self.client.patch(
                path,
                json=budget_data,
                headers={"X-GitHub-Api-Version": "2026-03-10"},
            )

            # Log response
            logger.info(f"[UPDATE_BUDGET] RESPONSE: {resp.status_code} {resp.reason_phrase}")
            logger.debug(f"[UPDATE_BUDGET] Response Body: {resp.text}")

            resp.raise_for_status()
            result = resp.json()
            logger.info(f"[UPDATE_BUDGET] Success - Updated budget {budget_id}")
            return result
        except httpx.HTTPStatusError as e:
            error_body = {}
            try:
                error_body = e.response.json()
                logger.error(f"[UPDATE_BUDGET] Error (JSON): {json.dumps(error_body, indent=2)}")
            except Exception:
                error_body = {"text": e.response.text}
                logger.error(f"[UPDATE_BUDGET] Error (Text): {error_body['text']}")
            logger.error(f"[UPDATE_BUDGET] HTTPStatusError: {e}")
            return {"error": str(e), "status_code": e.response.status_code, "response": error_body}

    async def delete_budget(
        self,
        entity_type: str,
        entity_name: str,
        budget_id: str,
    ) -> dict:
        """Delete a budget.

        Args:
            entity_type: 'enterprise' or 'organization'
            entity_name: Enterprise slug or organization name
            budget_id: Budget ID to delete

        Warning: Ensure there is another budget as fallback before deleting.
        Deleting user-level budgets may leave users without personal budget constraints.

        IMPORTANT: The authenticated user must be an ENTERPRISE ADMIN (not just billing manager)
        to delete budgets.

        API: DELETE /enterprises/{slug}/settings/billing/budgets/{budget_id}
             or DELETE /organizations/{org}/settings/billing/budgets/{budget_id}
        Returns: 200 OK with JSON response containing message and id
        """
        try:
            if entity_type == "enterprise":
                path = f"/enterprises/{entity_name}/settings/billing/budgets/{budget_id}"
            else:
                path = f"/organizations/{entity_name}/settings/billing/budgets/{budget_id}"

            full_url = f"{self._base_url}{path}"

            # Log detailed request information
            logger.info(f"[DELETE_BUDGET] ======== DELETE BUDGET REQUEST ========")
            logger.info(f"[DELETE_BUDGET] Method: DELETE")
            logger.info(f"[DELETE_BUDGET] URL: {full_url}")
            logger.info(f"[DELETE_BUDGET] Entity Type: {entity_type}")
            logger.info(f"[DELETE_BUDGET] Entity Name: {entity_name}")
            logger.info(f"[DELETE_BUDGET] Budget ID: {budget_id}")
            logger.debug(f"[DELETE_BUDGET] Headers: X-GitHub-Api-Version=2026-03-10, Authorization=Bearer ***")

            resp = await self.client.request(
                "DELETE",
                path,
                headers={"X-GitHub-Api-Version": "2026-03-10"},
            )

            # Log response details
            logger.info(f"[DELETE_BUDGET] ======== DELETE BUDGET RESPONSE ========")
            logger.info(f"[DELETE_BUDGET] Status Code: {resp.status_code}")
            logger.info(f"[DELETE_BUDGET] Reason: {resp.reason_phrase}")
            logger.debug(f"[DELETE_BUDGET] Response Headers: {dict(resp.headers)}")
            logger.debug(f"[DELETE_BUDGET] Response Body: {resp.text}")

            resp.raise_for_status()

            # DELETE returns 200 OK with JSON response (not 204)
            result = resp.json() if resp.text else {}
            logger.info(f"[DELETE_BUDGET] ✅ SUCCESS - Budget {budget_id} deleted successfully")
            logger.debug(f"[DELETE_BUDGET] Response data: {result}")

            return {
                "success": True,
                "budget_id": budget_id,
                "status_code": resp.status_code,
                "message": result.get("message", f"Budget {budget_id} deleted successfully"),
                "id": result.get("id", budget_id)
            }
        except httpx.HTTPStatusError as e:
            # Log error details
            logger.error(f"[DELETE_BUDGET] ======== DELETE BUDGET ERROR ========")
            logger.error(f"[DELETE_BUDGET] HTTP Status: {e.response.status_code}")
            logger.error(f"[DELETE_BUDGET] Reason: {e.response.reason_phrase}")
            logger.error(f"[DELETE_BUDGET] Response Headers: {dict(e.response.headers)}")

            error_body = {}
            try:
                # Try to parse JSON error response
                error_body = e.response.json()
                logger.error(f"[DELETE_BUDGET] Error Body (JSON): {json.dumps(error_body, indent=2)}")
            except Exception:
                # If not JSON, use raw text
                error_body = {"text": e.response.text if e.response.text else "No error details"}
                logger.error(f"[DELETE_BUDGET] Error Body (Text): {error_body['text']}")

            logger.error(f"[DELETE_BUDGET] Request Path: {path}")
            logger.error(f"[DELETE_BUDGET] Full URL: {full_url}")

            return {
                "error": f"HTTP {e.response.status_code}: {e.response.reason_phrase}",
                "status_code": e.response.status_code,
                "response": error_body,
                "request_path": path
            }
        except httpx.TimeoutException as e:
            logger.error(f"[DELETE_BUDGET] ======== DELETE BUDGET TIMEOUT ========")
            logger.error(f"[DELETE_BUDGET] Request timed out: {type(e).__name__}: {e}")
            logger.error(f"[DELETE_BUDGET] Request Path: {path}")
            logger.error(f"[DELETE_BUDGET] Full URL: {full_url}")
            return {
                "error": f"Timeout while deleting budget: {type(e).__name__}",
                "status_code": None,
                "response": {"message": str(e)},
                "request_path": path,
            }
        except httpx.RequestError as e:
            logger.error(f"[DELETE_BUDGET] ======== DELETE BUDGET REQUEST ERROR ========")
            logger.error(f"[DELETE_BUDGET] Request failed: {type(e).__name__}: {e}")
            logger.error(f"[DELETE_BUDGET] Request Path: {path}")
            logger.error(f"[DELETE_BUDGET] Full URL: {full_url}")
            return {
                "error": f"Request error while deleting budget: {type(e).__name__}",
                "status_code": None,
                "response": {"message": str(e)},
                "request_path": path,
            }
