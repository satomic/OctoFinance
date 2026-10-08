# Go backend vs Python backend: comparison test report

> Version: OctoFinance v2.0.0 (tests ran on this code before the version number was bumped from 1.6.0) | Test dates: 2026-10-07 to 2026-10-08 | [中文版](TEST_REPORT_CN.md)
>
> Conclusion: the Go backend behaves the same as the Python backend across every API, AI tool,
> data file and UI flow. With 16 concurrent requests, throughput of the main dashboard endpoints is
> **16 to 139 times higher** (see section 4).

## 1. Test environment

| Item | Details |
|------|---------|
| Machine | Apple M4 Pro, 12 cores, 48 GB RAM, macOS |
| Go backend | Go 1.25.6, Copilot Go SDK `github.com/github/copilot-sdk/go` v1.0.5 for the parity tests in sections 3.1–3.4 and 4; v1.0.17 (current `go.mod`) re-verified as described in section 3.5 (both SDK protocol v3) |
| Python backend | Python 3.13.5, FastAPI + uvicorn (single worker), `github-copilot-sdk` 1.0.5 (SDK protocol v3) |
| Copilot CLI | 1.0.89 locally; 1.0.68 for the first Docker image tests; 1.0.93 (latest at build time) in the final Docker image tests |
| Test data | A copy of a real `data/` directory (about 12 MB): 6 organizations + 1 enterprise, 10 seat snapshots (26 seats), 1,244 user-level usage records, 347 AI usage CSV rows, 2,502 usage report CSV rows, 7 cost centers, 7 budgets, 2 enterprise teams |

## 2. Test method

All comparison scripts are in [`tests/parity/`](tests/parity/) and can be rerun as-is (see section 7).

1. **Side by side**: `start.sh` makes two copies of a real `data/` directory and starts the Python backend on one and the Go backend on the other, so both see identical data without affecting each other.
2. **Mock GitHub API**: `mock_github.py` serves every GitHub REST endpoint OctoFinance uses (discovery, seats, billing, usage reports, AI credits, cost centers, budgets, enterprise teams, billing report exports) from the data snapshot. It **applies writes for real** (create/update/delete budgets, add/remove cost center members, remove seats, and so on) and records every request. Each backend gets its own mock instance, so write operations can be tested fully and safely, and the requests both backends send to GitHub can be compared one by one. The Go backend reaches the mock through the test-only `OCTOFINANCE_GITHUB_API_BASE` environment variable; the Python copy gets the same patch at startup, and the original Python code is not changed.
3. **Comparison tools**

   | Script | Purpose |
   |--------|---------|
   | `parity.py` | Sends the same request to both backends and compares status codes and JSON responses (1e-6 numeric tolerance, timestamp-like fields ignored) |
   | `tooldiff.py` | Calls the same AI tool with the same arguments (Python calls the tool handler directly, Go uses `octofinance-go -tool`) and compares the output |
   | `datadiff.py` | Compares every JSON / JSONL / CSV file in the two `data/` directories |
   | `synclog.py` | Subscribes to `/api/sync-stream` on both sides, triggers a sync and compares the sync logs line by line |
   | `bench.py` | Load-tests the same endpoints with concurrent requests |
   | `e2e.py` | Headed Chrome browser end-to-end test (Playwright) |

## 3. Behavioural parity results

### 3.1 HTTP API (every endpoint covered)

