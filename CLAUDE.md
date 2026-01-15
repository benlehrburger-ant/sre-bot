# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

> **For setup and demo instructions, see [DEMO.md](DEMO.md).**

---

## Project Overview

An SRE incident response bot using the Claude Agent SDK with MCP (Model Context Protocol) tools. Integrates with Slack for real-time incident triage.

---

## Architecture

```
Slack Bot (sre_bot_slack.py)
    │
    └── Claude Agent SDK (subprocess MCP)
            │
            └── MCP Server (sre_mcp_server.py)
                    │
                    ├── Prometheus (localhost:9090)
                    │       │
                    │       └── Metrics Server (scripts/metric_logging.py:8000)
                    │
                    ├── PagerDuty API (api.pagerduty.com)
                    │
                    └── Confluence API (your-domain.atlassian.net)
```

**Key decisions:**
- **Subprocess MCP**: `sre_mcp_server.py` runs as a separate process via stdio/JSON-RPC
- **Streaming**: Results stream to Slack in real-time via async iteration over `query()`
- **Simulated incidents**: Trigger by reducing `DB_POOL_SIZE` in `config/api-server.env` and redeploying
- **Automated remediation**: Bot can modify `api-server.env` to fix configuration issues
- **PagerDuty integration**: Create/manage incidents via REST API v2, receive webhooks
- **Confluence integration**: Auto-publish post-mortems (with user confirmation)
- **Webhook server**: Receives PagerDuty events and posts to Slack (port 3000)

---

## Main Files

| File | Purpose |
|------|---------|
| `sre_bot_slack.py` | Slack bot entry point, streams Agent SDK responses |
| `sre_mcp_server.py` | MCP server with Prometheus queries, health checks, logs, alerts, runbooks |
| `scripts/metric_logging.py` | HTTP server exposing Prometheus-format metrics |
| `.claude/skills/runbook/` | Claude Code skill for SRE runbooks |

---

## MCP Tools

### Investigation Tools

| Tool | Description |
|------|-------------|
| `query_metrics` | Execute PromQL queries against Prometheus |
| `list_metrics` | List available metric names |
| `get_service_health` | Health summary across all services |
| `get_logs` | Fetch application logs (simulated) |
| `get_alerts` | Get firing alerts (simulated) |
| `get_recent_deployments` | List recent deployments (simulated) |
| `execute_runbook` | Execute structured runbooks |

### PagerDuty Tools

| Tool | Description |
|------|-------------|
| `pagerduty_create_incident` | Create incident to page oncall |
| `pagerduty_update_incident` | Acknowledge or resolve incidents |
| `pagerduty_get_incident` | Get incident details |
| `pagerduty_list_incidents` | List active incidents |

### PagerDuty Webhook Setup

The bot includes a webhook server (port 3000) that receives PagerDuty events:

1. Start the bot: `python sre_bot_slack.py`
2. Expose port 3000 (use ngrok for local dev: `ngrok http 3000`)
3. In PagerDuty, go to **Integrations** → **Generic Webhooks (v3)**
4. Add webhook URL: `https://<your-host>/webhooks/pagerduty`
5. Select events: `incident.triggered`

When an incident triggers, the bot posts to `SLACK_INCIDENT_CHANNEL`

### Confluence Tools

| Tool | Description |
|------|-------------|
| `confluence_create_postmortem` | Create post-mortem page (requires user confirmation) |
| `confluence_get_page` | Retrieve existing page by ID or title |
| `confluence_list_postmortems` | Search past post-mortems |

---

## Service Topology (Simulated)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Clients   │────▶│  api-server │────▶│  postgres   │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │                    ▲
                           ▼                    │
                    ┌─────────────┐             │
                    │ payment-svc │─────────────┘
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │  auth-svc   │
                    └─────────────┘
