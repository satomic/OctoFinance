[English](README.md) | **简体中文**

# OctoFinance V2 - GitHub Copilot AI FinOps Platform

基于 AI 的 GitHub Copilot 财务运维平台，通过 Copilot SDK 实现智能化席位管理和成本优化。

## 前置条件

- Python 3.13+ (`.venv` 已配置)
- Node.js 22+
- GitHub PAT（已内置于 `backend/app/config.py`，也可通过环境变量 `GITHUB_PAT` 覆盖）
- **GitHub Copilot CLI**（必须安装）— 参考 [安装文档](https://github.com/github/copilot-cli)

### 安装 GitHub Copilot CLI

> 需要有效的 [GitHub Copilot 订阅](https://github.com/features/copilot/plans)。

**Windows**（需要 PowerShell v6+）：
```powershell
winget install GitHub.Copilot
```

**macOS / Linux**（Homebrew）：
```bash
brew install copilot-cli
```

**全平台**（npm）：
```bash
npm install -g @github/copilot
```

**macOS / Linux**（安装脚本）：
```bash
curl -fsSL https://gh.io/copilot-install | bash
```

安装完成后，在终端运行 `copilot`，按提示完成 GitHub 账号认证。

## 启动

### 1. 启动后端

```bash
cd OctoFinanceV2/backend
../.venv/bin/uvicorn app.main:app --reload --port 8000
```

启动后会看到：
```
[OctoFinance] Authenticated as: satomic
[OctoFinance] Discovered 11 organizations: [...]
[OctoFinance] Initial data sync complete.
[OctoFinance] Copilot AI engine ready.
[OctoFinance] Ready!
```

### 2. 启动前端

新开一个终端：

```bash
cd OctoFinanceV2/frontend
npm run dev
```

启动后访问 http://localhost:5173

## 停止

### 方式一：前台进程直接 Ctrl+C

在对应终端窗口按 `Ctrl+C` 即可停止。

### 方式二：后台进程通过端口号杀掉

```bash
# 停止后端 (port 8000)
lsof -ti:8000 | xargs kill

# 停止前端 (port 5173)
lsof -ti:5173 | xargs kill
```

### 方式三：一键停止全部

```bash
lsof -ti:8000 -ti:5173 | xargs kill 2>/dev/null
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查，返回用户/组织/AI引擎状态 |
| `/api/chat` | POST | AI 聊天（SSE 流式响应） |
| `/api/chat/simple` | POST | AI 聊天（等待完整响应） |
| `/api/sync` | POST | 触发全量数据同步 |
| `/api/sync/{org}` | POST | 同步指定组织 |
| `/api/sync/status` | GET | 同步状态 |
| `/api/data/orgs` | GET | 所有已发现的组织 |
| `/api/data/overview` | GET | 全局概览（席位/成本/浪费） |
| `/api/data/seats/{org}` | GET | 指定组织的席位数据 |
| `/api/data/billing/{org}` | GET | 指定组织的账单数据 |
| `/api/actions/pending` | GET | 待审批的 AI 建议 |
| `/api/actions/execute` | POST | 执行建议 |
| `/api/actions/reject` | POST | 拒绝建议 |
