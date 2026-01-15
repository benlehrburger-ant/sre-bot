"""
API Server for SRE Bot Demo

A FastAPI service that connects to PostgreSQL with a configurable connection pool.
When DB_POOL_SIZE is set too low, it causes connection pool exhaustion under load.
"""

import os
import time
import asyncio
import logging
import random
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import OperationalError, TimeoutError as SQLAlchemyTimeoutError

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration from environment
DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "demo")
DB_USER = os.getenv("DB_USER", "demo")
DB_PASSWORD = os.getenv("DB_PASSWORD", "demo")
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))
DB_POOL_TIMEOUT = float(os.getenv("DB_POOL_TIMEOUT", "5"))
SERVICE_NAME = os.getenv("SERVICE_NAME", "api-server")

# Prometheus metrics
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['service', 'method', 'endpoint', 'status']
)

REQUEST_LATENCY = Histogram(
    'http_request_duration_milliseconds',
    'HTTP request latency in milliseconds',
    ['service', 'method', 'endpoint'],
    buckets=[10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]
)

DB_CONNECTIONS_ACTIVE = Gauge(
    'db_connections_active',
    'Number of active database connections',
    ['service']
)

DB_CONNECTIONS_MAX = Gauge(
    'db_connections_max',
    'Maximum database connections in pool',
    ['service']
)

DB_POOL_SIZE_GAUGE = Gauge(
    'db_pool_size',
    'Configured database pool size',
    ['service']
)

# Database setup
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = None
SessionLocal = None

# Thread pool for running sync database code concurrently
executor = ThreadPoolExecutor(max_workers=20)


def init_database():
    """Initialize database connection with configured pool size."""
    global engine, SessionLocal

    logger.info(f"Initializing database connection pool with size={DB_POOL_SIZE}, timeout={DB_POOL_TIMEOUT}s")

    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=DB_POOL_SIZE,
        max_overflow=0,  # No extra connections beyond pool_size
        pool_timeout=DB_POOL_TIMEOUT,  # Seconds to wait for a connection
        pool_pre_ping=True,  # Verify connections before using
    )

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Update metrics
    DB_POOL_SIZE_GAUGE.labels(service=SERVICE_NAME).set(DB_POOL_SIZE)
    DB_CONNECTIONS_MAX.labels(service=SERVICE_NAME).set(DB_POOL_SIZE)

    logger.info(f"Database pool initialized: pool_size={DB_POOL_SIZE}, max_overflow=0")


def update_connection_metrics():
    """Update Prometheus metrics for database connections."""
    if engine:
        pool = engine.pool
        DB_CONNECTIONS_ACTIVE.labels(service=SERVICE_NAME).set(pool.checkedout())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info(f"Starting {SERVICE_NAME}")
    logger.info(f"DB_POOL_SIZE={DB_POOL_SIZE}")

    # Wait for database to be ready
    max_retries = 30
    for i in range(max_retries):
        try:
            init_database()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database connection successful")
            break
        except Exception as e:
            if i < max_retries - 1:
                logger.warning(f"Database not ready, retrying in 1s... ({e})")
                await asyncio.sleep(1)
            else:
                logger.error(f"Could not connect to database after {max_retries} retries")
                raise

    yield

    # Shutdown
    logger.info("Shutting down")
    if engine:
        engine.dispose()


app = FastAPI(title="SRE Demo API Server", lifespan=lifespan)


