# Go 后端 vs Python 后端：对比测试报告

> 版本：OctoFinance v2.0.0（测试在版本号由 1.6.0 改为 2.0.0 之前、基于同一份代码进行）　|　测试日期：2026-10-07 ~ 2026-10-08　|　[English](TEST_REPORT.md)
> 结论：Go 后端在全部 API、AI 工具、数据文件和 UI 流程上与 Python 后端行为一致；
> 16 个并发请求下，主要看板接口吞吐提升 **16 ~ 139 倍**（详见第 4 节）。

## 1. 测试环境

| 项目 | 说明 |
|------|------|
| 机器 | Apple M4 Pro，12 核，48 GB 内存，macOS |
| Go 后端 | Go 1.25.6；第 3.1–3.4 节和第 4 节的对比测试使用 Copilot Go SDK `github.com/github/copilot-sdk/go` v1.0.5，当前 `go.mod` 中的 v1.0.17 按第 3.5 节所述重新验证（均为 SDK 协议 v3） |
| Python 后端 | Python 3.13.5，FastAPI + uvicorn（单 worker），`github-copilot-sdk` 1.0.5（SDK 协议 v3） |
| Copilot CLI | 本地 1.0.89；首轮 Docker 镜像测试为 1.0.68；最终 Docker 镜像测试为构建时的最新版 1.0.93 |
| 测试数据 | 真实 `data/` 目录的副本（约 12 MB）：6 个组织 + 1 个企业，10 个 seat 快照（26 个席位），1,244 条用户级 usage 记录，AI usage CSV 347 行，usage report CSV 2,502 行，7 个成本中心，7 个预算，2 个企业团队 |

## 2. 测试方法

所有对比脚本都在 [`tests/parity/`](tests/parity/) 下，可直接复现（见第 7 节）。

1. **并排运行**：`start.sh` 把真实 `data/` 复制两份，分别启动 Python 后端和 Go 后端，两者数据完全相同、互不干扰。
2. **Mock GitHub API**：`mock_github.py` 以数据快照为来源，模拟 OctoFinance 用到的全部 GitHub REST 接口（发现、席位、账单、usage 报表、AI credits、成本中心、预算、企业团队、账单报表导出），并**真实执行写操作**（创建/修改/删除预算、增删成本中心成员、移除席位等）、记录所有请求。两个后端各连一个独立的 mock 实例，因此写操作可以安全地完整测试，且能逐条比对两个后端发给 GitHub 的请求。（Go 后端通过仅供测试的 `OCTOFINANCE_GITHUB_API_BASE` 环境变量指向 mock；Python 副本在启动时做同样的补丁，原 Python 代码不改动。）
3. **对比工具**

   | 脚本 | 作用 |
   |------|------|
   | `parity.py` | 对同一请求比对两个后端的状态码和 JSON 响应（数值 1e-6 容差，忽略时间戳类字段） |
   | `tooldiff.py` | 用相同参数调用同一个 AI 工具（Python 直接调用工具 handler，Go 用 `octofinance-go -tool`），比对输出 |
   | `datadiff.py` | 比对两边 `data/` 目录下所有 JSON / JSONL / CSV 文件 |
   | `synclog.py` | 同时订阅两边的 `/api/sync-stream`，触发同步，逐行比对同步日志 |
   | `bench.py` | 并发压测相同接口 |
   | `e2e.py` | 有头 Chrome 浏览器端到端测试（Playwright） |

## 3. 功能一致性结果

### 3.1 HTTP API（全部接口均已覆盖）