| Area | Endpoints | Result |
|------|-----------|--------|
| Authentication | `/api/auth/*` (status, setup, login, logout, GitHub OAuth login/callback/config) | Identical |
| PATs and settings | `/api/pats` (add/update/delete, token replacement, organization-scan toggle, GHE.com enterprise URL parsing), `/api/settings` | Identical |
| Sync | `/api/sync`, `/api/sync/{org}`, `/api/sync/dataset/{dataset}`, `/api/sync/status`, `/api/sync-stream` | Identical |
| Sessions / prompts | `/api/sessions/*`, `/api/prompts/*` | Identical |
| Dashboards | All 17 `/api/data/*` endpoints: dashboard, csv-dashboard, cost-center-dashboard, enterprise-teams-dashboard, budgets-dashboard, overview, orgs, seats, billing, user-roster, unassigned users + assign, ai-credit-pool, upload-csv, fetch-csv, csv-info, cost-center-report (ZIP) | Identical across 60+ parameter combinations (organization / enterprise team / user / date filters, period=current_month, search, unknown values) |
| Personal portal | `/api/me/dashboard`, `/api/me/cost-centers`, `/api/me/budget` | Identical; exact field-by-field comparison for 6 different users across several date ranges |
| Budget / cost center requests | All 7 `/api/budget-requests/*` endpoints | Identical across a 69-step lifecycle (submit, validation errors, approve/reject, amount change, resync, audit, delete, and every permission case) |
| Cost center owners | `/api/data/cost-center-owner(s)`, `/api/me/owned-cost-center*` | Identical |
| Shared reports | `/api/data/cost-center-share(s)` and the public `/share/cc/{token}` pages (password check, cookies, download) | Identical; **the report HTML is byte-identical to Python's** (only the generation time differs), and the ZIP contents match |
| Recommended actions | `/api/actions/*` | Identical |
| Health check | `/api/health` | Identical (Go additionally returns `"backend": "go"`) |
| Permissions | 403 for a regular user calling admin endpoints, 401 when not logged in | Identical |

Regression sweep after the final merge: all 39 endpoint/parameter combinations `OK`.

### 3.2 AI tools (44)

- Tool names, descriptions and parameter schemas (names, types, defaults, required fields, enums, constraints such as `gt=0`) were checked one by one against Python and match. Tools are registered in the same order as in Python.
- About 160 `tooldiff.py` calls covered default arguments, specific organizations/enterprises, unknown objects and edge values (`days=0`, negative amounts, empty lists, and so on). Every read-only tool gives the same output.
- Write tools (remove seats, add team members, record recommendations, create/update/delete cost centers, create/update/delete budgets, batch-create user budgets, create/update/delete enterprise teams and manage their members/organizations, `sync_data`) give the same output, **send exactly the same request sequence to the GitHub mock (method, path, body)**, and write the same data files.

### 3.3 Data files and sync

- After a full sync (`POST /api/sync`), the **70 data files written by each side have identical content** (including the day-by-day merged usage history).
- The sync logs match line by line (74 lines).
- Single-dataset syncs (cost_centers / budgets / enterprise_teams), single-organization syncs and session-directory syncs all match.
- CSV upload: the stored CSV files are byte-identical on both sides.

### 3.4 Headed browser end-to-end test (`e2e.py`)

Run with the local Google Chrome (headed, slowed down), the same script against each backend:

| Step | Go | Python |
|------|----|--------|
| 1. First start: create the admin account | ✅ | ✅ |
| 2. All 8 dashboard tabs render correctly (Usage Metrics, AI Usage, Usage Report, Cost Centers, Unassigned Users, Enterprise Teams, Budgets, Requests) | ✅ | ✅ |
| 3. Click Sync Data; the sync completes | ✅ | ✅ |
| 4. The Settings page lists the PAT | ✅ | ✅ |
| 5. AI chat: ask a question in a new session; the model calls tools (on Go: `list_cost_centers`, `get_all_seats`, `get_enterprise_team`) and renders a table answer | ✅ | ✅ |
| 6. A regular GitHub user submits a budget request in the personal portal | ✅ | ✅ |
| 7. The admin approves it and the budget is written to GitHub (`PATCH .../budgets/{id}`, `budget_amount: 123`) | ✅ | ✅ |

### 3.5 Docker

The Go backend has its own image, built from [`Dockerfile-go`](../Dockerfile-go) (the Python backend keeps its original [`Dockerfile`](../Dockerfile), unchanged). Full multi-stage build:

| Stage | Result |
|-------|--------|
| `frontend` (node:22-alpine, `npm ci` + `npm run build`) | ✅ |
| `gobuild` (golang:1.25-alpine, `go mod download` + static build of `octofinance-go`) | ✅ |
| `cli` (golang:1.25-alpine, resolve the latest Copilot CLI release (1.0.93), download and checksum-verify it; no packages installed) | ✅ |
| `runtime` (debian:bookworm-slim + Go binary + frontend + CLI; no packages installed) | ✅ |
| Architectures | ✅ linux/arm64 and linux/amd64 (the two platforms the release workflow builds) |

Image size:

| Image | Compressed (download size) | Unpacked |
|-------|---------------------------:|---------:|
| Go backend (`Dockerfile-go`), linux/arm64 | **117 MB** | ~266 MB |
| Python backend v1.5.0 (`Dockerfile`), for comparison | 155 MB | ~400 MB |

Unpacked, the Go image is the Debian base (108 MB), the Copilot CLI (146 MB, needed for AI chat), the Go binary (9.8 MB) and the frontend (1.4 MB).

Image runtime checks:

| Check | Result |
|-------|--------|
| The container starts the Go backend (`/api/health` returns `"backend": "go"`); the frontend and favicon are served | ✅ |
| Runs as the non-root user `octofinance` (uid 1000, same as the Python image, so an existing data volume stays writable); Copilot CLI 1.0.93 available | ✅ |
| AI chat inside the container calls tools (`get_synced_enterprise_data`) | ✅ |
| `docker run <image> -version` passes arguments to the Go binary | ✅ |

Versions: the Copilot CLI and the Copilot Go SDK default to their **latest release at build time**; the final build resolved CLI 1.0.93 and SDK v1.0.17 (the build log prints both). Pinning was also verified: `--build-arg COPILOT_CLI_VERSION=1.0.68 --build-arg COPILOT_SDK_VERSION=go.mod` builds with exactly those versions.

Re-verification with SDK v1.0.17 and CLI 1.0.93: `go build`, `go vet` and `go test ./...` pass; the AI engine starts, authenticates and lists models; chat calls the OctoFinance tools, both from source and inside the container. Two changes in the newer versions were found:

- SDK v1.0.17 no longer falls back to the `copilot` binary on `PATH` (v1.0.5 did). The engine now sets `COPILOT_CLI_PATH` from `PATH` when it is not set, so running from source keeps working; the image sets it explicitly.
- CLI 1.0.93 exposes built-in tools that 1.0.68 did not (for example `skill` and the GitHub MCP server), and the model may call them alongside the OctoFinance tools.

Build note: `docker build -f Dockerfile-go .` (no cache) succeeded on the first try **without any proxy arguments**, for linux/arm64 and linux/amd64. No stage installs distro packages: the CLI is downloaded with the `wget`, `sha256sum` and `tar` already in `golang:1.25-alpine`, and the runtime stage copies the CA certificate bundle from that stage. An earlier `apt-get`-based version of the `cli` stage kept failing on this network with HTTP 502 from the Debian mirror. If your network requires a proxy, pass `--build-arg HTTP_PROXY=http://host.docker.internal:<port> --build-arg HTTPS_PROXY=...` (`host.docker.internal` points at the host).

## 4. Performance

Method: `bench.py` warms each endpoint up with 3 requests, then sends requests from N concurrent threads and records throughput and latency. Both sides use the same data on the same machine, and only one backend is loaded at a time.

### 4.1 16 concurrent requests (200 requests per endpoint)

| Endpoint | Backend | Throughput (req/s) | p50 (ms) | p95 (ms) | Go throughput gain |
|----------|---------|-------------------:|---------:|---------:|-------------------:|
| `/api/data/dashboard` (main dashboard) | Python | 20.2 | 791.3 | 810.3 | |
| | **Go** | **2801.3** | **4.8** | **8.7** | **×138.7** |
| `/api/data/csv-dashboard` | Python | 60.0 | 262.1 | 295.7 | |
| | **Go** | **1692.2** | **8.5** | **13.1** | **×28.2** |
| `/api/data/cost-center-dashboard` | Python | 2251.3 | 6.9 | 7.3 | |
| | **Go** | **6585.7** | **2.2** | **3.6** | **×2.9** |
| `/api/data/enterprise-teams-dashboard` | Python | 53.0 | 299.8 | 318.7 | |
| | **Go** | **4815.5** | **2.8** | **4.7** | **×90.8** |
| `/api/data/overview` | Python | 296.3 | 53.7 | 55.3 | |
| | **Go** | **6088.3** | **2.3** | **3.9** | **×20.5** |
| `/api/me/dashboard` (personal portal) | Python | 30.0 | 530.5 | 555.0 | |
| | **Go** | **489.8** | **30.3** | **48.1** | **×16.4** |

