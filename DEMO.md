# SRE Bot Demo Guide

A step-by-step guide to running the SRE incident response bot demo.

---

## Prerequisites

- Python 3.8+
- Docker & Docker Compose (install OrbStack via kandji)
- Node.js / npm
- ngrok (for PagerDuty webhooks): `brew install ngrok`
- **PagerDuty Developer Account**: https://developer.pagerduty.com/
- **Atlassian Cloud Account** (free): https://www.atlassian.com/software/confluence/free

---

## 1. Setup

### Unzip and enter the project

```bash
unzip sre-bot-demo.zip
cd sre-bot-demo
```

### Install dependencies

```bash
npm install -g @anthropic-ai/claude-code
pip install -r requirements.txt
```

### Configure environment

Create a `.env` file in the project root:

```bash
# Required: Anthropic API key
ANTHROPIC_API_KEY=your-anthropic-key

# Slack integration
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
SLACK_INCIDENT_CHANNEL=#incident-triaging

# Webhook server port
WEBHOOK_PORT=3000

# PagerDuty integration
PAGERDUTY_API_KEY=your-pagerduty-api-key
PAGERDUTY_SERVICE_ID=your-service-id
PAGERDUTY_FROM_EMAIL=your-email@company.com

# Confluence integration
CONFLUENCE_BASE_URL=https://your-domain.atlassian.net/wiki
CONFLUENCE_API_TOKEN=your-atlassian-api-token
CONFLUENCE_USER_EMAIL=your-email@company.com
CONFLUENCE_SPACE_KEY=SRE
CONFLUENCE_PARENT_PAGE_ID=
```

### Join the Slack workspace

