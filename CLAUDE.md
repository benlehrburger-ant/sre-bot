# SRE Bot Context

## Service Topology

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Clients   │────▶│  api-server │────▶│  postgres   │
└─────────────┘     └──────┬──────┘     └─────────────┘
                          │                    ▲
                          │                    │
                          ▼                    │
                   ┌─────────────┐             │
                   │ payment-svc │─────────────┘
                   └─────────────┘
                          │
                          ▼
                   ┌─────────────┐
                   │  auth-svc   │
                   └─────────────┘
```

### Services

| Service | Purpose | Dependencies | Connection Pool |
|---------|---------|--------------|-----------------|
| api-server | Main API gateway | postgres, auth-svc | 100 DB connections |
| payment-svc | Payment processing | postgres, auth-svc | 50 DB connections |
| auth-svc | Authentication | postgres | 25 DB connections |
| postgres | Primary database | - | max_connections=100 |

## Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Error rate (5xx) | > 1% | > 5% |
| P99 latency | > 500ms | > 2000ms |
| DB connections | > 70% | > 90% |
| CPU usage | > 70% | > 90% |
| Memory usage | > 80% | > 95% |

## Common Issues & Runbooks

### Database Connection Exhaustion

**Symptoms:**
- api-server in CrashLoopBackOff or high error rate
- "Connection refused" or "too many connections" in logs
- db_connections_active near max (100)

**Investigation:**
1. Check `db_connections_active` - is it > 90?
2. Check `db_connections_waiting` - are connections queuing?
3. Check which service is holding connections

**Remediation:**
1. Identify the service with connection leak
2. Restart affected service pods (temporary fix)
3. Scale down affected service to release connections
4. Long-term: fix connection pool configuration or code

### High Latency Cascade

**Symptoms:**
- P99 latency > 1000ms on api-server
- Downstream services (payment-svc) also slow
- Error rate increasing as timeouts occur

**Investigation:**
1. Check `http_request_duration_milliseconds{quantile="0.99"}`
2. Compare latency across services - where does it start?
3. Check database query times
4. Check for resource constraints (CPU, memory)

**Remediation:**
1. If DB-related: check slow queries, connection pool
2. If CPU-bound: scale horizontally
3. If memory-bound: check for leaks, increase limits

### Elevated Error Rates

**Symptoms:**
- `http_requests_total{status="500"}` increasing
- Alerts from monitoring
- User complaints

**Investigation:**
1. Which service has errors? Check `rate(http_requests_total{status="500"}[1m]) by (service)`
2. Is it correlated with latency? Check P99
3. Is it correlated with resource exhaustion? Check DB connections, CPU
4. Check logs for specific error messages

**Remediation:**
- Depends on root cause identified above

## PromQL Quick Reference

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

# Services with high CPU
container_cpu_usage_ratio > 0.8

# Services with high memory
container_memory_usage_ratio > 0.8
```

## Escalation Paths

| Service | Primary Oncall | Escalation |
|---------|----------------|------------|
| api-server | Platform team | #platform-oncall |
| payment-svc | Payments team | #payments-oncall |
| auth-svc | Identity team | #identity-oncall |
| postgres | Database team | #dba-oncall |