```

| Service | Purpose | Dependencies | DB Pool |
|---------|---------|--------------|---------|
| api-server | Main API gateway | postgres, auth-svc | 100 |
| payment-svc | Payment processing | postgres, auth-svc | 50 |
| auth-svc | Authentication | postgres | 25 |
| postgres | Primary database | — | max=100 |

---

## Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Error rate (5xx) | > 1% | > 5% |
| P99 latency | > 500ms | > 2000ms |
| DB connections | > 70% | > 90% |
| CPU usage | > 70% | > 90% |
| Memory usage | > 80% | > 95% |

---

## Incident Runbooks

### Database Connection Exhaustion

**Symptoms:**
- api-server in CrashLoopBackOff or high error rate
- "Connection refused" or "too many connections" in logs
- `db_connections_active` near max (100)

**Investigation:**
1. Check `db_connections_active` — is it > 90?
2. Check `db_connections_waiting` — are connections queuing?
3. Identify which service is holding connections

**Remediation:**
1. Identify service with connection leak
2. Restart affected pods (temporary)
3. Scale down to release connections
4. Long-term: fix connection pool config

### High Latency Cascade

**Symptoms:**
- P99 latency > 1000ms on api-server
- Downstream services also slow
- Error rate increasing from timeouts

**Investigation:**
1. Check `http_request_duration_milliseconds{quantile="0.99"}`
2. Compare latency across services — where does it start?
3. Check database query times
4. Check resource constraints (CPU, memory)

**Remediation:**
- DB-related: check slow queries, connection pool
- CPU-bound: scale horizontally
- Memory-bound: check for leaks, increase limits

### Elevated Error Rates

**Symptoms:**
- `http_requests_total{status="500"}` increasing
- Alerts from monitoring

**Investigation:**
1. Which service? `rate(http_requests_total{status="500"}[1m]) by (service)`
2. Correlated with latency? Check P99
3. Correlated with resource exhaustion? Check DB connections, CPU
4. Check logs for specific errors

---

## PromQL Reference

```promql
# Error rate per service
sum(rate(http_requests_total{status="500"}[1m])) by (service)

# Error ratio (percentage)
sum(rate(http_requests_total{status="500"}[1m])) by (service)
/ sum(rate(http_requests_total[1m])) by (service)

# P99 latency
http_request_duration_milliseconds{quantile="0.99"}

# DB connection utilization
db_connections_active / db_connections_max

# High CPU services
container_cpu_usage_ratio > 0.8

# High memory services
container_memory_usage_ratio > 0.8
```

---

## Escalation Paths

| Service | Primary Oncall | Escalation |
|---------|----------------|------------|
| api-server | Platform team | #platform-oncall |
| payment-svc | Payments team | #payments-oncall |
| auth-svc | Identity team | #identity-oncall |
| postgres | Database team | #dba-oncall |

---

## Development Reference

### Adding MCP Tools

1. Add tool definition to `TOOLS` list in `sre_mcp_server.py`
2. Implement async handler function
3. Add case to `handle_tool_call()`
4. Update system prompt in `sre_bot_slack.py` if needed
5. Update `.claude/skills/runbook/SKILL.md` if runbook-related

### Triggering an Incident

Edit `config/api-server.env` to reduce the DB pool size:
```bash
DB_POOL_SIZE=1  # Change from 20 to 1 to trigger connection exhaustion
```

Then redeploy the container:
```bash
docker-compose -f config/docker-compose.yml up --build api-server
```

The bot can automatically fix this by restoring `DB_POOL_SIZE=20` when instructed.

### Slack Formatting

The bot converts Markdown to Slack mrkdwn:
- Code blocks: ` ```language ` → ` ``` ` (no language label)
- Bold: `**text**` → `*text*`
- Italic: `*text*` → `_text_`

### Agent SDK Pattern

```python
options = ClaudeAgentOptions(
    system_prompt=SYSTEM_PROMPT,
    mcp_servers={
        "sre": {
            "command": python_path,
            "args": [str(MCP_SERVER_PATH)],
        }
    },
    allowed_tools=["mcp__sre__*"],
    permission_mode="acceptEdits",
)

async for message in query(prompt=incident_text, options=options):
    # Process AssistantMessage, TextBlock, ToolUseBlock, ResultMessage
```