### 4.2 Single request (concurrency 1, 40 requests per endpoint)

| Endpoint | Python p50 (ms) | Go p50 (ms) | Go throughput gain |
|----------|----------------:|------------:|-------------------:|
| `/api/data/dashboard` | 49.5 | 1.7 | ×27.0 |
| `/api/data/csv-dashboard` | 16.6 | 4.1 | ×4.0 |
| `/api/data/cost-center-dashboard` | 0.6 | 0.3 | ×2.3 |
| `/api/data/enterprise-teams-dashboard` | 20.5 | 0.9 | ×24.0 |
| `/api/data/overview` | 3.6 | 0.4 | ×9.1 |
| `/api/me/dashboard` | 34.1 | 6.6 | ×5.5 |

### 4.3 Interpretation

- **Faster single requests**: the Go computation itself is faster, and the parsed merged billing CSVs and JSON data snapshots are cached by file modification time while pages use them, instead of being re-read and re-parsed on every request (Python re-reads the files each time; see 4.4 for how long the caches are kept).
- **The gap widens under concurrency**: Python's dashboard computation is CPU-bound synchronous code that runs serially in a single worker's event loop, so requests queue up as concurrency rises (main dashboard p50 goes from 49 ms to 791 ms). Go handles requests in parallel across cores, and its p50 barely changes with concurrency (1.7 ms → 4.8 ms).
- Both effects grow as data volume and user count increase.
- AI chat time is dominated by model inference; the two backends show no material difference there.

### 4.4 Memory (Docker, large synthetic enterprise)

Measured with `docker stats` and per-process RSS in the Go and Python images on the same data copy, scaled up to a large enterprise: 1,736 seats, about 68,000 user-day usage records (usage JSON files of 185 MB), a 60,000-row AI usage CSV and a 356,000-row usage report CSV (284 MB of data in total). The Copilot CLI runs in both containers and takes about 230–270 MB on its own; the table shows the backend process only.

| Step | Python | Go before the fix | Go after the fix |
|------|-------:|------------------:|-----------------:|
| Idle after startup | 99 MB | 14 MB | 16 MB |
| After opening all 11 dashboards once | 160 MB (peak 491 MB) | 1,468 MB | 1,148 MB (peak 1,092 MB) |
| After 44 concurrent dashboard requests | 275 MB (peak 516 MB) | 2,155 MB | 1,258 MB |
| After ingesting a 45 MB usage report CSV | 229 MB (peak 1,158 MB) | 2,698 MB | 1,400 MB (peak 1,438 MB) |
| 60 s later, idle | 229 MB | 2,698 MB (never released) | **64 MB** |
| Container total (`docker stats`) when idle again | 348 MiB | about 2.9 GiB | **252 MiB** |

Time for the same steps, Python / Go after the fix: all dashboards 16.8 s / 4.1 s, 44 concurrent requests 46.6 s / 2.0 s, CSV ingest 6.7 s / 1.4 s.

Cause and fix:

