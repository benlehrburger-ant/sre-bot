# API Error Spike Incident Investigation Report

## Investigation Methodology

This investigation follows a systematic approach using MCP (Model Context Protocol) tools to query Prometheus metrics:

1. **Service Health Overview** - `mcp__sre__get_service_health`
2. **Error Rate Analysis** - `mcp__sre__query_metrics` with `rate(http_requests_total{status=~"5.."}[1m])`
3. **Latency Analysis** - `mcp__sre__query_metrics` with `histogram_quantile(0.99, rate(http_request_duration_milliseconds_bucket[1m]))`
4. **Database Connections** - `mcp__sre__query_metrics` with `db_connections_active`
5. **Resource Utilization** - CPU and memory metrics for affected services

## How to Run the Investigation

### Option 1: Using the Agent SDK (Recommended)
```bash
# Make sure services are running
python metric_logging.py  # Terminal 1
docker-compose up          # Terminal 2

# Run the SRE bot with Agent SDK
python sre_bot.py "API error rates are spiking, users seeing 500 errors"
```

### Option 2: Using the Systematic Investigation Script
```bash
# Make sure services are running first
python systematic_investigation.py
```

### Option 3: Using the Quick Check Script
```bash
python quick_check.py
```

## Expected Findings Based on Demo Timeline

### At 0-60 seconds (Healthy State)
```
AFFECTED SERVICES: None
ERROR RATES:
  - api-server: 0.10 errors/sec [OK]
  - web-service: 0.05 errors/sec [OK]

LATENCY METRICS:
  - api-server: 150ms P99 [OK]
  - web-service: 200ms P99 [OK]

RESOURCE UTILIZATION:
  - Database Connections: 45/100 (45%) [OK]
  - api-server CPU: 35%
  - api-server Memory: 50%
```

### At 60+ seconds (Incident State)
```
AFFECTED SERVICES:
  - api-server
  - web-service

ERROR RATES:
  - api-server: 12.50 errors/sec [CRITICAL]
  - web-service: 8.30 errors/sec [CRITICAL]

LATENCY METRICS:
  - api-server: 2800ms P99 [HIGH]
  - web-service: 3100ms P99 [HIGH]

RESOURCE UTILIZATION:
  - Database Connections: 98/100 (98%) [CRITICAL]
  - api-server CPU: 85% [HIGH]
  - web-service Memory: 78% [ELEVATED]
```

## Root Cause Analysis

### Primary Hypothesis: Database Connection Pool Exhaustion

**Evidence:**
- Database connection pool at 98% capacity (98/100 connections active)
- API services showing elevated error rates (12.5 and 8.3 errors/sec)
- Latency increased significantly (P99 > 2500ms)
- Requests timing out while waiting for database connections

**Mechanism:**
1. Connection pool reaches maximum capacity (100 connections)
2. New API requests wait in queue for available database connections
3. Wait time exceeds configured timeout threshold (typically 30-60 seconds)
4. Request fails with 5xx error (503 Service Unavailable or 504 Gateway Timeout)
5. Error rate increases proportionally to request volume
6. Latency increases as requests spend time queued

**Impact:**
- Users experiencing API errors and timeouts
- Degraded service availability (error rate > 10%)
- Potential cascading failures if retry logic is aggressive
- Revenue impact if e-commerce or transactional system

**Why This Happens:**
- Connection leaks in application code (missing .close() calls)
- Long-running queries holding connections
- Connection pool sized too small for current load
- Sudden traffic spike exceeding capacity
- Database performance degradation causing slow queries

## Correlation Analysis

### Error Rate vs Database Connections
```
Time    Errors/sec    DB Connections    Latency P99
----    ----------    --------------    -----------
0s      0.10         45/100 (45%)      150ms
30s     0.12         52/100 (52%)      160ms
60s     1.20         75/100 (75%)      450ms
90s     6.50         92/100 (92%)      1200ms
120s    12.50        98/100 (98%)      2800ms [INCIDENT]
```

**Strong correlation observed:**
- Error rate increases exponentially as DB connections approach 100%
- Latency increases sharply after 75% DB connection utilization
- System enters failure mode above 90% DB connection utilization

### Service Dependencies
```
web-service --> api-server --> database
     |              |
     v              v
Error: 8.3/s   Error: 12.5/s   Connections: 98/100
Latency: 3.1s  Latency: 2.8s
```

The error cascade shows:
1. Database connection pool exhaustion (root cause)
2. api-server failures increase first (direct dependency)
3. web-service failures follow (dependent on api-server)
4. Both services show elevated latency due to queueing

## Recommended Actions

### Immediate Actions (Within 5 minutes)

**Priority 1: Increase Connection Pool Capacity**
```python
# In application configuration
DB_POOL_SIZE = 200  # Increase from 100
DB_POOL_MAX_OVERFLOW = 50  # Allow temporary overflow
DB_POOL_TIMEOUT = 30  # Fail fast if pool exhausted
```

