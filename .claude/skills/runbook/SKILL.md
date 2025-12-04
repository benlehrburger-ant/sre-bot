---
name: runbook
description: Execute documented runbooks for common SRE incidents. Use when investigating database connection exhaustion, high latency cascades, or elevated error rates. Provides structured investigation steps and remediation procedures.
---

# SRE Runbook Skill

Execute documented runbooks for known incident types during SRE investigations.

## When to Use This Skill

Trigger this skill when you identify one of these patterns:

### Database Connection Exhaustion
- `db_connections_active` > 90 (approaching max of 100)
- "too many connections" or "connection refused" in logs
- Services in CrashLoopBackOff due to DB issues

### High Latency Cascade
- P99 latency > 1000ms on api-server
- Latency spreading to downstream services (payment-svc, auth-svc)
- Timeouts causing error rate increases

### Elevated Error Rates
- 5xx error rate > 5% on any service
- Sudden spike in `http_requests_total{status="500"}`
- User-reported errors without clear cause

## How to Execute Runbooks

Use the `mcp__sre__execute_runbook` tool with these parameters:

### Available Runbooks
- `database_connection_exhaustion`
- `high_latency_cascade`
- `elevated_error_rates`

### Phases
- `investigate` - Get diagnostic steps and queries to confirm the issue
- `remediate` - Get specific fix procedures and commands

## Workflow

1. Use investigation tools to identify the incident type
2. Call `execute_runbook` with `phase="investigate"` to get diagnostic steps
3. Follow the investigation steps, running the suggested PromQL queries
4. Once symptoms are confirmed, call `execute_runbook` with `phase="remediate"`
5. Present the remediation options to the user before taking action

## Examples

### Example 1: DB Connection Issue
```
You notice db_connections_active is 97/100

1. execute_runbook(runbook="database_connection_exhaustion", phase="investigate")
2. Run the suggested queries to confirm
3. execute_runbook(runbook="database_connection_exhaustion", phase="remediate")
4. Offer: "I can restart api-server pods to release connections. Reply yes to proceed."
```

### Example 2: Latency Spike
```
You see P99 latency at 2500ms on api-server

1. execute_runbook(runbook="high_latency_cascade", phase="investigate")
2. Check if latency is DB-related, CPU-bound, or memory-bound
3. execute_runbook(runbook="high_latency_cascade", phase="remediate")
4. Offer the appropriate fix based on root cause
```

### Example 3: Error Rate Spike
```
Error rate jumps to 15% on api-server

1. execute_runbook(runbook="elevated_error_rates", phase="investigate")
2. Determine if caused by DB, latency, or recent deployment
3. Follow the decision tree in remediate phase
4. May chain to another runbook if root cause identified
```

## Escalation Paths

Each runbook includes escalation information:
- **Database issues**: #dba-oncall
- **Platform/API issues**: #platform-oncall
- **Payment issues**: #payments-oncall
- **Auth issues**: #identity-oncall
