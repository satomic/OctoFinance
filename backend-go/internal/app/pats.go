package app

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"sync"

	"github.com/satomic/octofinance/backend-go/internal/githost"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// DefaultSettings are the app settings stored next to the PATs in pats.json.
var DefaultSettings = jx.M{
	"auto_sync_on_startup": true,
	"sync_cron":            "",
	// Billing report CSV exports take minutes to generate, so both the poll
	// cadence and the give-up point are tunable.
	"csv_fetch_poll_seconds":    60.0,
	"csv_fetch_timeout_minutes": 120.0,
}

// PATManager persists GitHub PATs and app settings in data/pats.json.
type PATManager struct {
	mu       sync.RWMutex
	pats     []jx.M
	settings jx.M
}

// Pats is the global PAT manager.
var Pats = &PATManager{settings: jx.Copy(DefaultSettings)}

func patsFile() string { return dataPath("pats.json") }

func randHex(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// Load reads PATs and settings; migrates the legacy plain-array format.
func (p *PATManager) Load() []jx.M {
	p.mu.Lock()
	defer p.mu.Unlock()
	raw := jx.ReadJSONOr(patsFile(), jx.L{})
	switch t := raw.(type) {
	case []any:
		p.pats = jx.Maps(t)
		p.settings = jx.Copy(DefaultSettings)
		if len(t) > 0 {
			p.saveLocked()
			printf("[PATManager] Migrated pats.json from legacy array to {pats, settings} format")
		}
	case map[string]any:
		p.pats = jx.GetMaps(t, "pats")
		p.settings = jx.Merge(DefaultSettings, jx.GetMap(t, "settings"))
	default:
		p.pats = []jx.M{}
		p.settings = jx.Copy(DefaultSettings)
	}
	return p.copyPats()
}

func (p *PATManager) saveLocked() {
	if p.pats == nil {
		p.pats = []jx.M{}
	}
	_ = jx.WriteJSON(patsFile(), jx.M{"pats": p.pats, "settings": p.settings})
}

func (p *PATManager) copyPats() []jx.M {
	out := make([]jx.M, len(p.pats))
	for i, pat := range p.pats {
		out[i] = jx.Copy(pat)
	}
	return out
}

// GetSettings returns a copy of the settings.
func (p *PATManager) GetSettings() jx.M {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return jx.Copy(p.settings)
}

// UpdateSettings applies known keys and persists.
func (p *PATManager) UpdateSettings(updates jx.M) jx.M {
	p.mu.Lock()
	defer p.mu.Unlock()
	for key := range DefaultSettings {
		if v, ok := updates[key]; ok {
			p.settings[key] = v
		}
	}
	p.saveLocked()
	return jx.Copy(p.settings)
}

// GetAll returns all PATs including tokens (copies).
func (p *PATManager) GetAll() []jx.M {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.copyPats()
}

// GetAllMasked returns PATs with the token replaced by token_masked.
func (p *PATManager) GetAllMasked() []jx.M {
	p.mu.RLock()
	defer p.mu.RUnlock()
	out := []jx.M{}
	for _, pat := range p.pats {
		masked := jx.Copy(pat)
		token := jx.GetStr(pat, "token")
		if len(token) > 8 {
			masked["token_masked"] = token[:4] + "***" + token[len(token)-4:]
		} else {
			masked["token_masked"] = "***"
		}
		delete(masked, "token")
		masked["host"] = jx.OrStr(pat, "host", githost.DefaultHost)
		out = append(out, masked)
	}
	return out
}

// Add stores a new PAT; host must already be normalized.
func (p *PATManager) Add(label, token string, enterpriseSlugs []string, includeOrganizations bool, host string) (jx.M, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, existing := range p.pats {
		if jx.GetStr(existing, "token") == token {
			return nil, fmt.Errorf("This token is already configured as '%s'", jx.Str(existing["label"]))
		}
	}
	if label == "" {
		label = "Untitled"
	}
	if host == "" {
		host = githost.DefaultHost
	}
	if enterpriseSlugs == nil {
		enterpriseSlugs = []string{}
	}
	slugs := make(jx.L, len(enterpriseSlugs))
	for i, s := range enterpriseSlugs {
		slugs[i] = s
	}
	pat := jx.M{
		"id":                    "pat_" + randHex(4),
		"label":                 label,
		"token":                 token,
		"host":                  host,
		"user_login":            "",
		"user_avatar":           "",
		"orgs":                  jx.L{},
		"enterprise_slugs":      slugs,
		"include_organizations": includeOrganizations,
		"created_at":            jx.NowISO(),
		"last_synced_at":        "",
	}
	p.pats = append(p.pats, pat)
	p.saveLocked()
	return jx.Copy(pat), nil
}

// Update applies metadata fields (never id/token) and persists.
func (p *PATManager) Update(patID string, fields jx.M) jx.M {
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, pat := range p.pats {
		if jx.GetStr(pat, "id") == patID {
			for k, v := range fields {
				if k != "id" && k != "token" {
					pat[k] = v
				}
			}
			p.saveLocked()
			return jx.Copy(pat)
		}
	}
	return nil
}

// SetToken replaces a PAT's token.
func (p *PATManager) SetToken(patID, token string) (jx.M, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, pat := range p.pats {
		if jx.GetStr(pat, "token") == token && jx.GetStr(pat, "id") != patID {
			return nil, fmt.Errorf("This token is already configured as '%s'", jx.Str(pat["label"]))
		}
	}
	for _, pat := range p.pats {
		if jx.GetStr(pat, "id") == patID {
			pat["token"] = token
			p.saveLocked()
			return jx.Copy(pat), nil
		}
	}
	return nil, nil
}

// Remove deletes a PAT by id.
func (p *PATManager) Remove(patID string) bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	kept := p.pats[:0:0]
	for _, pat := range p.pats {
		if jx.GetStr(pat, "id") != patID {
			kept = append(kept, pat)
		}
	}
	removed := len(kept) < len(p.pats)
	p.pats = kept
	if removed {
		p.saveLocked()
	}
	return removed
}

// FindByID returns a copy of a PAT, or nil.
func (p *PATManager) FindByID(patID string) jx.M {
	p.mu.RLock()
	defer p.mu.RUnlock()
	for _, pat := range p.pats {
		if jx.GetStr(pat, "id") == patID {
			return jx.Copy(pat)
		}
	}
	return nil
}

// Count returns the number of PATs.
func (p *PATManager) Count() int {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return len(p.pats)
}
