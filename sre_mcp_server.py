#!/usr/bin/env python3
"""
SRE MCP Server - Subprocess-based MCP server for incident investigation.

This server runs as a separate process and communicates via stdio using
the MCP JSON-RPC protocol. This avoids the SDK MCP race condition bug.

Usage:
    python sre_mcp_server.py

The server implements:
- query_metrics: Run PromQL queries against Prometheus
- list_metrics: List available metric names
- get_service_health: Get a comprehensive health summary
"""

import json
import sys
import asyncio
import httpx
import random
import time
from typing import Any

PROMETHEUS_URL = "http://localhost:9090"

# Track when the server started (for incident simulation timing)
START_TIME = time.time()

# Tool definitions for MCP
TOOLS = [
    {
        "name": "query_metrics",
        "description": """Query Prometheus metrics using PromQL.

Use this to investigate incidents by checking error rates, latency, and resource usage.

Common investigation queries:
- Error rate by service: rate(http_requests_total{status="500"}[1m])
- Error ratio: sum(rate(http_requests_total{status="500"}[1m])) by (service) / sum(rate(http_requests_total[1m])) by (service)
- DB connections: db_connections_active or db_connections_waiting
- Latency P99: http_request_duration_milliseconds{quantile="0.99"}
- CPU usage: container_cpu_usage_ratio
- Memory usage: container_memory_usage_ratio

Investigation workflow:
1. Start with error rates to identify affected services
2. Check latency to see if it's a slowdown vs failures
3. Look at db_connections if you see timeout-related errors
4. Check CPU/memory if services are resource-constrained""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "promql": {
                    "type": "string",
                    "description": "The PromQL query to execute"
                }
            },
            "required": ["promql"]
        }
    },
    {
        "name": "list_metrics",
        "description": """List all available metric names in Prometheus.

Use this first if you're unsure what metrics exist.
Returns metric names grouped by category for easier discovery.""",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_service_health",
        "description": """Quick health check across all services.

Returns a summary of:
- Error rates per service
- Current latency (P99)
- Database connection status
- Service up/down status

Use this as a starting point for incident investigation to quickly
identify which services are affected.""",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_logs",
        "description": """Fetch recent application logs from services.

Returns the most recent log entries for a specified service.
Useful for investigating errors, timeouts, and application behavior.

Available services: api-server, payment-svc, auth-svc, postgres""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "The service to fetch logs from (api-server, payment-svc, auth-svc, postgres)"
                },
                "level": {
                    "type": "string",
                    "description": "Filter by log level: all, error, warn, info (default: all)",
                    "enum": ["all", "error", "warn", "info"]
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of log lines to return (default: 20, max: 100)"
                }
            },
            "required": ["service"]
        }
    },
    {
        "name": "get_alerts",
        "description": """Get currently firing and pending alerts from AlertManager.

Returns all active alerts with their severity, duration, and details.
Use this to understand what automated monitoring has already detected.""",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_recent_deployments",
        "description": """List recent deployments across all services.

Returns deployment history with timestamps, commit SHAs, and authors.
Useful for correlating incidents with recent changes.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Filter to a specific service (optional)"
                }
            },
            "required": []
        }
    },
    {
        "name": "execute_runbook",
        "description": """Execute a documented runbook for a known issue type.

Runbooks provide structured investigation and remediation procedures for common incidents.
Use this when you've identified a specific type of issue and want to follow the standard
operating procedure.

Available runbooks:
- database_connection_exhaustion: For DB pool exhaustion, "too many connections" errors
- high_latency_cascade: For P99 latency spikes cascading across services
- elevated_error_rates: For 5xx error rate increases

Each runbook has two phases:
- investigate: Returns diagnostic steps and queries to run
- remediate: Returns remediation actions (requires investigation first)

Always run the investigate phase first to confirm the issue before remediation.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "runbook": {
                    "type": "string",
                    "enum": ["database_connection_exhaustion", "high_latency_cascade", "elevated_error_rates"],
                    "description": "Which runbook to execute"
                },
                "phase": {
                    "type": "string",
                    "enum": ["investigate", "remediate"],
                    "description": "Phase to execute: 'investigate' for diagnosis, 'remediate' for fixes"
                }
            },
            "required": ["runbook", "phase"]
        }
    }
]