| 模块 | 接口 | 结果 |
|------|------|------|
| 认证 | `/api/auth/*`（status、setup、login、logout、GitHub OAuth login/callback/config） | 一致 |
| PAT 与设置 | `/api/pats`（增删改、换 token、开关组织扫描、GHE.com 企业 URL 解析）、`/api/settings` | 一致 |
| 同步 | `/api/sync`、`/api/sync/{org}`、`/api/sync/dataset/{dataset}`、`/api/sync/status`、`/api/sync-stream` | 一致 |
| 会话 / 提示词 | `/api/sessions/*`、`/api/prompts/*` | 一致 |
| 看板 | `/api/data/*` 全部 17 个接口：dashboard、csv-dashboard、cost-center-dashboard、enterprise-teams-dashboard、budgets-dashboard、overview、orgs、seats、billing、user-roster、unassigned users + assign、ai-credit-pool、upload-csv、fetch-csv、csv-info、cost-center-report（ZIP） | 一致；含组织/企业团队/用户/日期/period=current_month/搜索/未知参数等 60+ 种参数组合 |
| 个人门户 | `/api/me/dashboard`、`/api/me/cost-centers`、`/api/me/budget` | 一致；6 个不同用户 × 多种时间范围逐字段精确比对 |
| 预算 / 成本中心申请 | `/api/budget-requests/*` 全部 7 个接口 | 一致；69 步完整生命周期（提交、校验错误、审批/拒绝、改额度、重新同步、审计、删除及各类权限） |
| 成本中心负责人 | `/api/data/cost-center-owner(s)`、`/api/me/owned-cost-center*` | 一致 |
| 分享报告 | `/api/data/cost-center-share(s)` 及公开页面 `/share/cc/{token}`（密码校验、cookie、下载） | 一致；**报告 HTML 与 Python 逐字节相同**（仅生成时间不同），ZIP 内容一致 |
| 推荐操作 | `/api/actions/*` | 一致 |
| 健康检查 | `/api/health` | 一致（Go 额外返回 `"backend": "go"`） |
| 权限 | 普通用户访问管理员接口返回 403、未登录返回 401 | 一致 |

最终合并后的回归扫描：39 个接口/参数组合全部 `OK`。

### 3.2 AI 工具（44 个）

- 工具名称、描述、参数 schema（名称、类型、默认值、必填项、枚举、`gt=0` 等约束）与 Python 逐一核对一致，注册顺序与 Python 相同。
- 约 160 次 `tooldiff.py` 调用，覆盖默认参数、指定组织/企业、未知对象、边界值（`days=0`、负数金额、空列表等）。所有只读工具输出一致。
- 写操作工具（移除席位、加团队成员、记录推荐、成本中心增删改、预算增删改、批量创建用户预算、企业团队增删改及成员/组织管理、`sync_data`）：输出一致，**发给 GitHub mock 的请求序列（方法、路径、请求体）完全一致**，写入的数据文件一致。

### 3.3 数据文件与同步

- 完整同步（`POST /api/sync`）后，两边写出的 **70 个数据文件内容一致**（含按天合并的 usage 历史）。
- 同步日志逐行一致（74 行）。
- 单数据集同步（cost_centers / budgets / enterprise_teams）、单组织同步、会话目录同步均一致。
- CSV 上传：两边存储的 CSV 文件逐字节一致。

### 3.4 有头浏览器端到端测试（`e2e.py`）

使用本机 Google Chrome（有头、慢速），同一脚本分别对两个后端运行：

| 步骤 | Go | Python |
|------|----|--------|
| 1. 首次启动创建管理员账户 | ✅ | ✅ |
| 2. 8 个看板标签页全部正常渲染（Usage Metrics、AI Usage、Usage Report、Cost Centers、Unassigned Users、Enterprise Teams、Budgets、Requests） | ✅ | ✅ |
| 3. 点击 Sync Data，同步完成 | ✅ | ✅ |
| 4. 设置页列出 PAT | ✅ | ✅ |
| 5. AI 对话：新会话中提问，模型调用工具（Go 实测调用了 `list_cost_centers`、`get_all_seats`、`get_enterprise_team`）并渲染表格答案 | ✅ | ✅ |
| 6. 普通 GitHub 用户在个人门户提交预算申请 | ✅ | ✅ |
| 7. 管理员批准，预算写入 GitHub（`PATCH .../budgets/{id}`，`budget_amount: 123`） | ✅ | ✅ |

### 3.5 Docker

Go 后端使用独立的镜像，由 [`Dockerfile-go`](../Dockerfile-go) 构建（Python 后端保留原有的 [`Dockerfile`](../Dockerfile)，未做改动）。完整多阶段构建：

