"""
Configuration management.
PATs are managed at runtime via the web UI and stored in data/pats.json.
All org/enterprise info is auto-discovered via GitHub API.
"""

from pathlib import Path

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
        for sub in ("seats", "usage", "usage_users", "metrics", "billing", "premium_requests", "premium_usage_csv"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)


# Global config instance
config = AppConfig()