async def query_metrics(promql: str) -> dict[str, Any]:
    """Query Prometheus with a PromQL expression."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query",
                params={"query": promql},
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

        if data["status"] != "success":
            return {
                "content": [{
                    "type": "text",
                    "text": f"Query failed: {data.get('error', 'Unknown error')}\nQuery: {promql}"
                }],
                "isError": True
            }

        results = data["data"]["result"]

        if not results:
            return {
                "content": [{
                    "type": "text",
                    "text": f"No data returned for query: {promql}\nCheck if metric name is correct or try a broader time range."
                }]
            }

        # Format results for readability
        formatted_lines = [f"Query: {promql}", f"Results ({len(results)} series):", ""]

        for r in results:
            labels = r.get("metric", {})
            if "value" in r:
                timestamp, value = r["value"]
                label_str = ", ".join(f"{k}={v}" for k, v in labels.items() if k != "__name__")
                formatted_lines.append(f"  {label_str or 'value'}: {value}")
            elif "values" in r:
                label_str = ", ".join(f"{k}={v}" for k, v in labels.items() if k != "__name__")
                latest_value = r["values"][-1][1] if r["values"] else "N/A"
                formatted_lines.append(f"  {label_str or 'value'}: {latest_value} (latest)")

        return {
            "content": [{
                "type": "text",
                "text": "\n".join(formatted_lines)
            }]
        }

    except httpx.ConnectError:
        return {
            "content": [{
                "type": "text",
                "text": "Cannot connect to Prometheus at localhost:9090.\nMake sure to run: docker-compose up"
            }],
            "isError": True
        }
    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Error executing query: {str(e)}\nQuery: {promql}"
            }],
            "isError": True
        }


async def list_metrics() -> dict[str, Any]:
    """List available metrics in Prometheus."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{PROMETHEUS_URL}/api/v1/label/__name__/values",
                timeout=10.0
            )
            response.raise_for_status()
            data = response.json()

        metrics = data.get("data", [])

        # Group metrics by prefix for easier reading
        grouped = {
            "http": [m for m in metrics if m.startswith("http_")],
            "db": [m for m in metrics if m.startswith("db_")],
            "container": [m for m in metrics if m.startswith("container_")],
            "other": [
                m for m in metrics
                if not any(m.startswith(p) for p in ["http_", "db_", "container_", "go_", "promhttp_", "up"])
            ],
        }

        lines = [f"Available metrics ({len(metrics)} total):", ""]
        for category, metric_list in grouped.items():
            if metric_list:
                lines.append(f"{category.upper()}:")
                for m in metric_list:
                    lines.append(f"  - {m}")
                lines.append("")

        lines.append("Use query_metrics() with these metric names to get values.")

        return {
            "content": [{
                "type": "text",
                "text": "\n".join(lines)
            }]
        }

    except httpx.ConnectError:
        return {
            "content": [{
                "type": "text",
                "text": "Cannot connect to Prometheus. Is it running?"
            }],
            "isError": True
        }
    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Error listing metrics: {str(e)}"
            }],
            "isError": True
        }


async def get_service_health() -> dict[str, Any]:
    """Get a comprehensive health summary across all services."""
    health_lines = ["=== Service Health Summary ===", ""]
    issues = []

    async with httpx.AsyncClient() as client:
        # Check error rates
        try:
            response = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query",
                params={"query": 'sum(rate(http_requests_total{status="500"}[1m])) by (service)'},
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                if data["status"] == "success" and data["data"]["result"]:
                    health_lines.append("ERROR RATES (errors/sec):")
                    for r in data["data"]["result"]:
                        service = r["metric"].get("service", "unknown")
                        rate = float(r["value"][1])
                        status = "[CRITICAL]" if rate > 5 else "[WARNING]" if rate > 1 else "[OK]"
                        health_lines.append(f"  {status} {service}: {rate:.2f}/sec")
                        if rate > 5:
                            issues.append(f"High error rate on {service}: {rate:.1f}/sec")
                    health_lines.append("")
        except Exception:
            pass

        # Check latency
        try:
            response = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query",
                params={"query": 'http_request_duration_milliseconds{quantile="0.99"}'},
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                if data["status"] == "success" and data["data"]["result"]:
                    health_lines.append("LATENCY P99:")
                    for r in data["data"]["result"]:
                        service = r["metric"].get("service", "unknown")
                        latency = float(r["value"][1])
                        status = "[CRITICAL]" if latency > 1000 else "[WARNING]" if latency > 500 else "[OK]"
                        health_lines.append(f"  {status} {service}: {latency:.0f}ms")
                        if latency > 1000:
                            issues.append(f"High latency on {service}: {latency:.0f}ms")
                    health_lines.append("")
        except Exception:
            pass

        # Check DB connections
        try:
            response = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query",
                params={"query": "db_connections_active"},
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                if data["status"] == "success" and data["data"]["result"]:
                    active = float(data["data"]["result"][0]["value"][1])
                    status = "[CRITICAL]" if active > 90 else "[WARNING]" if active > 70 else "[OK]"
                    health_lines.append("DATABASE CONNECTIONS:")
                    health_lines.append(f"  {status}: {active:.0f}/100 active")
                    if active > 90:
                        issues.append(f"DB connection pool near exhaustion: {active:.0f}/100")
                    health_lines.append("")
        except Exception:
            pass

        # Check service up status
        try:
            response = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query",
                params={"query": "up"},
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                if data["status"] == "success" and data["data"]["result"]:
                    health_lines.append("SERVICE STATUS:")
                    for r in data["data"]["result"]:
                        service = r["metric"].get("service", r["metric"].get("job", "unknown"))
                        is_up = int(float(r["value"][1])) == 1
                        status = "[UP]" if is_up else "[DOWN]"
                        health_lines.append(f"  {status}: {service}")
                        if not is_up:
                            issues.append(f"Service down: {service}")
                    health_lines.append("")
        except Exception:
            pass

    # Add summary
    health_lines.append("=== SUMMARY ===")
    if issues:
        health_lines.append("ISSUES DETECTED:")
        for issue in issues:
            health_lines.append(f"  - {issue}")
    else:
        health_lines.append("All systems healthy")

    return {
        "content": [{
            "type": "text",
            "text": "\n".join(health_lines)
        }]
    }


