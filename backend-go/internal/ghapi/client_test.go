package ghapi

import (
	"context"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

// flakyServer drops the connection (no response, like a network EOF) for the
// first `drops` requests, then answers 200 with {"login":"octocat"}.
func flakyServer(t *testing.T, drops int32, status int) (*httptest.Server, *atomic.Int32) {
	t.Helper()
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := calls.Add(1)
		if n <= drops {
			conn, _, err := w.(http.Hijacker).Hijack()
			if err == nil {
				conn.Close()
			}
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write([]byte(`{"login":"octocat"}`))
	}))
	t.Cleanup(srv.Close)
	return srv, &calls
}

func fastBackoff(t *testing.T) {
	old := transientBackoff
	transientBackoff = []time.Duration{time.Millisecond, time.Millisecond}
	t.Cleanup(func() { transientBackoff = old })
}

func TestGetRetriesTransientFailures(t *testing.T) {
	fastBackoff(t)
	srv, calls := flakyServer(t, 2, 200)
	user, err := New("t", srv.URL).DiscoverUser(context.Background())
	if err != nil {
		t.Fatalf("expected success after retries, got %v", err)
	}
	if user["login"] != "octocat" || calls.Load() != 3 {
		t.Fatalf("login=%v calls=%d, want octocat after 3 calls", user["login"], calls.Load())
	}
}

func TestGetGivesUpAfterRetries(t *testing.T) {
	fastBackoff(t)
	srv, calls := flakyServer(t, 10, 200)
	_, err := New("t", srv.URL).DiscoverUser(context.Background())
	if _, ok := err.(*TransportError); !ok {
		t.Fatalf("expected a TransportError, got %v", err)
	}
	if got := calls.Load(); got != int32(1+TransientRetries) {
		t.Fatalf("calls=%d, want %d", got, 1+TransientRetries)
	}
}

func TestWritesAreNotRetried(t *testing.T) {
	fastBackoff(t)
	srv, calls := flakyServer(t, 1, 200)
	_, err := New("t", srv.URL).Do(context.Background(), http.MethodPost, "/x", nil, map[string]any{"a": 1}, nil)
	if err == nil || calls.Load() != 1 {
		t.Fatalf("POST must not be retried: err=%v calls=%d", err, calls.Load())
	}
}

func TestHTTPErrorsAreNotRetried(t *testing.T) {
	fastBackoff(t)
	srv, calls := flakyServer(t, 0, 401)
	resp, err := New("t", srv.URL).Get(context.Background(), "/user", nil, nil)
	if err != nil || resp.Status != 401 || calls.Load() != 1 {
		t.Fatalf("401 must be returned once: err=%v status=%v calls=%d", err, resp, calls.Load())
	}
}