def get_db():
    """Get a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "healthy", "service": SERVICE_NAME, "db_pool_size": DB_POOL_SIZE}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Database unhealthy: {str(e)}")


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    update_connection_metrics()
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _sync_list_users():
    """Synchronous database operation for list_users."""
    with SessionLocal() as session:
        # Simulate slow query - 500ms to cause faster pool exhaustion
        session.execute(text("SELECT pg_sleep(0.5)"))
        result = session.execute(text("SELECT id, name, email FROM users LIMIT 100"))
        return [{"id": row[0], "name": row[1], "email": row[2]} for row in result]


@app.get("/api/users")
async def list_users():
    """List all users from the database."""
    start_time = time.time()
    status = "200"

    try:
        # Occasional random error for realism (~1% error rate)
        if random.random() < 0.01:
            status = "500"
            raise HTTPException(status_code=500, detail="Transient database error")

        update_connection_metrics()

        # Run sync DB code in thread pool to allow concurrent requests
        loop = asyncio.get_event_loop()
        users = await loop.run_in_executor(executor, _sync_list_users)

        return {"users": users, "count": len(users)}

    except (OperationalError, SQLAlchemyTimeoutError) as e:
        status = "500"
        error_msg = str(e)

        if "QueuePool limit" in error_msg or "TimeoutError" in error_msg:
            logger.error(f"Connection pool exhausted: {error_msg}")
            raise HTTPException(
                status_code=500,
                detail=f"Database connection pool exhausted. QueuePool limit of size {DB_POOL_SIZE} reached, connection timed out."
            )
        else:
            logger.error(f"Database error: {error_msg}")
            raise HTTPException(status_code=500, detail=f"Database error: {error_msg}")

    except Exception as e:
        status = "500"
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        duration_ms = (time.time() - start_time) * 1000
        REQUEST_COUNT.labels(service="user-svc", method="GET", endpoint="/api/users", status=status).inc()
        REQUEST_LATENCY.labels(service="user-svc", method="GET", endpoint="/api/users").observe(duration_ms)


@app.get("/api/orders")
async def list_orders():
    """List recent orders - returns cached data, mostly healthy."""
    start_time = time.time()
    status = "200"

    try:
        # Occasional random error for realism (~1% error rate)
        if random.random() < 0.01:
            status = "500"
            raise HTTPException(status_code=500, detail="Transient cache error")

        # Return mock/cached data - doesn't use database connection pool
        orders = [
            {"id": i, "user_id": i % 10 + 1, "total": round(random.uniform(10, 500), 2), "status": "completed", "user_name": f"User {i % 10 + 1}"}
            for i in range(1, 11)
        ]

        return {"orders": orders, "count": len(orders)}

    except HTTPException:
        raise

    except Exception as e:
        status = "500"
        logger.error(f"Orders endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        duration_ms = (time.time() - start_time) * 1000
        REQUEST_COUNT.labels(service="payment-svc", method="GET", endpoint="/api/orders", status=status).inc()
        REQUEST_LATENCY.labels(service="payment-svc", method="GET", endpoint="/api/orders").observe(duration_ms)


@app.get("/api/stats")
async def get_stats():
    """Get statistics - returns cached data, mostly healthy."""
    start_time = time.time()
    status = "200"

    try:
        # Occasional random error for realism (~1% error rate)
        if random.random() < 0.01:
            status = "500"
            raise HTTPException(status_code=500, detail="Transient cache error")

        # Return mock/cached data - doesn't use database connection pool
        return {
            "users_count": 1000 + random.randint(0, 50),
            "orders_count": 5000 + random.randint(0, 100),
            "total_revenue": round(random.uniform(50000, 55000), 2),
            "db_pool": {
                "size": DB_POOL_SIZE,
                "checked_out": 0,
                "overflow": 0,
            }
        }

    except HTTPException:
        raise

    except Exception as e:
        status = "500"
        logger.error(f"Stats endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        duration_ms = (time.time() - start_time) * 1000
        REQUEST_COUNT.labels(service="auth-svc", method="GET", endpoint="/api/stats", status=status).inc()
        REQUEST_LATENCY.labels(service="auth-svc", method="GET", endpoint="/api/stats").observe(duration_ms)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": SERVICE_NAME,
        "endpoints": ["/health", "/metrics", "/api/users", "/api/orders", "/api/stats"],
        "config": {
            "db_pool_size": DB_POOL_SIZE,
            "db_pool_timeout": DB_POOL_TIMEOUT,
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