async def get_logs(service: str, level: str = "all", lines: int = 20) -> dict[str, Any]:
    """Generate simulated log entries for a service."""
    elapsed = time.time() - START_TIME
    incident_active = elapsed > 60

    lines = min(lines, 100)  # Cap at 100

    valid_services = ["api-server", "payment-svc", "auth-svc", "postgres"]
    if service not in valid_services:
        return {
            "content": [{
                "type": "text",
                "text": f"Unknown service: {service}\nValid services: {', '.join(valid_services)}"
            }],
            "isError": True
        }

    # Generate fake timestamps going backwards from "now"
    base_time = time.time()
    log_entries = []

    # Define log patterns for healthy vs incident states
    if incident_active:
        if service == "api-server":
            error_logs = [
                ("ERROR", "pq: connection pool exhausted, max connections (100) reached"),
                ("ERROR", "context deadline exceeded waiting for DB connection"),
                ("ERROR", "handler timeout: /api/v1/users took 5.2s"),
                ("ERROR", "upstream connection refused: payment-svc:8080"),
                ("WARN", "connection pool utilization at 98%"),
                ("WARN", "request queue depth: 247 requests waiting"),
                ("ERROR", "transaction failed: could not serialize access"),
                ("ERROR", "pq: canceling statement due to statement timeout"),
            ]
            info_logs = [
                ("INFO", "GET /api/v1/health 200 12ms"),
                ("INFO", "POST /api/v1/orders 500 5023ms"),
                ("INFO", "GET /api/v1/users 500 4892ms"),
            ]
            log_patterns = error_logs * 3 + info_logs  # More errors during incident
        elif service == "payment-svc":
            error_logs = [
                ("WARN", "upstream api-server responding slowly: 2340ms"),
                ("ERROR", "timeout waiting for api-server: context deadline exceeded"),
                ("WARN", "retrying request to api-server (attempt 2/3)"),
            ]
            info_logs = [
                ("INFO", "POST /payments/process 200 89ms"),
                ("INFO", "GET /payments/status 200 34ms"),
                ("INFO", "webhook delivered to merchant callback"),
            ]
            log_patterns = error_logs + info_logs * 2
        elif service == "auth-svc":
            info_logs = [
                ("INFO", "POST /auth/token 200 23ms"),
                ("INFO", "token validated for user_id=8472"),
                ("INFO", "session refreshed for user_id=1293"),
                ("WARN", "rate limit approaching for IP 10.0.4.52"),
            ]
            log_patterns = info_logs
        else:  # postgres
            error_logs = [
                ("ERROR", "too many connections for role \"api_server\""),
                ("WARN", "connection slots remaining: 2"),
                ("ERROR", "could not fork new process: Resource temporarily unavailable"),
                ("WARN", "checkpointer process took 12.4s"),
                ("ERROR", "terminating connection due to idle timeout"),
            ]
            info_logs = [
                ("INFO", "checkpoint complete: 847 buffers written"),
                ("INFO", "automatic vacuum of table \"orders\""),
            ]
            log_patterns = error_logs * 2 + info_logs
    else:
        # Healthy state - mostly info logs
        if service == "api-server":
            log_patterns = [
                ("INFO", "GET /api/v1/health 200 8ms"),
                ("INFO", "GET /api/v1/users 200 45ms"),
                ("INFO", "POST /api/v1/orders 200 123ms"),
                ("INFO", "GET /api/v1/products 200 34ms"),
                ("DEBUG", "cache hit for user_preferences"),
                ("INFO", "background job completed: sync_inventory"),
            ]
        elif service == "payment-svc":
            log_patterns = [
                ("INFO", "POST /payments/process 200 89ms"),
                ("INFO", "GET /payments/status 200 23ms"),
                ("INFO", "refund processed for order_id=9823"),
                ("INFO", "webhook delivered successfully"),
            ]
        elif service == "auth-svc":
            log_patterns = [
                ("INFO", "POST /auth/token 200 19ms"),
                ("INFO", "POST /auth/refresh 200 12ms"),
                ("INFO", "user login: user_id=4521"),
                ("DEBUG", "token cache hit"),
            ]
        else:  # postgres
            log_patterns = [
                ("INFO", "checkpoint complete: 234 buffers written"),
                ("INFO", "automatic analyze of table \"users\""),
                ("INFO", "connection authorized: user=api_server database=production"),
                ("DEBUG", "replication lag: 0.2ms"),
            ]

    # Generate log lines
    for i in range(lines):
        timestamp = base_time - (lines - i) * random.uniform(0.5, 2.0)
        time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        level_str, message = random.choice(log_patterns)

        # Filter by level if specified
        if level != "all":
            if level == "error" and level_str not in ["ERROR"]:
                continue
            if level == "warn" and level_str not in ["ERROR", "WARN"]:
                continue
            if level == "info" and level_str not in ["ERROR", "WARN", "INFO"]:
                continue

        log_entries.append(f"[{level_str}] {time_str} {service}: {message}")

    if not log_entries:
        return {
            "content": [{
                "type": "text",
                "text": f"No {level} logs found for {service} in the requested time range."
            }]
        }

    output = f"=== Logs for {service} (last {len(log_entries)} entries) ===\n\n"
    output += "\n".join(log_entries)

    return {
        "content": [{
            "type": "text",
            "text": output
        }]
    }