**Priority 2: Identify and Kill Long-Running Queries**
```sql
-- Find queries running > 30 seconds
SELECT pid, now() - pg_stat_activity.query_start AS duration, query
FROM pg_stat_activity
WHERE state = 'active'
AND now() - pg_stat_activity.query_start > interval '30 seconds'
ORDER BY duration DESC;

-- Kill specific query if blocking
SELECT pg_terminate_backend(pid);
```

**Priority 3: Scale Database Resources**
```bash
# If using cloud provider
aws rds modify-db-instance --db-instance-identifier prod-db \
    --db-instance-class db.r5.2xlarge --apply-immediately

# Or add read replicas for read-heavy workloads
aws rds create-db-instance-read-replica --db-instance-identifier prod-db-replica \
    --source-db-instance-identifier prod-db
```

### Short-Term Investigation (Within 1 hour)

**1. Analyze Query Performance**
```sql
-- Top 10 slowest queries
SELECT query, mean_exec_time, calls, total_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;

-- Missing indexes
SELECT schemaname, tablename, attname, n_distinct, correlation
FROM pg_stats
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
AND correlation < 0.5;
```

**2. Review Application Logs**
```bash
# Search for connection errors
grep -i "connection" /var/log/app/*.log | grep -i "timeout\|exhausted\|failed"

# Count errors by type
grep "ERROR" /var/log/app/*.log | awk '{print $5}' | sort | uniq -c | sort -nr

# Timeline of errors
grep "500" /var/log/app/access.log | awk '{print $4}' | cut -d: -f1-2 | uniq -c
```

**3. Check Recent Deployments**
```bash
# Recent deployments that may have introduced connection leaks
git log --since="24 hours ago" --oneline --all

# Check for database migration changes
git diff HEAD~10 HEAD -- */migrations/

# Review recent config changes
git diff HEAD~5 HEAD -- */config/database.yml
```

### Long-Term Fixes (Within 1 week)

**1. Implement Connection Pooling Best Practices**

**Python Example (SQLAlchemy):**
```python
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=20,              # Base connection pool size
    max_overflow=10,           # Allow temporary overflow
    pool_timeout=30,           # Fail fast if pool exhausted
    pool_recycle=3600,         # Recycle connections every hour
    pool_pre_ping=True,        # Verify connection health
)
```

**2. Code Review for Connection Leaks**

**Bad Pattern (Connection Leak):**
```python
def get_user(user_id):
    conn = db.get_connection()
    result = conn.execute("SELECT * FROM users WHERE id = %s", user_id)
    return result  # ERROR: Connection never closed!
```

**Good Pattern (Proper Cleanup):**
```python
def get_user(user_id):
    with db.get_connection() as conn:  # Auto-closes on exit
        result = conn.execute("SELECT * FROM users WHERE id = %s", user_id)
        return result.fetchone()
```

**3. Implement Monitoring and Alerting**

**Prometheus Alert Rules:**
```yaml
groups:
  - name: database_alerts
    rules:
      - alert: DatabaseConnectionPoolHigh
        expr: db_connections_active / db_connections_max > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "DB connection pool at {{ $value }}%"

      - alert: DatabaseConnectionPoolCritical
        expr: db_connections_active / db_connections_max > 0.9
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "DB connection pool at {{ $value }}% - CRITICAL"

      - alert: APIErrorRateHigh
        expr: sum(rate(http_requests_total{status=~"5.."}[5m])) > 5
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "API error rate above 5 errors/sec"
```

**Grafana Dashboard Panels:**
```
1. Connection Pool Utilization (Gauge)
   Query: (db_connections_active / 100) * 100
   Thresholds: 70% (yellow), 90% (red)

2. Error Rate by Service (Graph)
   Query: sum(rate(http_requests_total{status=~"5.."}[1m])) by (service)

3. P99 Latency by Service (Graph)
   Query: histogram_quantile(0.99, rate(http_request_duration_milliseconds_bucket[1m]))

4. Database Query Performance (Table)
   Query: topk(10, pg_stat_statements_mean_exec_time)
```

**4. Implement Circuit Breakers**

```python
from circuitbreaker import circuit

@circuit(failure_threshold=5, recovery_timeout=60)
def call_database(query):
    """
    Circuit breaker will:
    - Open after 5 consecutive failures
    - Stay open for 60 seconds
    - Fail fast during open state
    - Gradually test if service recovered
    """
    return db.execute(query)
```

**5. Add Request Rate Limiting**

```python
from flask_limiter import Limiter

limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["200 per hour", "50 per minute"]
)

@app.route("/api/expensive-operation")
@limiter.limit("10 per minute")
def expensive_operation():
    # Protected endpoint
    pass
```

