#!/usr/bin/env python3
"""
Healthy Services Metrics Server

Exposes Prometheus-format metrics for simulated healthy services (payment-svc, auth-svc).
These provide visual contrast against the real api-server which can have actual incidents.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import random
import time

# Counters that accumulate over time
request_counts = {
    "payment-svc": {"200": 0, "500": 0},
    "auth-svc": {"200": 0, "500": 0},
}

last_update = time.time()


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return

        global last_update

        # Update counters based on time elapsed (roughly proportional to traffic rate)
        elapsed = time.time() - last_update
        if elapsed > 0.5:  # Update every 0.5 seconds
            # Always healthy traffic
            request_counts["payment-svc"]["200"] += int(elapsed * random.randint(8, 12))
            request_counts["payment-svc"]["500"] += random.randint(0, 1) if random.random() > 0.9 else 0
            request_counts["auth-svc"]["200"] += int(elapsed * random.randint(15, 20))
            request_counts["auth-svc"]["500"] += random.randint(0, 1) if random.random() > 0.95 else 0
            last_update = time.time()

        # Healthy latency values
        payment_latency_p99 = 100 + random.randint(0, 20)
        payment_latency_p50 = 45 + random.randint(0, 15)
        auth_latency_p99 = 85 + random.randint(0, 15)
        auth_latency_p50 = 25 + random.randint(0, 10)

        metrics = f"""# HELP http_requests_total Total number of HTTP requests
# TYPE http_requests_total counter
http_requests_total{{service="payment-svc",status="200"}} {request_counts["payment-svc"]["200"]}
http_requests_total{{service="payment-svc",status="500"}} {request_counts["payment-svc"]["500"]}
http_requests_total{{service="auth-svc",status="200"}} {request_counts["auth-svc"]["200"]}
http_requests_total{{service="auth-svc",status="500"}} {request_counts["auth-svc"]["500"]}

# HELP http_request_duration_milliseconds HTTP request latency
# TYPE http_request_duration_milliseconds gauge
http_request_duration_milliseconds{{service="payment-svc",quantile="0.99"}} {payment_latency_p99}
http_request_duration_milliseconds{{service="payment-svc",quantile="0.50"}} {payment_latency_p50}
http_request_duration_milliseconds{{service="auth-svc",quantile="0.99"}} {auth_latency_p99}
http_request_duration_milliseconds{{service="auth-svc",quantile="0.50"}} {auth_latency_p50}

# HELP container_cpu_usage_ratio CPU usage ratio by container
# TYPE container_cpu_usage_ratio gauge
container_cpu_usage_ratio{{container="payment-svc",namespace="production"}} {0.3 + random.uniform(0, 0.1):.3f}
container_cpu_usage_ratio{{container="auth-svc",namespace="production"}} {0.2 + random.uniform(0, 0.1):.3f}

# HELP container_memory_usage_ratio Memory usage ratio by container
# TYPE container_memory_usage_ratio gauge
container_memory_usage_ratio{{container="payment-svc",namespace="production"}} {0.4 + random.uniform(0, 0.1):.3f}
container_memory_usage_ratio{{container="auth-svc",namespace="production"}} {0.35 + random.uniform(0, 0.1):.3f}

# HELP up Service health status
# TYPE up gauge
up{{service="payment-svc"}} 1
up{{service="auth-svc"}} 1
"""

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(metrics.encode())

    def log_message(self, format, *args):
        pass  # Suppress logs


def main():
    port = 8001
    server = HTTPServer(("", port), MetricsHandler)
    print(f"Healthy services metrics: http://localhost:{port}/metrics")
    server.serve_forever()


if __name__ == "__main__":
    main()