async def get_alerts() -> dict[str, Any]:
    """Get currently firing alerts (simulated)."""
    elapsed = time.time() - START_TIME
    incident_active = elapsed > 60

    alerts = []

    if incident_active:
        incident_duration = int(elapsed - 60)
        alerts = [
            {
                "status": "FIRING",
                "severity": "critical",
                "name": "HighErrorRate",
                "service": "api-server",
                "description": f"Error rate is 23.4% (threshold: 5%)",
                "duration": f"{incident_duration}s",
            },
            {
                "status": "FIRING",
                "severity": "critical",
                "name": "DBConnectionPoolExhausted",
                "service": "postgres",
                "description": f"Connection pool at 98/100 (threshold: 90%)",
                "duration": f"{incident_duration}s",
            },
            {
                "status": "FIRING",
                "severity": "warning",
                "name": "HighLatencyP99",
                "service": "api-server",
                "description": f"P99 latency is 2847ms (threshold: 500ms)",
                "duration": f"{incident_duration - 5}s",
            },
            {
                "status": "PENDING",
                "severity": "warning",
                "name": "HighCPUUsage",
                "service": "api-server",
                "description": f"CPU usage is 87% (threshold: 80%)",
                "duration": "pending for 45s",
            },
        ]
    else:
        # Healthy - no alerts or just resolved ones
        alerts = [
            {
                "status": "RESOLVED",
                "severity": "info",
                "name": "HighLatencyP99",
                "service": "payment-svc",
                "description": "P99 latency returned to normal",
                "duration": "resolved 12m ago",
            },
        ]

    lines = ["=== Active Alerts ===", ""]

    firing = [a for a in alerts if a["status"] == "FIRING"]
    pending = [a for a in alerts if a["status"] == "PENDING"]
    resolved = [a for a in alerts if a["status"] == "RESOLVED"]

    if firing:
        lines.append("🔴 FIRING:")
        for alert in firing:
            lines.append(f"  [{alert['severity'].upper()}] {alert['name']} ({alert['service']})")
            lines.append(f"      {alert['description']}")
            lines.append(f"      Duration: {alert['duration']}")
            lines.append("")

    if pending:
        lines.append("🟡 PENDING:")
        for alert in pending:
            lines.append(f"  [{alert['severity'].upper()}] {alert['name']} ({alert['service']})")
            lines.append(f"      {alert['description']}")
            lines.append(f"      {alert['duration']}")
            lines.append("")

    if resolved and not firing:
        lines.append("✅ RECENTLY RESOLVED:")
        for alert in resolved:
            lines.append(f"  {alert['name']} ({alert['service']}) - {alert['duration']}")
            lines.append("")

    if not firing and not pending:
        lines.append("✅ No active alerts")

    return {
        "content": [{
            "type": "text",
            "text": "\n".join(lines)
        }]
    }


