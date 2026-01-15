# SRE Bot Demo

A Slack-integrated incident response bot powered by the **Claude Agent SDK** with real Prometheus metrics.

> **Getting Started?** See [DEMO.md](DEMO.md) for step-by-step setup and run instructions.

---

## What This Demo Shows

- **Claude as the orchestrator**: Claude decides what to investigate, in what order
- **Claude Agent SDK**: Uses subprocess-based MCP server for tool communication
- **Real metrics**: Prometheus scrapes and stores metrics from a simulated service
- **Slack integration**: Real-time incident investigation in Slack threads
- **Streaming output**: Investigation results stream to Slack as they're generated

---

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│ metric_logging  │────▶│   Prometheus    │
│   (Port 8000)   │     │   (Port 9090)   │
└─────────────────┘     └────────┬────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────┐
│          sre_bot_slack.py               │
│  ┌─────────────────────────────────┐    │
│  │  Claude Agent SDK               │    │
│  │  - query() for investigations   │    │
│  │  - Streams to Slack threads     │    │
│  └──────────────┬──────────────────┘    │
│                 │ subprocess            │
│  ┌──────────────▼──────────────────┐    │
│  │  sre_mcp_server.py              │    │
│  │  - JSON-RPC over stdio          │    │
│  │  - query_metrics, list_metrics  │    │
│  │  - get_service_health           │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
           │
           ▼
┌─────────────────┐
│     Slack       │
│  (Bot mentions) │
└─────────────────┘
```

### Key Components

| Component | Description |
|-----------|-------------|
| `sre_bot_slack.py` | Main Slack bot using Claude Agent SDK |
| `sre_mcp_server.py` | MCP server (subprocess) providing investigation tools |
| `scripts/metric_logging.py` | Simulated metrics endpoint exposing Prometheus-format metrics |
| `config/api-server.env` | API server configuration (modify DB_POOL_SIZE to trigger incidents) |

### MCP Tools

Tools available to Claude during investigations:

| Tool | Purpose |
|------|---------|
| `query_metrics` | Run PromQL queries against Prometheus |
| `list_metrics` | Discover available metric names |
| `get_service_health` | Quick health summary across all services |
| `get_logs` | Fetch recent application logs |
| `get_alerts` | Get firing alerts from AlertManager |
| `get_recent_deployments` | List recent deployments |
| `execute_runbook` | Execute structured runbooks for known incidents |

---

## Demo Flow

### Triggering an Incident

1. Edit `config/api-server.env` and set `DB_POOL_SIZE=1` (down from 20)
2. Redeploy: `docker-compose -f config/docker-compose.yml up --build api-server`
3. Observe elevated 500 errors in Prometheus

### End-to-End Flow

| Step | User Action | Bot Response |
|------|-------------|--------------|
| 1 | `@SRE Bot 500 errors spiking, create an incident` | Creates PagerDuty incident, offers to investigate |
| 2 | `yes` | Investigates metrics, identifies DB pool misconfiguration |
| 3 | `yes` (to fix) | Updates `api-server.env` to restore `DB_POOL_SIZE=20`, redeploys |
| 4 | (automatic) | Monitors error rates, confirms they're falling |
| 5 | `yes` (to post-mortem) | Creates Confluence post-mortem, resolves incident |

### What Claude Does During Investigation

1. Calls `get_service_health` to get an overview
2. Calls `query_metrics` for error rates to quantify the problem
3. Calls `query_metrics` for DB connections to find root cause
4. Identifies the misconfigured `DB_POOL_SIZE` setting
5. Offers to fix the configuration and redeploy

---

## Project Structure

```
sre-bot-demo/
├── config/
│   ├── docker-compose.yml      # Prometheus + Grafana setup
│   ├── grafana-datasources.yml # Grafana datasource config
│   └── prometheus.yml          # Prometheus scrape config
├── scripts/
│   └── metric_logging.py       # Simulated metrics endpoint
├── .claude/
│   └── skills/runbook/         # Claude Code skill for runbooks
├── .env                        # API keys (create this)
├── CLAUDE.md                   # Service topology and runbooks
├── DEMO.md                     # Setup and run instructions
├── README.md                   # This file
├── requirements.txt            # Python dependencies
├── sre_bot_slack.py            # Main Slack bot
└── sre_mcp_server.py           # MCP server (subprocess)
```

---

## Slack Bot Features

- **Thread-based**: All investigation output goes to the thread where the bot was mentioned
- **Streaming**: Results appear in real-time as Claude investigates
- **Slack formatting**: Converts Markdown to Slack mrkdwn format
- **Tool visibility**: Shows which tools are being used during investigation

---

## URLs (when running)

| Service | URL | Credentials |
|---------|-----|-------------|
| Prometheus | http://localhost:9090 | — |
| Grafana | http://localhost:3000 | admin / demo |
| Metrics endpoint | http://localhost:8000/metrics | — |

---

## Troubleshooting

### "Cannot connect to Prometheus"

```bash
# Make sure Docker is running
docker-compose -f config/docker-compose.yml up -d

# Check Prometheus is healthy
curl http://localhost:9090/-/healthy
```

### "No metrics data"

```bash
# Make sure metric_logging.py is running
python scripts/metric_logging.py

# Wait 10-15 seconds for Prometheus to scrape
```

### "claude-agent-sdk not found"

```bash
pip install claude-agent-sdk
```

### "Missing SLACK_BOT_TOKEN or SLACK_APP_TOKEN"

Create a `.env` file with your Slack app credentials. You need:
- A Slack app with Socket Mode enabled
- Bot token scopes: `app_mentions:read`, `chat:write`
- Event subscriptions: `app_mention`, `message.im`

---

## Customization

### Trigger an incident

Edit `config/api-server.env`:

```bash
DB_POOL_SIZE=1  # Reduce from 20 to trigger connection exhaustion
```

Then redeploy the container:

```bash
docker-compose -f config/docker-compose.yml up --build api-server
```

### Add more metrics

Add to the `metrics` string in `scripts/metric_logging.py`:

```python
# HELP my_new_metric Description
# TYPE my_new_metric gauge
my_new_metric{label="value"} 42
```

### Add more tools

In `sre_mcp_server.py`, add to the `TOOLS` list and implement a handler in `handle_tool_call()`.
