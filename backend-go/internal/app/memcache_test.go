package app

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestFileCacheEvictsIdleEntries(t *testing.T) {
	path := filepath.Join(t.TempDir(), "x_latest.json")
	if err := os.WriteFile(path, []byte(`{"a":1}`), 0o644); err != nil {
		t.Fatal(err)
	}
	v, ok := dataReadCached(path)
	if !ok || v.(map[string]any)["a"] != 1.0 {
		t.Fatalf("got %v %v", v, ok)
	}
	st, _ := os.Stat(path)
	if _, hit := dataFileCache.get(path, st); !hit {
		t.Fatal("expected a cache hit after the first read")
	}
	evictIdleCaches(time.Now()) // just used: kept
	if _, hit := dataFileCache.get(path, st); !hit {
		t.Fatal("a recently used entry must not be evicted")
	}
	evictIdleCaches(time.Now().Add(cacheIdleTTL + time.Second))
	if _, hit := dataFileCache.get(path, st); hit {
		t.Fatal("an idle entry must be evicted")
	}
	if v, ok := dataReadCached(path); !ok || v.(map[string]any)["a"] != 1.0 {
		t.Fatal("reads must still work after eviction")
	}
}