async def get_recent_deployments(service: str = None) -> dict[str, Any]:
    """Get recent deployments (simulated)."""
    elapsed = time.time() - START_TIME

    # Generate fake deployment times relative to now
    now = time.time()

    # The key deployment: api-server deployed ~62 seconds before incident
    # This correlates with the incident start time
    deployments = [
        {
            "service": "api-server",
            "timestamp": now - elapsed - 2,  # ~2 seconds before server started (so ~62s before incident)
            "commit": "a]7f3d2e",
            "author": "alice",
            "message": "Increase connection pool timeout from 5s to 30s",
            "pr": "#1847",
        },
        {
            "service": "api-server",
            "timestamp": now - 3600 * 2,  # 2 hours ago
            "commit": "b8c4a1f",
            "author": "bob",
            "message": "Add retry logic for transient DB errors",
            "pr": "#1842",
        },
        {
            "service": "payment-svc",
            "timestamp": now - 3600 * 5,  # 5 hours ago
            "commit": "c2d9e8f",
            "author": "charlie",
            "message": "Update Stripe SDK to v12.3.0",
            "pr": "#1839",
        },
        {
            "service": "auth-svc",
            "timestamp": now - 3600 * 24,  # 1 day ago
            "commit": "d4e5f6a",
            "author": "diana",
            "message": "Add rate limiting for token refresh endpoint",
            "pr": "#1821",
        },
        {
            "service": "postgres",
            "timestamp": now - 3600 * 24 * 3,  # 3 days ago
            "commit": "e5f6a7b",
            "author": "evan",
            "message": "Upgrade to PostgreSQL 15.2, tune connection settings",
            "pr": "#1798",
        },
    ]

    # Filter by service if specified
    if service:
        deployments = [d for d in deployments if d["service"] == service]
        if not deployments:
            return {
                "content": [{
                    "type": "text",
                    "text": f"No recent deployments found for service: {service}"
                }]
            }

    lines = ["=== Recent Deployments ===", ""]

    for deploy in deployments:
        # Calculate relative time
        age_seconds = now - deploy["timestamp"]
        if age_seconds < 60:
            age_str = f"{int(age_seconds)}s ago"
        elif age_seconds < 3600:
            age_str = f"{int(age_seconds / 60)}m ago"
        elif age_seconds < 86400:
            age_str = f"{int(age_seconds / 3600)}h ago"
        else:
            age_str = f"{int(age_seconds / 86400)}d ago"

        time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(deploy["timestamp"]))

        lines.append(f"📦 {deploy['service']} - {age_str}")
        lines.append(f"   Commit: {deploy['commit']} ({deploy['pr']})")
        lines.append(f"   Author: {deploy['author']}")
        lines.append(f"   Message: {deploy['message']}")
        lines.append(f"   Time: {time_str}")
        lines.append("")

    return {
        "content": [{
            "type": "text",
            "text": "\n".join(lines)
        }]
    }