- **Cause**: to make dashboards fast, the Go backend kept every parsed data file and CSV export in memory for good. Decoded into Go maps, they take 3–6 times their size on disk, and Go's garbage collector lets the heap grow to twice what is live before collecting. Python re-parses the files on each request and keeps nothing, so it stays small but is slower.
- **Caches are released when idle**: large files (4 MB and up) stay cached only for 15 seconds after their last use, which is long enough to serve the requests a page makes together. Small files stay cached for 3 minutes. Freed memory is returned to the operating system immediately.
- **One parse per file**: concurrent requests that need the same file wait for a single parse instead of each decoding a copy.
- **Smaller decoded data**: the JSON parser and the CSV reader keep one copy of each repeated key and short value (field names, dates, logins, model names). On an 85 MB usage file this needs 40% less memory than `encoding/json`, and parsing is 25% faster. A fuzz test with 16 million inputs checks that it returns exactly what `encoding/json` returns.
- **No double parsing**: the user roster caches only logins, not the files it reads them from. CSV ingest reuses the rows the dashboards already parsed and caches the merged result for the dashboard that follows.
- **GC tuning**: `GOGC` defaults to 50 (the peak is about a quarter lower, at no measurable cost in response time). When the container has a memory limit (`docker run -m`), the Go GC gets a soft limit of 60% of it. `GOGC` and `GOMEMLIMIT` set in the environment take precedence.

Short peaks while dashboards load or a CSV is ingested remain higher than with Python, because Go processes the work in parallel instead of one request at a time. They last a few seconds and are released within about 20 seconds.

## 5. Known differences (all harmless or intentional)

| Difference | Details |
|------------|---------|
| Random IDs / timestamps | Session IDs, PAT IDs, prompt IDs, budget UUIDs generated by the mock, and so on differ on every run |
| Number formatting | In written files Python writes `20.0` and Go writes `20`; the values are the same and each backend reads the other's files |
| JSON key order | Some files written by Go have alphabetically sorted keys; the JSON meaning is the same |
| 422 validation error details | Status 422 matches for missing fields, wrong types, and so on, but in some cases Go omits pydantic's `input` / `ctx` fields or the error text differs; the frontend does not depend on these fields |
| `tool_complete` tool name | Python records `null`; Go fills in the tool name from the matching `tool_start` |
| `fetch_org_usage_report` and 2 other live-fetch tools | The Python versions call `run_until_complete` inside a running event loop and fail on every call; the Go versions implement the intended behaviour |
| Requests stored with `history: null` | Python's approval returns 500; Go treats it as an empty history and carries on (only hand-made data triggers this) |
| Frontend static files | Python returns `index.html` for root-level files such as `/copilot.svg`; Go returns the real file (the favicon shows correctly) |

## 6. Unit tests

`go test ./...` covers: Python-compatible `round()`, truthiness, ISO timestamp parsing, day differences, GitHub host parsing, session title generation, cron descriptions, usage history merging, synthetic enterprise billing, and the registration order of the 44 tools. All pass, and `go vet` reports no warnings.

## 7. How to reproduce

Requirements: Go 1.24+; the Python backend dependencies installed in `.venv` at the repository root; for the end-to-end test also `pip install playwright` and a local Google Chrome.

```bash
cd backend-go/tests/parity

# Start a backend pair (Python 27001 / Go 27002; each one's mock GitHub runs on port +500)
# Runs go to /tmp/octofinance-parity by default; change with PARITY_RUNS
PARITY_USER=real-akimoto-akira ./start.sh demo 27001 27002 "$(cd ../.. && pwd)"

python3 parity.py demo /api/data/dashboard "/api/data/dashboard?period=current_month"
python3 parity.py demo --user /api/me/dashboard          # as a regular user
python3 tooldiff.py demo get_cost_overview '{}'
python3 datadiff.py demo                                   # compare both data/ directories
python3 synclog.py demo /api/sync 40                       # trigger a sync and compare logs
python3 bench.py demo 16 200                               # load test
FRESH_AUTH=1 ./start.sh demo 27001 27002 "$(cd ../.. && pwd)"   # remove the admin account so E2E tests first-run setup
python3 e2e.py http://127.0.0.1:27002 /tmp/octofinance-parity/demo/go/data 27502 go

./stop.sh demo
```

Note: the tests only run on copies of the data and only talk to the mock GitHub, so they never change the real `data/` directory or anything on the real GitHub.
