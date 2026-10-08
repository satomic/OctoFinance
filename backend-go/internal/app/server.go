package app

import (
	"context"
	"errors"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

const sessionCookie = "octofinance_session"

// authPublicPaths do not require authentication.
var authPublicPaths = map[string]bool{
	"/api/auth/status":          true,
	"/api/auth/setup":           true,
	"/api/auth/login":           true,
	"/api/auth/github/login":    true,
	"/api/auth/github/callback": true,
}

// nonAdminPathPrefixes are reachable by any authenticated user.
var nonAdminPathPrefixes = []string{"/api/auth/", "/api/me/", "/api/budget-requests"}

// adminOnlyPaths live under an otherwise non-admin prefix.
var adminOnlyPaths = map[string]bool{"/api/auth/github/config": true}

func requestUser(r *http.Request) jx.M {
	ck, err := r.Cookie(sessionCookie)
	if err != nil {
		return nil
	}
	return Auth.GetSession(ck.Value)
}

var corsOrigins = map[string]bool{"http://localhost:5173": true, "http://localhost:3000": true}

// middleware applies CORS and the auth + role gate for /api/*.
func middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if origin := r.Header.Get("Origin"); corsOrigins[origin] {
			h := w.Header()
			h.Set("Access-Control-Allow-Origin", origin)
			h.Set("Access-Control-Allow-Credentials", "true")
			h.Add("Vary", "Origin")
			if r.Method == http.MethodOptions && r.Header.Get("Access-Control-Request-Method") != "" {
				h.Set("Access-Control-Allow-Methods", "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT")
				if reqH := r.Header.Get("Access-Control-Request-Headers"); reqH != "" {
					h.Set("Access-Control-Allow-Headers", reqH)
				}
				h.Set("Access-Control-Max-Age", "600")
				w.WriteHeader(http.StatusOK)
				return
			}
		}
		path := r.URL.Path
		if strings.HasPrefix(path, "/api") && !authPublicPaths[path] {
			user := requestUser(r)
			if user == nil {
				WriteJSON(w, 401, jx.M{"error": "Authentication required"})
				return
			}
			if !jx.GetBool(user, "is_admin") {
				allowed := false
				if !adminOnlyPaths[path] {
					for _, p := range nonAdminPathPrefixes {
						if strings.HasPrefix(path, p) {
							allowed = true
							break
						}
					}
				}
				if !allowed {
					WriteJSON(w, 403, jx.M{"error": "Administrator access required"})
					return
				}
			}
		}
		next.ServeHTTP(w, r)
	})
}

// spaHandler serves frontend/dist: hashed assets, root files, and index.html for everything else.
func spaHandler() http.Handler {
	index := filepath.Join(FrontendDist, "index.html")
	assets := http.StripPrefix("/assets/", http.FileServer(http.Dir(filepath.Join(FrontendDist, "assets"))))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/api/") || r.URL.Path == "/api" {
			WriteJSON(w, 404, jx.M{"detail": "Not Found"})
			return
		}
		if strings.HasPrefix(r.URL.Path, "/assets/") {
			assets.ServeHTTP(w, r)
			return
		}
		clean := filepath.Clean("/" + r.URL.Path)
		if clean != "/" {
			candidate := filepath.Join(FrontendDist, clean)
			if st, err := os.Stat(candidate); err == nil && !st.IsDir() {
				http.ServeFile(w, r, candidate)
				return
			}
		}
		if !jx.Exists(index) {
			WriteJSON(w, 404, jx.M{"detail": "Not Found"})
			return
		}
		// index.html must never be cached, otherwise browsers keep stale bundles.
		w.Header().Set("Cache-Control", "no-cache, must-revalidate")
		http.ServeFile(w, r, index)
	})
}

// NewHandler builds the full HTTP handler.
func NewHandler() http.Handler {
	mux := http.NewServeMux()
	router := &Router{mux: mux}
	for _, reg := range routeRegistrars {
		reg(router)
	}
	router.Handle("GET /api/health", handleHealth)
	if jx.Exists(FrontendDist) {
		mux.Handle("/", spaHandler())
	} else {
		mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
			WriteJSON(w, 404, jx.M{"detail": "Not Found"})
		})
	}
	return middleware(mux)
}