# Runbook definitions based on CLAUDE.md
RUNBOOKS = {
    "database_connection_exhaustion": {
        "name": "Database Connection Exhaustion",
        "symptoms": [
            "api-server in CrashLoopBackOff or high error rate",
            "\"Connection refused\" or \"too many connections\" in logs",
            "db_connections_active near max (100)",
        ],
        "investigate": {
            "description": "Diagnose database connection pool exhaustion",
            "steps": [
                {
                    "step": 1,
                    "action": "Check current DB connection utilization",
                    "query": "db_connections_active",
                    "threshold": "> 90 indicates critical exhaustion",
                },
                {
                    "step": 2,
                    "action": "Check if connections are queuing",
                    "query": "db_connections_waiting",
                    "threshold": "> 0 indicates connection starvation",
                },
                {
                    "step": 3,
                    "action": "Identify which service is holding connections",
                    "query": "sum(rate(http_requests_total[1m])) by (service)",
                    "note": "High request rate + high connections = likely culprit",
                },
                {
                    "step": 4,
                    "action": "Check for connection leak indicators in logs",
                    "tool": "get_logs",
                    "params": {"service": "postgres", "level": "error"},
                },
                {
                    "step": 5,
                    "action": "Check recent deployments for config changes",
                    "tool": "get_recent_deployments",
                    "note": "Look for connection pool or timeout changes",
                },
            ],
        },
        "remediate": {
            "description": "Remediation steps for DB connection exhaustion",
            "immediate_actions": [
                {
                    "priority": 1,
                    "action": "Restart affected service pods",
                    "command": "kubectl rollout restart deployment/api-server -n production",
                    "effect": "Releases held connections, temporary fix",
                    "risk": "Brief service interruption during restart",
                },
                {
                    "priority": 2,
                    "action": "Scale down affected service to release connections",
                    "command": "kubectl scale deployment/api-server --replicas=1 -n production",
                    "effect": "Reduces connection pressure immediately",
                    "risk": "Reduced capacity during incident",
                },
            ],
            "long_term_fixes": [
                {
                    "action": "Review and fix connection pool configuration",
                    "details": "Check pool size, idle timeout, max lifetime settings",
                },
                {
                    "action": "Add connection pool metrics and alerts",
                    "details": "Alert at 70% utilization before hitting limits",
                },
                {
                    "action": "Implement connection retry with backoff",
                    "details": "Prevents thundering herd on recovery",
                },
            ],
            "escalation": {
                "team": "Database team",
                "channel": "#dba-oncall",
                "when": "If connections don't recover after restart, or if this recurs",
            },
        },
    },
    "high_latency_cascade": {
        "name": "High Latency Cascade",
        "symptoms": [
            "P99 latency > 1000ms on api-server",
            "Downstream services (payment-svc) also slow",
            "Error rate increasing as timeouts occur",
        ],
        "investigate": {
            "description": "Diagnose latency cascade across services",
            "steps": [
                {
                    "step": 1,
                    "action": "Check P99 latency across all services",
                    "query": "http_request_duration_milliseconds{quantile=\"0.99\"}",
                    "threshold": "> 500ms warning, > 2000ms critical",
                },
                {
                    "step": 2,
                    "action": "Identify where latency originates",
                    "query": "topk(5, http_request_duration_milliseconds{quantile=\"0.99\"})",
                    "note": "Service with highest latency is likely the source",
                },
                {
                    "step": 3,
                    "action": "Check database query times",
                    "query": "db_connections_waiting",
                    "note": "Waiting connections indicate DB bottleneck",
                },
                {
                    "step": 4,
                    "action": "Check for resource constraints",
                    "queries": [
                        "container_cpu_usage_ratio",
                        "container_memory_usage_ratio",
                    ],
                    "threshold": "CPU > 80% or Memory > 90% indicates resource pressure",
                },
                {
                    "step": 5,
                    "action": "Review error logs for timeout patterns",
                    "tool": "get_logs",
                    "params": {"service": "api-server", "level": "error"},
                },
            ],
        },
        "remediate": {
            "description": "Remediation steps for latency cascade",
            "immediate_actions": [
                {
                    "priority": 1,
                    "action": "If DB-related: Check for long-running queries",
                    "command": "SELECT * FROM pg_stat_activity WHERE state = 'active' AND query_start < now() - interval '30 seconds'",
                    "effect": "Identifies blocking queries",
                },
                {
                    "priority": 2,
                    "action": "If CPU-bound: Scale horizontally",
                    "command": "kubectl scale deployment/api-server --replicas=5 -n production",
                    "effect": "Distributes load across more pods",
                },
                {
                    "priority": 3,
                    "action": "If memory-bound: Restart to clear potential leaks",
                    "command": "kubectl rollout restart deployment/api-server -n production",
                    "effect": "Clears memory, resets connections",
                },
            ],
            "long_term_fixes": [
                {
                    "action": "Add circuit breakers between services",
                    "details": "Prevents cascade by failing fast",
                },
                {
                    "action": "Implement request timeouts at each layer",
                    "details": "Ensures requests don't hang indefinitely",
                },
                {
                    "action": "Add caching for frequently accessed data",
                    "details": "Reduces load on downstream services",
                },
            ],
            "escalation": {
                "team": "Platform team",
                "channel": "#platform-oncall",
                "when": "If latency doesn't improve after scaling, or if root cause unclear",
            },
        },
    },
    "elevated_error_rates": {
        "name": "Elevated Error Rates",
        "symptoms": [
            "http_requests_total{status=\"500\"} increasing",
            "Alerts from monitoring",
            "User complaints",
        ],
        "investigate": {
            "description": "Diagnose elevated 5xx error rates",
            "steps": [
                {
                    "step": 1,
                    "action": "Identify which service has errors",
                    "query": "sum(rate(http_requests_total{status=\"500\"}[1m])) by (service)",
                    "threshold": "> 1% warning, > 5% critical",
                },
                {
                    "step": 2,
                    "action": "Calculate error ratio percentage",
                    "query": "sum(rate(http_requests_total{status=\"500\"}[1m])) by (service) / sum(rate(http_requests_total[1m])) by (service)",
                    "note": "Shows error percentage per service",
                },
                {
                    "step": 3,
                    "action": "Check if correlated with latency",
                    "query": "http_request_duration_milliseconds{quantile=\"0.99\"}",
                    "note": "High latency + errors often indicates timeouts",
                },
                {
                    "step": 4,
                    "action": "Check for resource exhaustion",
                    "queries": [
                        "db_connections_active",
                        "container_cpu_usage_ratio",
                        "container_memory_usage_ratio",
                    ],
                },
                {
                    "step": 5,
                    "action": "Check logs for specific error messages",
                    "tool": "get_logs",
                    "params": {"service": "api-server", "level": "error"},
                },
                {
                    "step": 6,
                    "action": "Check for recent deployments",
                    "tool": "get_recent_deployments",
                    "note": "Recent changes are often the cause",
                },
            ],
        },
        "remediate": {
            "description": "Remediation depends on root cause identified above",
            "decision_tree": [
                {
                    "condition": "If caused by DB connection exhaustion",
                    "action": "Follow database_connection_exhaustion runbook",
                },
                {
                    "condition": "If caused by high latency/timeouts",
                    "action": "Follow high_latency_cascade runbook",
                },
                {
                    "condition": "If caused by recent deployment",
                    "action": "Rollback the deployment",
                    "command": "kubectl rollout undo deployment/api-server -n production",
                },
                {
                    "condition": "If caused by external dependency failure",
                    "action": "Enable circuit breaker / fallback mode",
                },
            ],
            "immediate_actions": [
                {
                    "priority": 1,
                    "action": "If recent deployment suspected, rollback immediately",
                    "command": "kubectl rollout undo deployment/<service> -n production",
                    "effect": "Reverts to last known good state",
                },
            ],
            "escalation": {
                "team": "Depends on affected service",
                "channels": {
                    "api-server": "#platform-oncall",
                    "payment-svc": "#payments-oncall",
                    "auth-svc": "#identity-oncall",
                },
                "when": "If root cause cannot be identified or errors persist after remediation",
            },
        },
    },
}


