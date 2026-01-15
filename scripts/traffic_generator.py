#!/usr/bin/env python3
"""
Traffic Generator for SRE Demo

Sends continuous HTTP requests to the API server to create baseline load.
This is necessary to trigger connection pool exhaustion when DB_POOL_SIZE is too low.
"""

import asyncio
import aiohttp
import random
import logging
import os
import signal
import sys
from datetime import datetime

# Configuration
API_HOST = os.getenv("API_HOST", "api-server")
API_PORT = os.getenv("API_PORT", "8080")
REQUESTS_PER_SECOND = int(os.getenv("REQUESTS_PER_SECOND", "20"))

BASE_URL = f"http://{API_HOST}:{API_PORT}"
ENDPOINTS = ["/api/users", "/api/orders", "/api/stats"]

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Statistics
stats = {
    "total_requests": 0,
    "successful": 0,
    "failed": 0,
    "start_time": None
}

running = True


def signal_handler(sig, frame):
    global running
    logger.info("Shutting down traffic generator...")
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


async def make_request(session: aiohttp.ClientSession, endpoint: str):
    """Make a single HTTP request to the API server."""
    url = f"{BASE_URL}{endpoint}"
    stats["total_requests"] += 1

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
            if response.status == 200:
                stats["successful"] += 1
            else:
                stats["failed"] += 1
                if stats["failed"] % 10 == 1:  # Log every 10th failure
                    logger.warning(f"Request failed: {endpoint} -> {response.status}")
    except asyncio.TimeoutError:
        stats["failed"] += 1
        logger.warning(f"Request timeout: {endpoint}")
    except aiohttp.ClientError as e:
        stats["failed"] += 1
        if stats["failed"] % 10 == 1:
            logger.warning(f"Request error: {endpoint} -> {e}")
    except Exception as e:
        stats["failed"] += 1
        logger.error(f"Unexpected error: {endpoint} -> {e}")


async def print_stats():
    """Print statistics periodically."""
    while running:
        await asyncio.sleep(10)
        if stats["start_time"]:
            elapsed = (datetime.now() - stats["start_time"]).total_seconds()
            rps = stats["total_requests"] / elapsed if elapsed > 0 else 0
            success_rate = (stats["successful"] / stats["total_requests"] * 100) if stats["total_requests"] > 0 else 0

            logger.info(
                f"Stats: {stats['total_requests']} total, "
                f"{stats['successful']} success, {stats['failed']} failed, "
                f"{rps:.1f} req/s, {success_rate:.1f}% success rate"
            )


async def wait_for_api():
    """Wait for the API server to be ready."""
    logger.info(f"Waiting for API server at {BASE_URL}...")

    async with aiohttp.ClientSession() as session:
        for i in range(60):  # Wait up to 60 seconds
            try:
                async with session.get(f"{BASE_URL}/health", timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        logger.info("API server is ready!")
                        return True
            except Exception:
                pass

            await asyncio.sleep(1)
            if i % 5 == 0:
                logger.info(f"Still waiting for API server... ({i}s)")

    logger.error("API server did not become ready in time")
    return False


async def generate_traffic():
    """Main traffic generation loop."""
    global running

    if not await wait_for_api():
        return

    stats["start_time"] = datetime.now()
    delay = 1.0 / REQUESTS_PER_SECOND

    logger.info(f"Starting traffic generation: {REQUESTS_PER_SECOND} requests/second")

    # Start stats printer
    stats_task = asyncio.create_task(print_stats())

    async with aiohttp.ClientSession() as session:
        while running:
            endpoint = random.choice(ENDPOINTS)
            asyncio.create_task(make_request(session, endpoint))
            await asyncio.sleep(delay)

    stats_task.cancel()

    # Final stats
    elapsed = (datetime.now() - stats["start_time"]).total_seconds()
    logger.info(f"Final stats: {stats['total_requests']} requests in {elapsed:.1f}s")
    logger.info(f"Success: {stats['successful']}, Failed: {stats['failed']}")


if __name__ == "__main__":
    logger.info("Traffic Generator starting...")
    logger.info(f"Target: {BASE_URL}")
    logger.info(f"Rate: {REQUESTS_PER_SECOND} requests/second")

    try:
        asyncio.run(generate_traffic())
    except KeyboardInterrupt:
        logger.info("Traffic generator stopped")
