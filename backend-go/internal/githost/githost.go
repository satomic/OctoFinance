// Package githost resolves the two flavours of GitHub Enterprise Cloud that
// OctoFinance talks to: github.com (API at api.github.com) and
// <subdomain>.ghe.com with data residency (API at api.<subdomain>.ghe.com).
package githost

import (
	"fmt"
	"net/url"
	"os"
	"regexp"
	"strings"
)

// DefaultHost is github.com.
const DefaultHost = "github.com"

var (
	gheHostRE        = regexp.MustCompile(`^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.ghe\.com$`)
	enterprisePathRE = regexp.MustCompile(`^/enterprises/([^/?#]+)`)
)

func hostname(raw string) string {
	u, err := url.Parse(raw)
	if err != nil {
		return ""
	}
	return strings.ToLower(u.Hostname())
}

// Normalize turns user input into "github.com" or "<sub>.ghe.com".
// Accepts a bare host, an API host or any URL on the host. Empty means github.com.
func Normalize(value string) (string, error) {
	raw := strings.ToLower(strings.TrimSpace(value))
	if raw == "" {
		return DefaultHost, nil
	}
	if !strings.Contains(raw, "://") {
		raw = "https://" + raw
	}
	host := strings.TrimRight(hostname(raw), ".")
	host = strings.TrimPrefix(host, "api.")
	if host == "github.com" || host == "www.github.com" {
		return DefaultHost, nil
	}
	if gheHostRE.MatchString(host) {
		return host, nil
	}
	return "", fmt.Errorf("Unsupported GitHub host '%s'. Use github.com or <subdomain>.ghe.com (GitHub Enterprise Cloud with data residency).", value)
}

// IsGHE reports whether host is a GHE.com host.
func IsGHE(host string) bool {
	if host == "" {
		host = DefaultHost
	}
	return host != DefaultHost
}

// APIBase returns the REST API base URL for a host.
// OCTOFINANCE_GITHUB_API_BASE overrides it for every host (testing against a mock API).
func APIBase(host string) string {
	if override := strings.TrimSpace(os.Getenv("OCTOFINANCE_GITHUB_API_BASE")); override != "" {
		return strings.TrimRight(override, "/")
	}
	if host == "" || host == DefaultHost {
		return "https://api.github.com"
	}
	return "https://api." + host
}

// WebBase returns the web UI base URL for a host.
func WebBase(host string) string {
	if host == "" {
		host = DefaultHost
	}
	return "https://" + host
}

// FromAPIBase is the inverse of APIBase; unknown bases fall back to github.com.
func FromAPIBase(base string) string {
	h, err := Normalize(base)
	if err != nil {
		return DefaultHost
	}
	return h
}

// ParseEnterpriseURL splits "https://acme.ghe.com/enterprises/acme" into
// ("acme.ghe.com", "acme"). ok is false when value is a plain slug.
func ParseEnterpriseURL(value string) (host, slug string, ok bool, err error) {
	raw := strings.TrimSpace(value)
	if !strings.Contains(raw, "/enterprises/") {
		return "", "", false, nil
	}
	if !strings.Contains(raw, "://") {
		raw = "https://" + raw
	}
	u, perr := url.Parse(raw)
	if perr != nil {
		return "", "", false, nil
	}
	m := enterprisePathRE.FindStringSubmatch(u.Path)
	if m == nil {
		return "", "", false, nil
	}
	h, nerr := Normalize(u.Hostname())
	if nerr != nil {
		return "", "", false, nerr
	}
	return h, m[1], true, nil
}