async def execute_runbook(runbook: str, phase: str) -> dict[str, Any]:
    """Execute a documented runbook for incident response."""
    if runbook not in RUNBOOKS:
        return {
            "content": [{
                "type": "text",
                "text": f"Unknown runbook: {runbook}\nAvailable runbooks: {', '.join(RUNBOOKS.keys())}"
            }],
            "isError": True
        }

    rb = RUNBOOKS[runbook]
    lines = [f"=== Runbook: {rb['name']} ===", ""]

    if phase == "investigate":
        # Show symptoms to confirm this is the right runbook
        lines.append("SYMPTOMS (confirm these match your incident):")
        for symptom in rb["symptoms"]:
            lines.append(f"  • {symptom}")
        lines.append("")

        # Show investigation steps
        inv = rb["investigate"]
        lines.append(f"INVESTIGATION: {inv['description']}")
        lines.append("")

        for step in inv["steps"]:
            lines.append(f"Step {step['step']}: {step['action']}")

            if "query" in step:
                lines.append(f"  → Run query: {step['query']}")
            if "queries" in step:
                for q in step["queries"]:
                    lines.append(f"  → Run query: {q}")
            if "tool" in step:
                lines.append(f"  → Use tool: {step['tool']}")
                if "params" in step:
                    params_str = ", ".join(f"{k}={v}" for k, v in step["params"].items())
                    lines.append(f"     with params: {params_str}")
            if "threshold" in step:
                lines.append(f"  → Threshold: {step['threshold']}")
            if "note" in step:
                lines.append(f"  → Note: {step['note']}")
            lines.append("")

        lines.append("After completing investigation, run this runbook again with phase='remediate'")

    elif phase == "remediate":
        rem = rb["remediate"]
        lines.append(f"REMEDIATION: {rem['description']}")
        lines.append("")

        # Show decision tree if present
        if "decision_tree" in rem:
            lines.append("DECISION TREE:")
            for decision in rem["decision_tree"]:
                lines.append(f"  IF: {decision['condition']}")
                lines.append(f"  THEN: {decision['action']}")
                if "command" in decision:
                    lines.append(f"       Command: {decision['command']}")
                lines.append("")

        # Show immediate actions
        if "immediate_actions" in rem:
            lines.append("IMMEDIATE ACTIONS:")
            for action in rem["immediate_actions"]:
                lines.append(f"  [{action['priority']}] {action['action']}")
                if "command" in action:
                    lines.append(f"      Command: {action['command']}")
                if "effect" in action:
                    lines.append(f"      Effect: {action['effect']}")
                if "risk" in action:
                    lines.append(f"      Risk: {action['risk']}")
                lines.append("")

        # Show long-term fixes
        if "long_term_fixes" in rem:
            lines.append("LONG-TERM FIXES (for post-incident):")
            for fix in rem["long_term_fixes"]:
                lines.append(f"  • {fix['action']}")
                lines.append(f"    {fix['details']}")
            lines.append("")

        # Show escalation info
        if "escalation" in rem:
            esc = rem["escalation"]
            lines.append("ESCALATION:")
            if "team" in esc:
                lines.append(f"  Team: {esc['team']}")
            if "channel" in esc:
                lines.append(f"  Channel: {esc['channel']}")
            if "channels" in esc:
                for svc, channel in esc["channels"].items():
                    lines.append(f"  {svc}: {channel}")
            if "when" in esc:
                lines.append(f"  When: {esc['when']}")

    return {
        "content": [{
            "type": "text",
            "text": "\n".join(lines)
        }]
    }


