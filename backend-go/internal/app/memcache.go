package app

import (
	"os"
	"runtime/debug"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Parsed snapshots and CSV exports are cached so the several requests a page
// makes do not each re-parse the same files. Decoded into Go maps, a large
// enterprise's usage files take several times their size on disk, so a cache
// that kept them would hold gigabytes; the Python backend re-parses per request
// and keeps nothing. Large files therefore stay cached only while pages are
// loading (bigIdleTTL), small ones a few minutes, and memory freed by eviction
// is returned to the OS.
var (
	cacheIdleTTL = 3 * time.Minute
	bigIdleTTL   = 15 * time.Second
	bigFileBytes = int64(4 << 20)
)

type fileCacheEntry struct {
	mtime    time.Time
	size     int64
	val      any
	lastUsed time.Time
}

// fileCache maps a file path to a value derived from it, invalidated on any
// change of modification time or size.
type fileCache struct {
	mu      sync.Mutex
	entries map[string]*fileCacheEntry
	loading map[string]*sync.Mutex
}

var allFileCaches []*fileCache

func newFileCache() *fileCache {
	c := &fileCache{entries: map[string]*fileCacheEntry{}, loading: map[string]*sync.Mutex{}}
	allFileCaches = append(allFileCaches, c)
	return c
}

func (c *fileCache) getLocked(path string, st os.FileInfo) (any, bool) {
	e, ok := c.entries[path]
	if !ok || !e.mtime.Equal(st.ModTime()) || e.size != st.Size() {
		return nil, false
	}
	e.lastUsed = time.Now()
	return e.val, true
}

// get returns the cached value for path when the file is unchanged.
func (c *fileCache) get(path string, st os.FileInfo) (any, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.getLocked(path, st)
}

func (c *fileCache) put(path string, st os.FileInfo, val any) {
	c.mu.Lock()
	c.entries[path] = &fileCacheEntry{mtime: st.ModTime(), size: st.Size(), val: val, lastUsed: time.Now()}
	c.mu.Unlock()
}

// load returns the cached value or computes it with fn. Concurrent callers for
// the same path wait for one fn call instead of each decoding their own copy.
func (c *fileCache) load(path string, st os.FileInfo, fn func() (any, error)) (any, error) {
	c.mu.Lock()
	if v, ok := c.getLocked(path, st); ok {
		c.mu.Unlock()
		return v, nil
	}
	l, ok := c.loading[path]
	if !ok {
		l = &sync.Mutex{}
		c.loading[path] = l
	}
	c.mu.Unlock()

	l.Lock()
	defer l.Unlock()
	if v, ok := c.get(path, st); ok { // loaded by the caller we waited for
		return v, nil
	}
	v, err := fn()
	if err != nil {
		return nil, err
	}
	c.put(path, st, v)
	return v, nil
}

// evictIdle drops idle entries and reports how many bytes of files they held.
func (c *fileCache) evictIdle(now time.Time) int64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	var freed int64
	for k, e := range c.entries {
		ttl := cacheIdleTTL
		if e.size >= bigFileBytes {
			ttl = bigIdleTTL
		}
		if now.Sub(e.lastUsed) >= ttl {
			delete(c.entries, k)
			delete(c.loading, k)
			freed += e.size
		}
	}
	return freed
}

var cacheJanitorOnce sync.Once

// startCacheJanitor evicts idle cache entries every few seconds.
func startCacheJanitor() {
	cacheJanitorOnce.Do(func() {
		go func() {
			t := time.NewTicker(5 * time.Second)
			defer t.Stop()
			for now := range t.C {
				evictIdleCaches(now)
			}
		}()
	})
}

func evictIdleCaches(now time.Time) {
	var freed int64
	for _, c := range allFileCaches {
		freed += c.evictIdle(now)
	}
	if freed >= bigFileBytes {
		debug.FreeOSMemory()
	}
}

// tuneGC trades a little CPU for memory: the dashboards decode large files
// into short-lived maps, and Go's default GOGC=100 lets the heap grow to twice
// what is live before collecting. GOGC=50 lowered the peak by about a quarter
// at no measurable cost in response time. In a container with a memory limit
// the GC also gets a soft limit below it (the Copilot CLI shares the
// container), so it collects harder before the kernel would kill the process.
// GOGC and GOMEMLIMIT set in the environment take precedence.
func tuneGC() {
	if os.Getenv("GOGC") == "" {
		debug.SetGCPercent(50)
	}
	if os.Getenv("GOMEMLIMIT") != "" {
		return
	}
	for _, f := range []string{"/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"} {
		b, err := os.ReadFile(f)
		if err != nil {
			continue
		}
		limit, err := strconv.ParseInt(strings.TrimSpace(string(b)), 10, 64)
		if err != nil || limit <= 0 || limit >= 1<<50 { // "max" or the cgroup v1 "unlimited" value
			return
		}
		debug.SetMemoryLimit(limit * 6 / 10)
		return
	}
}
