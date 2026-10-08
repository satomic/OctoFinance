// Package app is the Go implementation of the OctoFinance backend: the HTTP
// API consumed by the React frontend, the data sync engine and the Copilot SDK
// AI engine. It reads and writes exactly the same data/ directory layout as
// the Python backend, so the two backends are interchangeable.
package app

import (
	"os"
	"path/filepath"
	"strings"
)

// AppVersion is the application version exposed via /api/health and the UI.
const AppVersion = "2.0.2"

// BackendName identifies this implementation in /api/health.
const BackendName = "go"

// CopilotPricing is the Copilot plan pricing (USD/month/user).
var CopilotPricing = map[string]float64{
	"business":   19.0,
	"enterprise": 39.0,
}

var (
	// ProjectRoot is the repository root (holds data/ and frontend/dist).
	ProjectRoot string
	// DataDir is where all runtime state lives.
	DataDir string
	// FrontendDist is the built SPA directory.
	FrontendDist string
)

func init() {
	ProjectRoot = resolveProjectRoot()
	DataDir = envOr("OCTOFINANCE_DATA_DIR", filepath.Join(ProjectRoot, "data"))
	FrontendDist = envOr("OCTOFINANCE_FRONTEND_DIST", filepath.Join(ProjectRoot, "frontend", "dist"))
}

func envOr(key, def string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		if abs, err := filepath.Abs(v); err == nil {
			return abs
		}
		return v
	}
	return def
}

// resolveProjectRoot finds the repository root: OCTOFINANCE_ROOT, else the
// parent of a backend-go working directory, else the working directory.
func resolveProjectRoot() string {
	if v := strings.TrimSpace(os.Getenv("OCTOFINANCE_ROOT")); v != "" {
		if abs, err := filepath.Abs(v); err == nil {
			return abs
		}
		return v
	}
	cwd, err := os.Getwd()
	if err != nil {
		return "."
	}
	if filepath.Base(cwd) == "backend-go" {
		return filepath.Dir(cwd)
	}
	return cwd
}

// EnsureDataDirs creates the data directory tree, like the Python AppConfig.
func EnsureDataDirs() {
	_ = os.MkdirAll(DataDir, 0o755)
	for _, sub := range []string{"seats", "usage", "usage_users", "metrics", "billing", "ai_credits",
		"ai_usage_csv", "usage_report_csv", "cost_centers", "budgets", "enterprise_teams"} {
		_ = os.MkdirAll(filepath.Join(DataDir, sub), 0o755)
	}
}

// dataPath joins a path under DataDir.
func dataPath(parts ...string) string {
	return filepath.Join(append([]string{DataDir}, parts...)...)
}