| 阶段 | 结果 |
|------|------|
| `frontend`（node:22-alpine，`npm ci` + `npm run build`） | ✅ |
| `gobuild`（golang:1.25-alpine，`go mod download` + 静态编译 `octofinance-go`） | ✅ |
| `cli`（golang:1.25-alpine，解析 Copilot CLI 最新版本（1.0.93）并下载、校验，不安装任何软件包） | ✅ |
| `runtime`（debian:bookworm-slim + Go 二进制 + 前端 + CLI，不安装任何软件包） | ✅ |
| 架构 | ✅ linux/arm64 与 linux/amd64（发布工作流构建的两个平台） |

镜像大小：

| 镜像 | 压缩后（下载大小） | 解压后 |
|------|------------------:|------:|
| Go 后端（`Dockerfile-go`），linux/arm64 | **117 MB** | 约 266 MB |
| Python 后端 v1.5.0（`Dockerfile`），作对比 | 155 MB | 约 400 MB |

解压后的 Go 镜像由 Debian 基础镜像（108 MB）、Copilot CLI（146 MB，AI 对话必需）、Go 二进制（9.8 MB）和前端（1.4 MB）组成。

镜像运行验证：

| 检查项 | 结果 |
|--------|------|
| 容器启动 Go 后端（`/api/health` 返回 `"backend": "go"`），前端页面和 favicon 正常返回 | ✅ |
| 以非 root 用户 `octofinance`（uid 1000，与 Python 镜像相同，已有数据卷可继续写入）运行，Copilot CLI 1.0.93 可用 | ✅ |
| 容器内 AI 对话并调用工具（`get_synced_enterprise_data`） | ✅ |
| `docker run <镜像> -version` 参数直接传给 Go 二进制 | ✅ |

版本：Copilot CLI 和 Copilot Go SDK 默认在**构建时取最新发布版本**；最终构建解析到 CLI 1.0.93 和 SDK v1.0.17（构建日志会打印两者）。也验证了固定版本：`--build-arg COPILOT_CLI_VERSION=1.0.68 --build-arg COPILOT_SDK_VERSION=go.mod` 会严格使用这两个版本构建。

用 SDK v1.0.17 和 CLI 1.0.93 重新验证：`go build`、`go vet`、`go test ./...` 通过；AI 引擎启动、认证并列出模型；无论从源码运行还是在容器内，对话都会调用 OctoFinance 工具。发现新版本有两处变化：

- SDK v1.0.17 不再回退到 `PATH` 上的 `copilot`（v1.0.5 会回退）。引擎现在会在未设置 `COPILOT_CLI_PATH` 时从 `PATH` 找到 CLI 并设置该变量，因此源码运行不受影响；镜像中则显式设置了该变量。
- CLI 1.0.93 提供了 1.0.68 没有的内置工具（例如 `skill` 和 GitHub MCP server），模型可能会在调用 OctoFinance 工具的同时调用它们。

构建说明：`docker build -f Dockerfile-go .`（无缓存）**无需任何代理参数**，linux/arm64 和 linux/amd64 都一次构建成功。所有阶段都不安装发行版软件包：CLI 用 `golang:1.25-alpine` 自带的 `wget`、`sha256sum`、`tar` 下载校验，运行时阶段从该阶段复制 CA 证书。之前基于 `apt-get` 的 `cli` 阶段在测试网络下反复因 Debian 镜像源 HTTP 502 失败。若所在网络必须走代理，可传入 `--build-arg HTTP_PROXY=http://host.docker.internal:<端口> --build-arg HTTPS_PROXY=...`（`host.docker.internal` 指向宿主机）。

## 4. 性能对比

压测方法：`bench.py`，每个接口先预热 3 次，再用 N 个并发线程发送请求，记录吞吐和延迟。两边数据相同、同一台机器、同时只压一个后端。

### 4.1 16 个并发请求（每个接口 200 次）