async def handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Route tool calls to the appropriate handler."""
    if name == "query_metrics":
        return await query_metrics(arguments.get("promql", ""))
    elif name == "list_metrics":
        return await list_metrics()
    elif name == "get_service_health":
        return await get_service_health()
    elif name == "get_logs":
        return await get_logs(
            service=arguments.get("service", ""),
            level=arguments.get("level", "all"),
            lines=arguments.get("lines", 20)
        )
    elif name == "get_alerts":
        return await get_alerts()
    elif name == "get_recent_deployments":
        return await get_recent_deployments(
            service=arguments.get("service")
        )
    elif name == "execute_runbook":
        return await execute_runbook(
            runbook=arguments.get("runbook", ""),
            phase=arguments.get("phase", "investigate")
        )
    else:
        return {
            "content": [{
                "type": "text",
                "text": f"Unknown tool: {name}"
            }],
            "isError": True
        }


def send_response(response: dict[str, Any]) -> None:
    """Send a JSON-RPC response to stdout."""
    json_str = json.dumps(response)
    sys.stdout.write(json_str + "\n")
    sys.stdout.flush()


def send_error(id: Any, code: int, message: str) -> None:
    """Send a JSON-RPC error response."""
    send_response({
        "jsonrpc": "2.0",
        "id": id,
        "error": {
            "code": code,
            "message": message
        }
    })


async def handle_request(request: dict[str, Any]) -> None:
    """Handle an incoming JSON-RPC request."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        # MCP initialization
        send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "sre-tools",
                    "version": "1.0.0"
                }
            }
        })
    elif method == "notifications/initialized":
        # No response needed for notifications
        pass
    elif method == "tools/list":
        send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": TOOLS
            }
        })
    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        result = await handle_tool_call(tool_name, arguments)
        send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result
        })
    else:
        send_error(req_id, -32601, f"Method not found: {method}")


async def main():
    """Main event loop - read JSON-RPC requests from stdin."""
    # Disable buffering for stdin
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        try:
            line = await reader.readline()
            if not line:
                break

            line = line.decode("utf-8").strip()
            if not line:
                continue

            try:
                request = json.loads(line)
                await handle_request(request)
            except json.JSONDecodeError as e:
                send_error(None, -32700, f"Parse error: {e}")

        except Exception as e:
            # Log to stderr so it doesn't interfere with JSON-RPC
            print(f"Error: {e}", file=sys.stderr)
            break


if __name__ == "__main__":
    asyncio.run(main())
