package app

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Release update checker: follows the /releases/latest redirect, no API token.

const (
	releasesLatestURL = "https://github.com/satomic/OctoFinance/releases/latest"
	releasesPageURL   = "https://github.com/satomic/OctoFinance/releases"
	checkTimeout      = 30 * time.Second
)

var tagRE = regexp.MustCompile(`/releases/tag/([^/?#]+)`)

func versionTuple(v string) []int {
	v = strings.TrimLeft(strings.TrimSpace(v), "vV")
	out := []int{}
	for _, p := range regexp.MustCompile(`[.\-+]`).Split(v, -1) {
		n, err := strconv.Atoi(p)
		if err != nil || p == "" {
			break
		}
		out = append(out, n)
	}
	return out
}

func versionGreater(a, b []int) bool {
	for i := 0; i < len(a) && i < len(b); i++ {
		if a[i] != b[i] {
			return a[i] > b[i]
		}
	}
	return len(a) > len(b)
}

// UpdateChecker caches the latest known release.
type UpdateChecker struct {
	mu         sync.Mutex
	latest     string
	releaseURL string
	checkedAt  any
	err        any
	running    bool
}

// Updates is the global update checker.
var Updates = &UpdateChecker{releaseURL: releasesPageURL}

// State returns the update info served to the UI.
func (u *UpdateChecker) State() jx.M {
	u.mu.Lock()
	defer u.mu.Unlock()
	var latest any
	available := false
	if u.latest != "" {
		latest = u.latest
		available = versionGreater(versionTuple(u.latest), versionTuple(AppVersion))
	}
	return jx.M{
		"current_version":  AppVersion,
		"latest_version":   latest,
		"update_available": available,
		"release_url":      u.releaseURL,
		"checked_at":       u.checkedAt,
		"error":            u.err,
	}
}

// Schedule kicks off a check in the background unless one is in flight.
func (u *UpdateChecker) Schedule() {
	u.mu.Lock()
	if u.running {
		u.mu.Unlock()
		return
	}
	u.running = true
	u.mu.Unlock()
	go func() {
		defer func() {
			u.mu.Lock()
			u.running = false
			u.mu.Unlock()
		}()
		ctx, cancel := context.WithTimeout(context.Background(), checkTimeout)
		defer cancel()
		tag, err := u.check(ctx)
		u.mu.Lock()
		defer u.mu.Unlock()
		u.checkedAt = jx.NowISO()
		if err != nil {
			if errors.Is(err, context.DeadlineExceeded) {
				u.err = fmt.Sprintf("Timed out after %.0fs", checkTimeout.Seconds())
			} else {
				u.err = err.Error()
			}
			Logger.Info("Update check failed: " + fmt.Sprint(u.err))
			return
		}
		u.latest = tag
		u.releaseURL = "https://github.com/satomic/OctoFinance/releases/tag/" + tag
		u.err = nil
		Logger.Info(fmt.Sprintf("Latest release: %s (current %s)", tag, AppVersion))
	}()
}

func (u *UpdateChecker) check(ctx context.Context) (string, error) {
	candidates := []string{}
	client := &http.Client{
		Timeout: checkTimeout,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			candidates = append(candidates, req.URL.String())
			return nil
		},
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, releasesLatestURL, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", "OctoFinance/"+AppVersion)
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	resp.Body.Close()
	candidates = append([]string{resp.Request.URL.String()}, candidates...)
	if loc := resp.Header.Get("Location"); loc != "" {
		candidates = append(candidates, loc)
	}
	for _, c := range candidates {
		if m := tagRE.FindStringSubmatch(c); m != nil {
			return m[1], nil
		}
	}
	return "", errors.New("Could not resolve a release tag from the redirect")
}