| 接口 | 后端 | 吞吐 (req/s) | p50 (ms) | p95 (ms) | Go 吞吐倍数 |
|------|------|-------------:|---------:|---------:|----------:|
| `/api/data/dashboard`（主看板） | Python | 20.2 | 791.3 | 810.3 | |
| | **Go** | **2801.3** | **4.8** | **8.7** | **×138.7** |
| `/api/data/csv-dashboard` | Python | 60.0 | 262.1 | 295.7 | |
| | **Go** | **1692.2** | **8.5** | **13.1** | **×28.2** |
| `/api/data/cost-center-dashboard` | Python | 2251.3 | 6.9 | 7.3 | |
| | **Go** | **6585.7** | **2.2** | **3.6** | **×2.9** |
| `/api/data/enterprise-teams-dashboard` | Python | 53.0 | 299.8 | 318.7 | |
| | **Go** | **4815.5** | **2.8** | **4.7** | **×90.8** |
| `/api/data/overview` | Python | 296.3 | 53.7 | 55.3 | |
| | **Go** | **6088.3** | **2.3** | **3.9** | **×20.5** |
| `/api/me/dashboard`（个人门户） | Python | 30.0 | 530.5 | 555.0 | |
| | **Go** | **489.8** | **30.3** | **48.1** | **×16.4** |

### 4.2 单请求（并发 1，每个接口 40 次）

| 接口 | Python p50 (ms) | Go p50 (ms) | Go 吞吐倍数 |
|------|----------------:|------------:|----------:|
| `/api/data/dashboard` | 49.5 | 1.7 | ×27.0 |
| `/api/data/csv-dashboard` | 16.6 | 4.1 | ×4.0 |
| `/api/data/cost-center-dashboard` | 0.6 | 0.3 | ×2.3 |
| `/api/data/enterprise-teams-dashboard` | 20.5 | 0.9 | ×24.0 |
| `/api/data/overview` | 3.6 | 0.4 | ×9.1 |
| `/api/me/dashboard` | 34.1 | 6.6 | ×5.5 |

### 4.3 解读

- **单请求更快**：Go 计算本身更快，且合并后的账单 CSV 和数据快照 JSON 在页面使用期间按文件修改时间缓存解析结果，不再每个请求重新读取解析（Python 每次请求都重新读文件；缓存保留多久见 4.4）。
- **并发下差距进一步拉大**：Python 的看板计算是 CPU 密集的同步代码，在单 worker 的事件循环里串行执行，并发越高排队越长（主看板 p50 从 49 ms 涨到 791 ms）；Go 的请求在多核上并行处理，p50 基本不随并发增长（1.7 ms → 4.8 ms）。
- 数据量和用户数增加时，这两点的收益都会更明显。
- AI 对话的耗时主要取决于模型推理，两个后端无实质差别。

### 4.4 内存（Docker，大型企业模拟数据）

在 Go 和 Python 两个镜像中，用同一份数据副本测量 `docker stats` 和各进程 RSS。数据按大型企业放大：1,736 个席位，约 68,000 条按用户按天的 usage 记录（usage JSON 文件共 185 MB），60,000 行 AI usage CSV，356,000 行 usage report CSV（数据共 284 MB）。两个容器中都运行 Copilot CLI，它本身占约 230–270 MB；下表只列后端进程。

| 步骤 | Python | Go 修复前 | Go 修复后 |
|------|-------:|----------:|----------:|
| 启动后空闲 | 99 MB | 14 MB | 16 MB |
| 依次打开全部 11 个看板后 | 160 MB（峰值 491 MB） | 1,468 MB | 1,148 MB（峰值 1,092 MB） |
| 44 个并发看板请求后 | 275 MB（峰值 516 MB） | 2,155 MB | 1,258 MB |
| 导入 45 MB usage report CSV 后 | 229 MB（峰值 1,158 MB） | 2,698 MB | 1,400 MB（峰值 1,438 MB） |
| 60 秒后，空闲 | 229 MB | 2,698 MB（一直不释放） | **64 MB** |
| 再次空闲时容器总计（`docker stats`） | 348 MiB | 约 2.9 GiB | **252 MiB** |

同样步骤的耗时（Python / 修复后的 Go）：打开全部看板 16.8 s / 4.1 s，44 个并发请求 46.6 s / 2.0 s，导入 CSV 6.7 s / 1.4 s。

原因与修复：

