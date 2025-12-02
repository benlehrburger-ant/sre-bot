#!/usr/bin/env python3
"""
Fake Metrics Server for SRE Bot Demo

Exposes Prometheus-format metrics that simulate a real incident:
- First 60 seconds: Everything healthy
- After 60 seconds: Database connection exhaustion causes API errors

Run with: python metric_logging.py
Access at: http://localhost:8000/metrics
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import random
import time
import sys

START_TIME = time.time()

# Counters that accumulate over time
request_counts = {
    "api-server": {"200": 0, "500": 0},
    "payment-svc": {"200": 0, "500": 0},
    "auth-svc": {"200": 0, "500": 0},
}


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return

        elapsed = time.time() - START_TIME
        incident_active = elapsed > 60

        # Update request counters based on current state
        if incident_active:
            # Incident: API server failing due to DB issues
            request_counts["api-server"]["200"] += random.randint(50, 80)
            request_counts["api-server"]["500"] += random.randint(30, 50)
            request_counts["payment-svc"]["200"] += random.randint(40, 60)
            request_counts["payment-svc"]["500"] += random.randint(0, 2)
            request_counts["auth-svc"]["200"] += random.randint(80, 100)
            request_counts["auth-svc"]["500"] += random.randint(0, 1)

            # Degraded metrics
            db_connections_active = 95 + random.randint(0, 5)
            db_connections_waiting = 10 + random.randint(0, 8)
            api_latency_p99 = 2500 + random.randint(0, 1000)
            api_latency_p50 = 800 + random.randint(0, 300)
            payment_latency_p99 = 120 + random.randint(0, 30)
            cpu_usage_api = 0.85 + random.uniform(0, 0.1)
            memory_usage_api = 0.78 + random.uniform(0, 0.1)
        else:
            # Healthy state
            request_counts["api-server"]["200"] += random.randint(90, 110)
            request_counts["api-server"]["500"] += random.randint(0, 2)
            request_counts["payment-svc"]["200"] += random.randint(40, 60)
            request_counts["payment-svc"]["500"] += random.randint(0, 1)
            request_counts["auth-svc"]["200"] += random.randint(80, 100)
            request_counts["auth-svc"]["500"] += random.randint(0, 1)

            # Healthy metrics
            db_connections_active = 40 + random.randint(0, 15)
            db_connections_waiting = random.randint(0, 2)
            api_latency_p99 = 150 + random.randint(0, 50)
            api_latency_p50 = 45 + random.randint(0, 20)
            payment_latency_p99 = 100 + random.randint(0, 20)
            cpu_usage_api = 0.25 + random.uniform(0, 0.1)
            memory_usage_api = 0.45 + random.uniform(0, 0.1)

        metrics = f"""# HELP http_requests_total Total number of HTTP requests
# TYPE http_requests_total counter
http_requests_total{{service="api-server",status="200"}} {request_counts["api-server"]["200"]}
http_requests_total{{service="api-server",status="500"}} {request_counts["api-server"]["500"]}
http_requests_total{{service="payment-svc",status="200"}} {request_counts["payment-svc"]["200"]}
http_requests_total{{service="payment-svc",status="500"}} {request_counts["payment-svc"]["500"]}
http_requests_total{{service="auth-svc",status="200"}} {request_counts["auth-svc"]["200"]}
http_requests_total{{service="auth-svc",status="500"}} {request_counts["auth-svc"]["500"]}

# HELP db_connections Database connection pool metrics
# TYPE db_connections gauge
db_connections_active{{pool="primary"}} {db_connections_active}
db_connections_max{{pool="primary"}} 100
db_connections_waiting{{pool="primary"}} {db_connections_waiting}

# HELP http_request_duration_milliseconds HTTP request latency
# TYPE http_request_duration_milliseconds gauge
http_request_duration_milliseconds{{service="api-server",quantile="0.99"}} {api_latency_p99}
http_request_duration_milliseconds{{service="api-server",quantile="0.50"}} {api_latency_p50}
http_request_duration_milliseconds{{service="payment-svc",quantile="0.99"}} {payment_latency_p99}
http_request_duration_milliseconds{{service="payment-svc",quantile="0.50"}} {payment_latency_p99 - 30}
http_request_duration_milliseconds{{service="auth-svc",quantile="0.99"}} {85 + random.randint(0, 15)}
http_request_duration_milliseconds{{service="auth-svc",quantile="0.50"}} {25 + random.randint(0, 10)}

# HELP container_cpu_usage_ratio CPU usage ratio by container
# TYPE container_cpu_usage_ratio gauge
container_cpu_usage_ratio{{container="api-server",namespace="production"}} {cpu_usage_api:.3f}
container_cpu_usage_ratio{{container="payment-svc",namespace="production"}} {0.3 + random.uniform(0, 0.1):.3f}
container_cpu_usage_ratio{{container="auth-svc",namespace="production"}} {0.2 + random.uniform(0, 0.1):.3f}
container_cpu_usage_ratio{{container="postgres",namespace="production"}} {0.6 + random.uniform(0, 0.15):.3f}

# HELP container_memory_usage_ratio Memory usage ratio by container
# TYPE container_memory_usage_ratio gauge
container_memory_usage_ratio{{container="api-server",namespace="production"}} {memory_usage_api:.3f}
container_memory_usage_ratio{{container="payment-svc",namespace="production"}} {0.4 + random.uniform(0, 0.1):.3f}
container_memory_usage_ratio{{container="auth-svc",namespace="production"}} {0.35 + random.uniform(0, 0.1):.3f}
container_memory_usage_ratio{{container="postgres",namespace="production"}} {0.7 + random.uniform(0, 0.1):.3f}

# HELP up Service health status
# TYPE up gauge
up{{service="api-server"}} {0 if incident_active and random.random() > 0.7 else 1}
up{{service="payment-svc"}} 1
up{{service="auth-svc"}} 1
up{{service="postgres"}} 1
"""

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(metrics.encode())

    def log_message(self, format, *args):
        # Custom logging to show incident status
        elapsed = time.time() - START_TIME
        status = "🔴 INCIDENT ACTIVE" if elapsed > 60 else f"🟢 Healthy ({60 - elapsed:.0f}s until incident)"
        print(f"[{status}] {args[0]}", file=sys.stderr)


def main():
    port = 8000
    server = HTTPServer(("", port), MetricsHandler)

    print("=" * 60)
    print("🚀 SRE Bot Demo - Fake Metrics Server")
    print("=" * 60)
    print(f"Metrics endpoint: http://localhost:{port}/metrics")
    print(f"Prometheus UI:    http://localhost:9090")
    print(f"Grafana UI:       http://localhost:3000 (admin/demo)")
    print()
    print("📊 Incident Timeline:")
    print("  • 0-60s:  All systems healthy")
    print("  • 60s+:   DB connection exhaustion → API errors spike")
    print()
    print("Press Ctrl+C to stop")
    print("=" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