1. Join the **anthro-demo** Slack workspace: [Invite Link](https://join.slack.com/t/anthrodemo/shared_invite/zt-3nil7fvua-fUJ~amDD9FSj2ccKUhVT0w)
2. If the link is expired, contact benlehrburger@anthropic.com to be added manually

---

## 2. Configure PagerDuty

### Get API credentials

1. Go to https://your-subdomain.pagerduty.com/api_keys
2. Click **Create New API Key**
3. Copy the key to `PAGERDUTY_API_KEY` in `.env`

### Get Service ID

1. Go to **Services** → select your service
2. The service ID is in the URL: `https://your-subdomain.pagerduty.com/services/PXXXXXX`
3. Copy `PXXXXXX` to `PAGERDUTY_SERVICE_ID` in `.env`

### Configure webhook (for Slack notifications)

1. Start the bot: `python sre_bot_slack.py`
2. In a separate terminal, start ngrok: `ngrok http 3000`
3. Copy the ngrok URL (e.g., `https://abc123.ngrok-free.dev`)
4. In PagerDuty, go to **Integrations** → **Generic Webhooks (v3)**
5. Click **+ New Webhook** and configure:
   - **Webhook URL**: `https://abc123.ngrok-free.dev/webhooks/pagerduty`
   - **Scope**: Service → select your service
   - **Events**: Select `incident.triggered`
6. Click **Add Webhook**

---

## 3. Configure Confluence

### Get API token

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click **Create API token**
3. Copy the token to `CONFLUENCE_API_TOKEN` in `.env`

### Create SRE space

1. In Confluence, click **Spaces** → **Create space**
2. Name it "SRE" with key `SRE`
3. This is where post-mortems will be created

---

## 4. Start the Infrastructure

Open **4 separate terminal windows**:

| Terminal | Command | Purpose |
|----------|---------|---------|
| 1 | `python scripts/metric_logging.py` | Metrics server exposing Prometheus metrics |
| 2 | `docker-compose -f config/docker-compose.yml up` | Prometheus + Grafana + api-server |
| 3 | `python sre_bot_slack.py` | Slack bot + webhook server |
| 4 | `ngrok http 3000` | Expose webhook for PagerDuty |

---

## 5. Trigger the Incident

### Step 1: Reduce DB Pool Size

Edit `config/api-server.env` and change the pool size from 20 to 1:

```bash
# Before
DB_POOL_SIZE=20

# After
DB_POOL_SIZE=1
```

### Step 2: Redeploy the Container

```bash
docker-compose -f config/docker-compose.yml up --build api-server
```

This simulates a bad configuration change that causes connection exhaustion.

### Step 3: Verify in Prometheus

1. Open [http://localhost:9090](http://localhost:9090)
2. Click the **Graph** tab
3. Run this PromQL query:
   ```
   rate(http_requests_total{status="500"}[1m])
   ```
4. You should see elevated 500 errors from the API server

---

## 6. Demo Flow

### Step 1: Report the Incident in Slack

Go to the `#incident-triaging` channel and message the bot:

```
@SRE Bot 500 errors spiking, create an incident
```

The bot will create a PagerDuty incident and offer to investigate.

### Step 2: Investigate the Incident

When the bot asks if you want it to investigate, reply:

```
yes
```

The bot will:
1. Query Prometheus metrics
2. Check service health and logs
3. Analyze the data
4. Identify the root cause (DB pool size misconfiguration)
5. Offer to fix the issue

Example output:
```
*Root Cause*
Database connection exhaustion in api-server. The DB_POOL_SIZE is set to 1,
which is insufficient for the current load.

I can fix this by updating the DB_POOL_SIZE to 20 in config/api-server.env
and redeploying the container. Would you like me to proceed?
```

### Step 3: Apply the Fix

When the bot offers to fix the issue, reply:

```
yes
```

The bot will:
1. Update `config/api-server.env` to restore `DB_POOL_SIZE=20`
2. Trigger a container redeploy
3. Monitor error rates to verify the fix is working

You can verify the change by checking the file:
```bash
cat config/api-server.env | grep DB_POOL_SIZE
# Should show: DB_POOL_SIZE=20
```

### Step 4: Verify Remediation

The bot will monitor Prometheus and confirm when error rates return to normal:

```
Error rates are falling. The fix appears to be working.

Current 500 error rate: 0.02/s (down from 15.3/s)

Would you like me to create a post-mortem and close out the incident?
```

### Step 5: Create Post-Mortem & Close Incident

Reply to confirm:

```
yes
```

The bot will:
1. Create a Confluence post-mortem page documenting the incident
2. Resolve the PagerDuty incident
3. Share the post-mortem link

```
✅ Incident resolved and post-mortem created:
https://your-domain.atlassian.net/wiki/spaces/SRE/pages/12345/...
```

### Summary

| Step | Action | Result |
|------|--------|--------|
| 1 | `@SRE Bot 500 errors spiking, create an incident` | PagerDuty incident created, bot offers to investigate |
| 2 | `yes` (investigate) | Bot identifies root cause (DB pool size = 1) |
| 3 | `yes` (fix) | Bot restores DB_POOL_SIZE=20, redeploys container |
| 4 | (automatic) | Bot monitors and confirms error rates falling |
| 5 | `yes` (post-mortem) | Confluence page created, incident closed |

---

## Code Walkthrough

Key files and lines to reference when explaining the implementation:

| File | Line | Description |
|------|------|-------------|
| `sre_bot_slack.py` | 161 | Agent system prompt |
| `sre_bot_slack.py` | 215 | Initializing agent with Agent SDK |
| `sre_bot_slack.py` | 225 | Tools available to agent |
| `sre_bot_slack.py` | 107 | PagerDuty webhook handler |
| `sre_bot_slack.py` | 424 | Webhook server setup |
| `sre_mcp_server.py` | 207 | PagerDuty tool definitions |
| `sre_mcp_server.py` | 305 | Confluence tool definitions |
| `sre_mcp_server.py` | 1361 | PagerDuty handlers |
| `sre_mcp_server.py` | 1593 | Confluence handlers |
| `CLAUDE.md` | 61 | MCP tools documentation |

---

## Testing Individual Integrations

### Test PagerDuty

```bash
# List incidents
python -c "
import asyncio
from sre_mcp_server import pagerduty_list_incidents
asyncio.run(pagerduty_list_incidents()).get('content')[0].get('text')
"

# Create test incident
curl -X POST https://api.pagerduty.com/incidents \
  -H "Authorization: Token token=YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -H "From: your-email@company.com" \
  -d '{
    "incident": {
      "type": "incident",
      "title": "[TEST] SRE Bot Demo",
      "service": {"id": "YOUR_SERVICE_ID", "type": "service_reference"},
      "urgency": "low"
    }
  }'
```

### Test Confluence

```bash
python -c "
import asyncio
from sre_mcp_server import confluence_create_postmortem

result = asyncio.run(confluence_create_postmortem(
    title='Post-Mortem: Test Incident',
    incident_summary='Test post-mortem from SRE bot.',
    root_cause='Testing Confluence integration.'
))
print(result['content'][0]['text'])
"
```

### Test webhook endpoint

```bash
curl -X POST http://localhost:3000/webhooks/pagerduty \
  -H "Content-Type: application/json" \
  -d '{
    "event": {
      "event_type": "incident.triggered",
      "data": {
        "id": "TEST123",
        "title": "Test Incident",
        "service": {"summary": "api-server"},
        "urgency": "high",
        "html_url": "https://pagerduty.com/incidents/TEST123"
      }
    }
  }'
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Port 3000 in use | `lsof -i :3000` then `kill <PID>`, or change `WEBHOOK_PORT` |
| Webhook not received | Check ngrok inspector at http://127.0.0.1:4040 |
| Slack message not posting | Verify channel name/ID, check bot is in channel |
| Confluence 401 error | Regenerate API token, verify email matches |
| PagerDuty 401 error | Check API key is valid, verify From email |