- **原因**：为了让看板更快，Go 后端把解析过的每个数据文件和 CSV 导出都永久保存在内存里。这些数据解码成 Go map 后是磁盘大小的 3–6 倍，而 Go 的垃圾回收会等堆增长到存活数据的两倍才回收。Python 每个请求重新解析文件、什么都不保留，所以内存小，但更慢。
- **空闲即释放缓存**：大文件（4 MB 及以上）在最后一次使用后只缓存 15 秒，足够覆盖一个页面同时发出的那几个请求；小文件缓存 3 分钟。释放的内存立即归还操作系统。
- **同一文件只解析一次**：并发请求需要同一个文件时，等待同一次解析，不再各自解码一份。
- **解码后的数据更小**：JSON 解析器和 CSV 读取器对重复的键和短值（字段名、日期、登录名、模型名）只保留一份。对一个 85 MB 的 usage 文件，内存比 `encoding/json` 少 40%，解析快 25%。用 1,600 万个输入的模糊测试验证其结果与 `encoding/json` 完全一致。
- **不再重复解析**：用户名单只缓存登录名，不再缓存它读取的整个文件。导入 CSV 时复用看板已解析的行，并把合并结果缓存给随后的看板使用。
- **GC 调优**：`GOGC` 默认为 50（峰值约降低四分之一，响应时间无可测差异）。容器设置了内存上限（`docker run -m`）时，Go GC 使用其 60% 作为软上限。环境变量中设置的 `GOGC` 和 `GOMEMLIMIT` 优先。

看板加载或导入 CSV 时的短暂峰值仍高于 Python，因为 Go 并行处理，而不是一次处理一个请求。峰值持续几秒，约 20 秒内释放。

## 5. 已知差异（均为无害或刻意保留）

| 差异 | 说明 |
|------|------|
| 随机 ID / 时间戳 | 会话 ID、PAT ID、提示词 ID、mock 生成的预算 UUID 等每次都不同 |
| 数字写法 | 写入文件时 Python 写 `20.0`，Go 写 `20`；数值相同，两边读取互通 |
| JSON 键顺序 | 部分 Go 写出的文件键按字母排序；JSON 语义相同 |
| 422 校验错误细节 | 缺字段、类型错误等返回 422 状态一致，但部分情况下 Go 不带 pydantic 的 `input` / `ctx` 字段或错误文本不同；前端不依赖这些字段 |
| `tool_complete` 工具名 | Python 记录 `null`，Go 会补上对应 `tool_start` 的工具名 |
| `fetch_org_usage_report` 等 3 个实时拉取工具 | Python 版在运行中的事件循环里调用 `run_until_complete`，每次都会报错；Go 版实现了预期行为 |
| 记录中 `history: null` 的请求 | Python 审批会 500，Go 视为空历史继续处理（仅手工构造的数据会触发） |
| 前端静态文件 | Python 对 `/copilot.svg` 等根目录文件也返回 `index.html`；Go 返回真实文件（favicon 可正常显示） |

## 6. 单元测试

`go test ./...` 覆盖：Python 兼容的 `round()`、真值判断、ISO 时间解析、天数差、GitHub 主机解析、会话标题生成、cron 描述、usage 历史合并、企业账单合成、44 个工具的注册顺序。全部通过；`go vet` 无告警。

## 7. 如何复现

依赖：Go 1.24+；仓库根目录 `.venv` 中安装了 Python 后端依赖；端到端测试另需 `pip install playwright` 和本机 Google Chrome。

```bash
cd backend-go/tests/parity

# 启动一对后端（Python 27001 / Go 27002，各自的 mock GitHub 在 +500 端口）
# 运行目录默认 /tmp/octofinance-parity，可用 PARITY_RUNS 修改
PARITY_USER=real-akimoto-akira ./start.sh demo 27001 27002 "$(cd ../.. && pwd)"

python3 parity.py demo /api/data/dashboard "/api/data/dashboard?period=current_month"
python3 parity.py demo --user /api/me/dashboard          # 以普通用户身份
python3 tooldiff.py demo get_cost_overview '{}'
python3 datadiff.py demo                                   # 比对两边 data/ 目录
python3 synclog.py demo /api/sync 40                       # 触发同步并比对日志
python3 bench.py demo 16 200                               # 压测
FRESH_AUTH=1 ./start.sh demo 27001 27002 "$(cd ../.. && pwd)"   # 删除管理员账户，供 E2E 测首次设置
python3 e2e.py http://127.0.0.1:27002 /tmp/octofinance-parity/demo/go/data 27502 go

./stop.sh demo
```

注意：测试只在数据副本上运行，并只访问 mock GitHub，不会修改真实 `data/` 或真实 GitHub 上的任何内容。
