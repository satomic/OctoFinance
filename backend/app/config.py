"""
Configuration management.
PATs are managed at runtime via the web UI and stored in data/pats.json.
All org/enterprise info is auto-discovered via GitHub API.
"""

from pathlib import Path

# Application version (single source of truth, exposed via /api/health and the UI)
APP_VERSION = "1.0.0"

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Copilot plan pricing (USD/month/user)
COPILOT_PRICING = {
    "business": 19.0,
    "enterprise": 39.0,
}


class AppConfig:
    def __init__(self):
        self.github_api_base: str = "https://api.github.com"
        self.data_dir: Path = DATA_DIR
        # Ensure data directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for sub in ("seats", "usage", "usage_users", "metrics", "billing", "ai_credits", "ai_usage_csv", "cost_centers", "budgets"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)


# Global config instance
config = AppConfig()
