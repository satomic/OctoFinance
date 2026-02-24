"""
GitHub REST API client with auto-discovery.
Each instance is bound to a specific PAT token.
"""

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
    # Copilot Usage & Metrics
    # =========================================================================

    async def get_copilot_usage(self, org: str, since: str | None = None, until: str | None = None) -> list | None:
        """Get Copilot usage metrics for an org."""
        try:
            params = {}
            if since:
                params["since"] = since
            if until:
                params["until"] = until
            resp = await self.client.get(f"/orgs/{org}/copilot/usage", params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError:
            return None

    async def get_copilot_metrics(self, org: str, since: str | None = None, until: str | None = None) -> list | None:
        """Get Copilot metrics for an org."""
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
    # Copilot Seat Management (Operations)
    # =========================================================================

    async def add_copilot_seats(self, org: str, usernames: list[str]) -> dict | None:
        """Add Copilot seats for specified users."""
        try:
            resp = await self.client.post(
                f"/orgs/{org}/copilot/billing/seats",
                json={"selected_usernames": usernames},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            return {"error": str(e), "status_code": e.response.status_code}

    async def remove_copilot_seats(self, org: str, usernames: list[str]) -> dict | None:
        """Remove Copilot seats for specified users."""
        try:
            resp = await self.client.request(
                "DELETE",
                f"/orgs/{org}/copilot/billing/seats",
                json={"selected_usernames": usernames},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            return {"error": str(e), "status_code": e.response.status_code}