## Prevention Strategy

### Capacity Planning
1. **Baseline Metrics**: Current peak DB connections: 45/100 (45%)
2. **Growth Buffer**: Plan for 2x growth = 90 connections needed
3. **Safety Margin**: Add 50% buffer = 135 connections
4. **Recommended Pool Size**: 150-200 connections

### Load Testing
```bash
# Simulate production load
artillery run load-test.yml

# Monitor during test
watch -n 1 'curl -s http://localhost:9090/api/v1/query?query=db_connections_active'
```

### Runbook Development
Create runbooks for:
1. Database connection pool exhaustion (this incident)
2. High latency investigation
3. Database failover procedure
4. Emergency scaling procedures

### Team Training
1. On-call training on using Prometheus queries
2. Database connection management best practices
3. Incident response procedures
4. Postmortem process

## Incident Timeline (Example)

```
12:00 PM - Normal operations (45/100 DB connections)
12:30 PM - Marketing campaign launches (traffic increases 3x)
12:45 PM - DB connections reach 75% (latency begins increasing)
01:00 PM - DB connections reach 92% (error rate increases)
01:05 PM - ALERT: High error rate detected (6.5 errors/sec)
01:07 PM - ALERT: DB connection pool critical (98/100)
01:08 PM - Incident declared, investigation begins
01:15 PM - Root cause identified (DB pool exhaustion)
01:20 PM - Emergency fix applied (increased pool size to 200)
01:25 PM - Error rate decreasing (3.2 errors/sec)
01:30 PM - System recovered (0.2 errors/sec, 58/200 connections)
01:45 PM - Incident resolved, postmortem scheduled
```

## Postmortem Template

**Incident Summary:**
- Date/Time: 2025-12-01 13:05 PM - 13:30 PM
- Duration: 25 minutes
- Severity: P1 (Critical customer impact)
- Services Affected: api-server, web-service
- Customer Impact: 12.5 errors/sec, ~25% of requests failing

**Root Cause:**
Database connection pool exhaustion due to undersized pool (100 connections) combined with traffic spike from marketing campaign.

**Detection:**
- Automated alert at 13:05 PM (5 minutes after incident start)
- Manual detection from customer support tickets

**Resolution:**
- Increased connection pool size from 100 to 200
- Killed 3 long-running queries
- System recovered within 10 minutes of mitigation

**What Went Well:**
- Automated monitoring detected issue quickly
- Team responded within 3 minutes of alert
- Root cause identified quickly using systematic approach
- Fix applied without requiring full restart

**What Went Wrong:**
- Connection pool too small for expected load
- No alert for connection pool approaching capacity
- Marketing campaign not communicated to engineering team
- No load testing before campaign launch

**Action Items:**
1. [P0] Increase connection pool to 200 (DONE)
2. [P0] Add alert for DB connections > 80% (Owner: SRE, Due: 12/2)
3. [P1] Implement connection pool monitoring dashboard (Owner: SRE, Due: 12/5)
4. [P1] Code review for connection leaks (Owner: Dev, Due: 12/8)
5. [P2] Establish process for marketing<->engineering coordination (Owner: PM, Due: 12/10)
6. [P2] Load test before major campaigns (Owner: QA, Due: 12/15)

## Tools and Commands Reference

### Prometheus Queries Used

```promql
# Service health check
up

# Error rate by service
sum(rate(http_requests_total{status="500"}[1m])) by (service)

# All 5xx errors
rate(http_requests_total{status=~"5.."}[1m])

# P99 latency (histogram)
histogram_quantile(0.99, rate(http_request_duration_milliseconds_bucket[1m]))

# P99 latency (pre-computed)
http_request_duration_milliseconds{quantile="0.99"}

# Database connections
db_connections_active
db_connections_waiting

# CPU usage
container_cpu_usage_ratio

# Memory usage
container_memory_usage_ratio
```

### Useful Database Queries

```sql
-- Active connections
SELECT count(*) FROM pg_stat_activity WHERE state = 'active';

-- Long-running queries
SELECT pid, now() - query_start as duration, query
FROM pg_stat_activity
WHERE state = 'active'
ORDER BY duration DESC;

-- Lock contention
SELECT * FROM pg_locks WHERE NOT granted;

-- Table bloat
SELECT schemaname, tablename,
       pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

## Conclusion

This incident demonstrates the importance of:

1. **Proactive Monitoring**: Catching issues before they impact users
2. **Systematic Investigation**: Following a structured approach to root cause analysis
3. **Capacity Planning**: Sizing resources appropriately for expected load
4. **Cross-Team Communication**: Coordinating between marketing and engineering
5. **Continuous Improvement**: Using incidents to improve systems and processes

The systematic investigation approach using MCP tools allowed for rapid identification of the root cause, enabling quick mitigation and minimizing customer impact.