func handleHealth(c *Ctx) any {
	logins := APIs.DiscoveredLogins()
	var user any
	if len(logins) > 0 {
		user = logins[0]
	}
	return jx.M{
		"status":              "ok",
		"version":             AppVersion,
		"backend":             BackendName,
		"users":               logins,
		"user":                user,
		"orgs":                APIs.AllOrgLogins(),
		"pat_count":           Pats.Count(),
		"copilot_engine":      Engine.IsReady(),
		"is_syncing":          Syncs.IsSyncing(),
		"sync":                Syncs.Status(),
		"credential_problems": CredProblems(),
		"update":              Updates.State(),
	}
}

// startup mirrors the FastAPI lifespan startup sequence.
func startup() {
	printf("[OctoFinance] Starting up (Go backend)...")
	EnsureDataDirs()
	SetupLogging()
	Auth.LoadSessions()
	Syncs.LoadStatus()

	pats := Pats.Load()
	printf("[OctoFinance] Loaded %d PAT(s)", len(pats))

	if removed := Collector.PurgeSnapshots(); removed > 0 {
		printf("[OctoFinance] Removed %d legacy data snapshot file(s)", removed)
	}
	if renamed := Sessions.BackfillTitles(); renamed > 0 {
		printf("[OctoFinance] Named %d untitled chat session(s) from their first message", renamed)
	}
	if folded := CSVEnsureMigrated(CSVTypeAI) + CSVEnsureMigrated(CSVTypeUsage); folded > 0 {
		printf("[OctoFinance] Merged %d legacy CSV file(s) into the latest snapshots", folded)
	}

	Syncs.SetPreflight(CredPreflight)
	settings := Pats.GetSettings()

	if len(pats) > 0 {
		printf("[OctoFinance] Auto-discovering GitHub resources...")
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		done := make(chan struct{})
		go func() {
			APIs.Rebuild(ctx)
			close(done)
		}()
		select {
		case <-done:
			printf("[OctoFinance] Discovered %d organizations: %v", len(APIs.AllOrgLogins()), APIs.AllOrgLogins())
		case <-ctx.Done():
			printf("[OctoFinance] Startup discovery warning: timed out; continue startup and retry from Settings/Sync.")
		}
		cancel()

		if jx.GetBoolDef(settings, "auto_sync_on_startup", true) {
			printf("[OctoFinance] Starting initial data sync (background)...")
			Syncs.RunInBackground(RunFullSync, "startup")
		} else {
			printf("[OctoFinance] Auto sync on startup is disabled, skipping initial sync.")
			go CredCheckAll(context.Background(), Syncs.Log)
		}
		if expr := strings.TrimSpace(jx.Str(settings["sync_cron"])); expr != "" {
			Syncs.StartCronScheduler(expr, RunFullSync)
		}
	} else {
		printf("[OctoFinance] No PATs configured. Add a PAT via Settings to get started.")
	}

	printf("[OctoFinance] Starting Copilot AI engine...")
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	if err := Engine.Start(ctx); err != nil {
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			printf("[OctoFinance] Copilot engine startup warning: timed out; chat will retry when used.")
		} else {
			printf("[OctoFinance] Copilot engine startup warning: %v", err)
		}
	} else {
		printf("[OctoFinance] Copilot AI engine ready.")
	}
	cancel()
	printf("[OctoFinance] Ready!")
}

// Run starts the server on addr and blocks until SIGINT/SIGTERM.
func Run(addr string) error {
	startup()
	srv := &http.Server{
		Addr:              addr,
		Handler:           NewHandler(),
		ReadHeaderTimeout: 30 * time.Second,
	}
	errCh := make(chan error, 1)
	go func() {
		printf("[OctoFinance] Listening on http://%s", addr)
		errCh <- srv.ListenAndServe()
	}()
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	select {
	case err := <-errCh:
		return err
	case <-sig:
	}
	printf("[OctoFinance] Shutting down...")
	Syncs.StopCronScheduler()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
	Engine.Stop()
	return nil
}
