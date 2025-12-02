# SRE Bot Demo

A Slack-integrated incident response bot powered by the **Claude Agent SDK** with real Prometheus metrics.

## What This Demo Shows

- **Claude as the orchestrator**: Claude decides what to investigate, in what order
- **Claude Agent SDK**: Uses subprocess-based MCP server for tool communication
- **Real metrics**: Prometheus scrapes and stores metrics from a simulated service
- **Slack integration**: Real-time incident investigation in Slack threads
- **Streaming output**: Investigation results stream to Slack as they're generated

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.10+
- Node.js 18+ (for Claude Code CLI)
- Anthropic API key
- Slack Bot Token and App Token

### Setup

```bash
# 1. Install Claude Code CLI (required by Agent SDK)
npm install -g @anthropic-ai/claude-code

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Configure your API keys
# Create .env with:
#   ANTHROPIC_API_KEY=your-anthropic-key
#   SLACK_BOT_TOKEN=xoxb-your-bot-token
#   SLACK_APP_TOKEN=xapp-your-app-token

# 4. Start the metrics server (Terminal 1)
python scripts/metric_logging.py

# 5. Start Prometheus + Grafana (Terminal 2)
docker-compose -f config/docker-compose.yml up

# 6. Start the Slack bot (Terminal 3)
python sre_bot_slack.py

# 7. Wait 60 seconds for metrics, then @mention the bot in Slack
```

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

**sre_mcp_server.py** - Subprocess MCP server using JSON-RPC:
```python
# Tools available to Claude:
- query_metrics: Run PromQL queries against Prometheus
- list_metrics: Discover available metric names
- get_service_health: Quick health summary across all services
```

**sre_bot_slack.py** - Slack bot with Claude Agent SDK:
```python
from claude_agent_sdk import query, ClaudeAgentOptions

options = ClaudeAgentOptions(
    system_prompt=SYSTEM_PROMPT,
    mcp_servers={
        "sre": {
            "command": python_path,
            "args": [str(MCP_SERVER_PATH)],  # Subprocess MCP
        }
    },
    allowed_tools=["mcp__sre__query_metrics", "mcp__sre__get_service_health"],
    permission_mode="acceptEdits",
)

# Stream responses to Slack
async for message in query(prompt=incident_text, options=options):
    # Post each message to Slack thread as it arrives
```

## Demo Flow

### Timeline

| Time | System State | What Claude Will Find |
|------|--------------|----------------------|
| 0-60s | Healthy | Low error rates, normal latency, DB at ~45% |
| 60s+ | Incident | High error rates, elevated latency, DB at 95%+ |

### Example Investigation

Mention the bot in Slack:
```
@SRE Bot API error rates are spiking, users seeing 500 errors
```

Claude will:
1. Call `get_service_health` to get an overview
2. Call `query_metrics` for error rates to quantify the problem
3. Call `query_metrics` for latency to see correlation
4. Call `query_metrics` for DB connections to find root cause
5. Provide investigation findings, root cause analysis, and recommended actions
6. Offer to take remediation actions (restart pods, adjust connection pools, etc.)

## Project Structure

```
sre-bot-demo/
├── config/
│   ├── docker-compose.yml      # Prometheus + Grafana setup
│   ├── grafana-datasources.yml # Grafana datasource config
│   └── prometheus.yml          # Prometheus scrape config
├── scripts/
│   └── metric_logging.py       # Simulated metrics endpoint
├── outputs/                    # Investigation reports
├── .env                        # API keys (create this)
├── CLAUDE.md                   # Service topology and runbooks
├── README.md                   # This file
├── requirements.txt            # Python dependencies
├── quick-start.txt             # Quick reference setup guide
├── sre_bot_slack.py            # Main Slack bot
└── sre_mcp_server.py           # MCP server (subprocess)
```

## Slack Bot Features

- **Thread-based**: All investigation output goes to the thread where the bot was mentioned
- **Streaming**: Results appear in real-time as Claude investigates
- **Slack formatting**: Converts Markdown to Slack mrkdwn format
- **Tool visibility**: Shows which tools are being used during investigation
- **Remediation offers**: Claude offers to take specific actions to fix issues

## URLs

- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000 (admin/demo)
- **Metrics**: http://localhost:8000/metrics

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

## Customization

### Change the incident timing

In `scripts/metric_logging.py`, modify:
```python
incident_active = elapsed > 60  # Change 60 to desired seconds
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
