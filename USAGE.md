**English** | [简体中文](USAGE_CN.md)

# OctoFinance V2 Usage Guide

## Interface Layout

After opening http://localhost:5173, the interface is divided into three areas:

```
┌─────────────────────────────────────────────────────────┐
│  StatusBar: Username · Org Count · AI Status · [Sync]  │
├──────────────┬──────────────────────────────────────────┤
│              │                                          │
│   Sidebar    │            Main Chat Area                │
│              │                                          │
│  Overview    │   Welcome / AI Conversation              │
│  (Summary)   │                                          │
│              │   [Quick Prompt Buttons]                 │
│  Orgs        │                                          │
│  (Org List)  │   User Messages ↔ AI Responses           │
│              │                                          │
│  Pending     │                                          │
│  Actions     │                                          │
│  (Review)    │   ┌─────────────────────────────┐       │
│              │   │  Input  [Clear] [Send/Stop] │       │
│              │   └─────────────────────────────┘       │
└──────────────┴──────────────────────────────────────────┘
```

## Step 1: Check Status

Look at the top **StatusBar**:

- Green dot + username + org count → Backend connected, data synced
- Green dot + "AI Ready" → Copilot AI engine ready for conversation
- Yellow dot + "AI Starting..." → AI engine starting, wait a few seconds

If status looks abnormal, click the **Sync Data** button on the right to manually trigger data sync.

## Step 2: Review Sidebar Overview

The left sidebar automatically displays:

- **Overview**: Total seats, active, inactive, utilization rate, monthly cost, monthly waste
- **Organizations**: All auto-discovered orgs, each showing plan type and seat status
- **Pending Actions**: AI-generated action suggestions awaiting approval (initially empty)

## Step 3: Chat with AI

This is the core feature. Ask questions in natural language in the input box—both English and Chinese work.

### Quick Prompt Buttons (visible on first visit)

| Button | Purpose |
|--------|---------|
| **Overview** | Global Copilot usage and cost overview |
| **Inactive Users** | Find users who haven't used Copilot for 30+ days |
| **Cost Optimization** | Analyze waste and provide optimization suggestions |
| **ROI Analysis** | Calculate Copilot return on investment |

Click any button to get started.

### Common Conversation Examples

**View overview:**
```
Show me the current Copilot usage and costs across all organizations
```

**Find inactive users:**
```
Which users haven't used Copilot in over 30 days? How much money is wasted?
```

**Deep dive into an organization:**
```
How is the Copilot utilization in the nekoaru organization? Who uses it most and who doesn't?
```

**Cost optimization:**
```
Help me analyze where we can save money and provide specific recommendations
```

**ROI analysis:**
```
Is our Copilot investment worth it? What's the cost per active user?
```

**Create action suggestions:**
```
List all inactive users and create suggestions to remove their seats
```

**Cross-organization comparison:**
```
Compare Copilot utilization across organizations—which one has the most waste?
```

**Multi-turn conversation (AI remembers context):**
```
You: Show me inactive users in nekoaru
AI: Found 3 inactive users...should I create removal suggestions?
You: Yes, please create them
AI: Suggestions created, estimated savings of $117/month. Execute now?
You: Not yet, let me think about it
```

## Step 4: Handle AI Suggestions

When AI creates action suggestions, cards appear in the **Pending Actions** sidebar showing:

- Action type (e.g., "remove seats")
- Affected organization and users
- Estimated cost savings
- **Approve & Execute** button → Confirm execution (will actually call GitHub API to remove seats)
- **Reject** button → Decline this suggestion

> ⚠️ **Approve & Execute will perform real actions** (such as removing users' Copilot seats). Please confirm before clicking.

## Tool Indicators During Conversation

During AI responses, you may see small tags above messages:

- ⏳ `get_all_seats` → AI is reading seat data
- ⏳ `find_inactive_users` → AI is analyzing inactive users
- ⏳ `get_cost_overview` → AI is calculating costs
- ⏳ `record_recommendation` → AI is creating action suggestions
- ✅ Tag turns green → Tool execution complete

These tags show which tools AI is using to analyze data—no action needed from you.

## Other Operations

| Operation | Method |
|-----------|--------|
| Manual data sync | Click **Sync Data** button at top |
| Clear conversation | Click **Clear** button left of input box |
| Stop AI response | Click **Stop** button during AI reply |
| Switch language | Ask in Chinese or English, AI will automatically match |
