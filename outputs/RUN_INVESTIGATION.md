# How to Run the API Error Spike Investigation

## Quick Start

### Step 1: Start the Demo Environment

Open 3 terminal windows:

**Terminal 1 - Start Metrics Server:**
```bash
cd /Users/benlehrburger/Desktop/sre-bot-demo
python metric_logging.py
```

**Terminal 2 - Start Prometheus & Grafana:**
```bash
cd /Users/benlehrburger/Desktop/sre-bot-demo
docker-compose up
```

**Terminal 3 - Wait 60+ seconds, then run investigation:**
```bash
cd /Users/benlehrburger/Desktop/sre-bot-demo

# Option 1: Full systematic investigation
python systematic_investigation.py

# Option 2: Quick check
python quick_check.py

# Option 3: Use the Agent SDK
python sre_bot.py "API error rates are spiking, users seeing 500 errors"
```

## What Each Script Does

### systematic_investigation.py (NEW - Comprehensive)
- Follows exact MCP tool calling sequence you requested
- Step 1: Calls `mcp__sre__get_service_health`
- Step 2: Queries error rates with `rate(http_requests_total{status=~"5.."}[1m])`
- Step 3: Checks latency with `histogram_quantile(0.99, ...)`
- Step 4: Checks database connections
- Step 5: Checks CPU and memory usage
- Generates detailed summary with root cause hypothesis

### quick_check.py (Existing - Fast)
- Quick overview of key metrics
- Error rates, latency, DB connections
- No detailed analysis

### sre_bot.py (Existing - Agent SDK)
- Uses Claude Agent SDK
- Claude autonomously decides investigation steps
- Most realistic incident response simulation

## Expected Output

### Before Incident (0-60 seconds)

```
============================================================
STEP 1: Getting Service Health Overview
============================================================

Service Status:
  [UP] api-server
  [UP] web-service

Error Rates (500 errors):
  [OK] api-server: 0.10 errors/sec
  [OK] web-service: 0.05 errors/sec

Latency (P99):
  [OK] api-server: 150ms
  [OK] web-service: 200ms

Database Connections:
  [OK] Active: 45/100
```

### During Incident (60+ seconds)

```
============================================================
STEP 1: Getting Service Health Overview
============================================================

Service Status:
  [UP] api-server
  [UP] web-service

Error Rates (500 errors):
  [CRITICAL] api-server: 12.50 errors/sec
  [CRITICAL] web-service: 8.30 errors/sec

Latency (P99):
  [HIGH] api-server: 2800ms
  [HIGH] web-service: 3100ms

Database Connections:
  [CRITICAL] Active: 98/100

======================================================================
ROOT CAUSE HYPOTHESIS
======================================================================

PRIMARY HYPOTHESIS: Database Connection Pool Exhaustion

Evidence:
- Database connection pool at 98% capacity
- API services showing elevated error rates
- Requests timing out while waiting for database connections
```

## Troubleshooting

### "Cannot connect to Prometheus"
```bash
# Check if Docker is running
docker ps

# If not, start it
docker-compose up -d

# Verify Prometheus is accessible
curl http://localhost:9090/-/healthy
```

### "No data returned"
```bash
# Make sure metric_logging.py is running
ps aux | grep metric_logging

# If not running, start it
python metric_logging.py

# Wait 10-15 seconds for Prometheus to scrape metrics
```

### "ModuleNotFoundError"
```bash
# Install dependencies
pip install -r requirements.txt

# Or install individually
pip install httpx prometheus-client
```

## Verify Setup

Before running investigation, verify everything is working:

```bash
# Test Prometheus connectivity
python test_tools.py

# Expected output:
# ✅ Prometheus is running
# ✅ Found 2 scrape targets
# ✅ Error rate data available
# ✅ DB connections: 45/100
# ✅ Latency data available
```

## Timeline

The demo simulates an incident that evolves over time:

| Time | State | What You'll See |
|------|-------|-----------------|
| 0-60s | Healthy | Low errors (~0.1/sec), Normal latency (~150ms), DB at 45% |
| 60s+ | Incident | High errors (~12/sec), High latency (~2800ms), DB at 98% |

**Important:** Wait at least 60 seconds after starting metric_logging.py before running the investigation to see the incident in progress.

## Using MCP Tools Directly (If Configured)

If you have MCP tools configured in Claude Desktop:

```
You: Investigate an API error spike

Claude will call:
1. mcp__sre__get_service_health
2. mcp__sre__query_metrics with various PromQL queries
3. Analyze results and provide recommendations
```

## Next Steps After Investigation

1. **Review the findings** in the output
2. **Check the detailed report** in `INVESTIGATION_REPORT.md`
3. **Apply recommended fixes** (in a real environment)
4. **Create a postmortem** using the template in the report

## URLs

Once running, you can access:

- **Prometheus UI**: http://localhost:9090
- **Grafana**: http://localhost:3000 (admin/demo)
- **Metrics Endpoint**: http://localhost:8000/metrics

## Manual Investigation (Using Prometheus UI)

You can also investigate manually using the Prometheus web UI:

1. Open http://localhost:9090
2. Go to Graph tab
3. Try these queries:

```promql
# Error rate
sum(rate(http_requests_total{status="500"}[1m])) by (service)

# Latency
http_request_duration_milliseconds{quantile="0.99"}

# DB connections
db_connections_active

# CPU usage
container_cpu_usage_ratio
```

## Clean Up

When done:

```bash
# Stop Docker containers
docker-compose down

# Stop metric_logging.py
Ctrl+C in Terminal 1
```

## File Overview

| File | Purpose |
|------|---------|
| `systematic_investigation.py` | **NEW** - Comprehensive investigation following your exact specifications |
| `INVESTIGATION_REPORT.md` | **NEW** - Detailed report of findings and recommendations |
| `quick_check.py` | Existing - Quick health check |
| `sre_bot.py` | Existing - Agent SDK version |
| `test_tools.py` | Existing - Verify setup |
| `metric_logging.py` | Existing - Generates fake metrics |

## Key Differences Between Scripts

### systematic_investigation.py
- **Purpose**: Demonstrate systematic SRE investigation process
- **Approach**: Step-by-step with detailed explanations
- **Output**: Comprehensive with hypothesis and recommendations
- **Use Case**: Training, documentation, demonstrations

### quick_check.py
- **Purpose**: Fast health check
- **Approach**: Query key metrics only
- **Output**: Minimal, just the numbers
- **Use Case**: Quick status check during incident

### sre_bot.py (Agent SDK)
- **Purpose**: Autonomous incident investigation by Claude
- **Approach**: Claude decides what to check and in what order
- **Output**: Natural language investigation narrative
- **Use Case**: Production incident response, agent demonstrations
