package app

import (
	"context"
	"fmt"
	"io"
	"log"
	"log/slog"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/ghapi"
)

// rotatingFile is a minimal size-based rotating writer (RotatingFileHandler).
type rotatingFile struct {
	mu       sync.Mutex
	path     string
	maxBytes int64
	backups  int
	f        *os.File
	size     int64
}

func newRotatingFile(path string, maxBytes int64, backups int) (*rotatingFile, error) {
	r := &rotatingFile{path: path, maxBytes: maxBytes, backups: backups}
	if err := r.open(); err != nil {
		return nil, err
	}
	return r, nil
}

func (r *rotatingFile) open() error {
	f, err := os.OpenFile(r.path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	st, _ := f.Stat()
	r.f = f
	if st != nil {
		r.size = st.Size()
	}
	return nil
}

func (r *rotatingFile) Write(p []byte) (int, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.size+int64(len(p)) > r.maxBytes {
		r.f.Close()
		for i := r.backups - 1; i >= 1; i-- {
			os.Rename(fmt.Sprintf("%s.%d", r.path, i), fmt.Sprintf("%s.%d", r.path, i+1))
		}
		os.Rename(r.path, r.path+".1")
		if err := r.open(); err != nil {
			return 0, err
		}
		r.size = 0
	}
	n, err := r.f.Write(p)
	r.size += int64(n)
	return n, err
}

// textHandler renders "2006-01-02 15:04:05 - name - LEVEL - message" lines,
// the Python logging format.
type textHandler struct {
	w     io.Writer
	name  string
	level slog.Level
	attrs []slog.Attr
}

func (h *textHandler) Enabled(_ context.Context, l slog.Level) bool { return l >= h.level }

func (h *textHandler) Handle(_ context.Context, r slog.Record) error {
	msg := r.Message
	add := func(a slog.Attr) bool {
		msg += fmt.Sprintf(" %s=%v", a.Key, a.Value.Any())
		return true
	}
	for _, a := range h.attrs {
		add(a)
	}
	r.Attrs(add)
	lvl := r.Level.String()
	if lvl == "WARN" {
		lvl = "WARNING"
	}
	ts := r.Time.Format("2006-01-02 15:04:05")
	var line string
	if h.name != "" {
		line = fmt.Sprintf("%s - %s - %s - %s\n", ts, h.name, lvl, msg)
	} else {
		line = fmt.Sprintf("%s - %s - %s\n", ts, lvl, msg)
	}
	_, err := io.WriteString(h.w, line)
	return err
}

func (h *textHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	c := *h
	c.attrs = append(append([]slog.Attr{}, h.attrs...), attrs...)
	return &c
}

func (h *textHandler) WithGroup(string) slog.Handler { return h }

// Logger is the application logger.
var Logger = slog.New(&textHandler{w: os.Stdout, name: "app", level: slog.LevelInfo})

// SetupLogging mirrors logging_config.setup_logging: console + rotating files.
func SetupLogging() {
	logDir := dataPath("logs")
	_ = os.MkdirAll(logDir, 0o755)

	appLog, err := newRotatingFile(filepath.Join(logDir, "octofinance.log"), 10*1024*1024, 5)
	var appW io.Writer = os.Stdout
	if err == nil {
		appW = io.MultiWriter(os.Stdout, appLog)
	}
	Logger = slog.New(&textHandler{w: appW, name: "app", level: slog.LevelInfo})
	slog.SetDefault(Logger)
	log.SetOutput(appW)
	log.SetFlags(0)

	apiLog, err := newRotatingFile(filepath.Join(logDir, "api_requests.log"), 50*1024*1024, 10)
	if err == nil {
		ghapi.Logger = slog.New(&textHandler{w: io.MultiWriter(appW, apiLog), name: "app.services.github_api", level: slog.LevelInfo})
	}

	Logger.Info("Logging initialized. Logs directory: " + logDir)
	Logger.Info("Application log: " + filepath.Join(logDir, "octofinance.log"))
	Logger.Info("API requests log: " + filepath.Join(logDir, "api_requests.log"))
}

// printf mirrors the Python backend's print() startup/progress lines.
func printf(format string, args ...any) {
	fmt.Fprintf(os.Stdout, "%s %s\n", time.Now().Format("2006-01-02 15:04:05"), fmt.Sprintf(format, args...))
}
