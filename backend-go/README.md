# OctoFinance Go backend

A Go implementation of the OctoFinance backend. It serves the same HTTP API
and the same React frontend as the Python (FastAPI) backend in `../backend`,
and reads and writes the same `data/` directory in the same file formats, so
you can switch between the two backends on one installation at any time.

The AI chat uses the [GitHub Copilot Go SDK](https://github.com/github/copilot-sdk/tree/main/go)
(`github.com/github/copilot-sdk/go`, SDK protocol v3, the same protocol as the
Python SDK), driving the same Copilot CLI with the same FinOps system prompt and
the same set of tools.

## Run

From the repository root:

```bash
./scripts/run-backend.sh go          # builds and starts the Go backend on :8000
```

or by hand:

```bash
cd backend-go
go build -o bin/octofinance-go ./cmd/octofinance
./bin/octofinance-go -host 0.0.0.0 -port 8000
```

Run from `backend-go/` (or set `OCTOFINANCE_ROOT`), the binary uses `../data`
and serves `../frontend/dist` when it has been built.

Docker: the image is built from [`../Dockerfile-go`](../Dockerfile-go) and contains
only the Go backend, the frontend and the Copilot CLI:

```bash
./scripts/docker-build-go.sh          # from the repository root -> octofinance-go:dev
docker run -d -p 8000:8000 -v $(pwd)/data:/app/data -e COPILOT_GITHUB_TOKEN=... octofinance-go:dev
```

Release tags publish it as `ghcr.io/<owner>/<repo>` (see the main README).

| Setting | Default | Purpose |
|---------|---------|---------|
| `-host` / `HOST` | `0.0.0.0` | Listen address |
| `-port` / `PORT` | `8000` | Listen port |
| `OCTOFINANCE_ROOT` | parent of `backend-go/`, else the working directory | Repository root holding `data/` and `frontend/dist` |
| `OCTOFINANCE_DATA_DIR` | `$OCTOFINANCE_ROOT/data` | Data directory |
| `OCTOFINANCE_FRONTEND_DIST` | `$OCTOFINANCE_ROOT/frontend/dist` | Built frontend |
| `COPILOT_CLI_PATH` | `copilot` on `PATH` | Copilot CLI binary used by the SDK |

All other environment variables (`COPILOT_GITHUB_TOKEN`, `GH_TOKEN`,
`GITHUB_TOKEN`, `COPILOT_GH_HOST`, `GITHUB_OAUTH_*`) behave exactly as in the
Python backend.

Debugging helpers:

```bash
./bin/octofinance-go -list-tools                         # AI tool names
./bin/octofinance-go -tool get_cost_overview -args '{}'  # run one AI tool and print its result
./bin/octofinance-go -version
```

## Layout

```
cmd/octofinance/        entry point (flags, server start)
internal/jx/            schemaless-JSON helpers with Python dict semantics
internal/githost/       github.com vs <tenant>.ghe.com host model
internal/ghapi/         GitHub REST API client (one per PAT)
internal/app/           everything else, one file per Python module:
  server.go, httpx.go     HTTP server, auth/role middleware, SPA, request helpers
  routes_*.go             API routers (auth, pats, sync, sessions, chat, data, me, ...)
  copilot_engine.go       Copilot SDK client, sessions, streaming chat
  tooldef.go, tools_*.go  AI tools exposed to the Copilot session
  datacollector.go        GitHub data sync into data/{category}/{scope}_latest.json
  syncmgr.go              sync runs, SSE log broadcast, cron scheduler
  csvstore.go, csvfetcher.go, budgetprov.go, ...  services
```

## Differences from the Python backend

- Handlers run concurrently; shared JSON files are guarded by locks.
- The merged billing CSVs are parsed once and cached until the file changes,
  instead of being re-read on every dashboard request.
- `/api/health` additionally reports `"backend": "go"`.
- Static files in `frontend/dist` other than `/assets` (e.g. the favicon) are
  served as files instead of falling back to `index.html`.

## Testing against the Python backend

See **[TEST_REPORT.md](TEST_REPORT.md)** ([中文](TEST_REPORT_CN.md)) for the full comparison: API, AI tool,
data file and browser end-to-end parity results, and the performance numbers
(e.g. 16 concurrent requests: main dashboard 20 → 2,801 req/s).

The harness lives in [`tests/parity/`](tests/parity/): it runs the Python and Go
backends side by side on copies of the same data, each against its own stateful
mock GitHub API, and diffs responses, tool outputs, data files and sync logs.
`OCTOFINANCE_GITHUB_API_BASE` (test-only) points every GitHub host at the mock.

```bash
go test ./...                     # unit tests
cd tests/parity && ./start.sh ...  # parity runs, see TEST_REPORT.md section 7
```
