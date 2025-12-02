#!/usr/bin/env python3
"""
SRE Bot - Slack Integration with Claude Agent SDK

This version integrates with Slack for real-time incident response.
It uses the Claude Agent SDK with in-process MCP tools.

Configuration:
    Create a .env file with:
        ANTHROPIC_API_KEY=your-anthropic-key
        SLACK_BOT_TOKEN=xoxb-your-bot-token
        SLACK_APP_TOKEN=xapp-your-app-token

Usage:
    python sre_bot_slack.py
"""

import asyncio
import os
import sys
import re
from pathlib import Path

# Path to our subprocess MCP server
MCP_SERVER_PATH = Path(__file__).parent / "sre_mcp_server.py"

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    load_dotenv(env_path)
except ImportError:
    print("⚠️  python-dotenv not installed, using environment variables only")
    print("   Run: pip install python-dotenv")

# Check Slack dependency
try:
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
except ImportError:
    print("❌ slack-bolt not installed")
    print("   Run: pip install slack-bolt")
    sys.exit(1)

# Check Claude Agent SDK
try:
    from claude_agent_sdk import (
        query,
        ClaudeAgentOptions,
        AssistantMessage,
        TextBlock,
        ToolUseBlock,
        ResultMessage,
    )
except ImportError:
    print("❌ claude-agent-sdk not installed")
    print("   Run: pip install claude-agent-sdk")
    print("")
    print("   Note: The SDK also requires Claude Code CLI:")
    print("   npm install -g @anthropic-ai/claude-code")
    sys.exit(1)

# Validate environment variables
missing_vars = []
for var in ["ANTHROPIC_API_KEY", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"]:
    if not os.environ.get(var):
        missing_vars.append(var)

if missing_vars:
    print("❌ Missing required configuration:")
    for var in missing_vars:
        print(f"   - {var}")
    print("")
    print("   Create a .env file in this directory with:")
    print("       ANTHROPIC_API_KEY=your-anthropic-key")
    print("       SLACK_BOT_TOKEN=xoxb-your-bot-token")
    print("       SLACK_APP_TOKEN=xapp-your-app-token")
    sys.exit(1)


# Initialize Slack app
app = AsyncApp(token=os.environ["SLACK_BOT_TOKEN"])

SYSTEM_PROMPT = """You are an expert SRE incident response bot deployed in Slack. Your job is to investigate production incidents quickly and thoroughly.

## Your Investigation Approach

1. Start with get_service_health - Get a quick overview of all services
2. Drill into error rates - Check which services have elevated errors
3. Check latency - High latency often precedes errors
4. Investigate resources - Check DB connections, CPU, memory
5. Correlate and conclude - Connect symptoms to root cause

## Available Tools

- mcp__sre__get_service_health: Quick health summary across all services
- mcp__sre__query_metrics: Run any PromQL query against Prometheus
- mcp__sre__list_metrics: Discover available metric names
- mcp__sre__get_logs: Fetch recent application logs from services
- mcp__sre__get_alerts: Get currently firing alerts from AlertManager
- mcp__sre__get_recent_deployments: List recent deployments to correlate with incidents

## Your Capabilities

You have full access to remediate issues, including:
- Database management (connection pools, kill queries, tune settings)
- Kubernetes/infrastructure (restart pods, scale deployments, adjust resources)
- Core monorepo (deploy hotfixes, rollback changes, feature flags)
- Configuration management (update env vars, secrets, limits)

## Communication Style

You're posting to a Slack incident channel. Be:
- Concise: Focus on key findings
- Clear: Use specific numbers and service names
- Visual: Use emoji for quick scanning (🔴 🟢 ⚠️ ✅)
- Actionable: Offer to take immediate action

## CRITICAL: Output Structure

Structure your response as SEPARATE messages (do not combine these into one message):

1. *Investigation findings* - What you discovered from the tools
2. *Root Cause Analysis* - Your diagnosis of what's causing the issue
3. *Recommended Actions* - What needs to be done to fix it
4. *Offer to Remediate* - End by offering to take specific actions immediately. For example:
   - "I can restart the api-server pods now to release hung connections. Reply *yes* to proceed."
   - "I can increase the DB connection pool from 100 to 150 and deploy. Reply *yes* to proceed."
   - "I can roll back the last deployment (commit abc123). Reply *yes* to proceed."

Always offer concrete actions you can take, not just recommendations for the team.

## CRITICAL: Slack Formatting Rules

You MUST use Slack's mrkdwn format, NOT standard Markdown:
- Bold: Use *bold* (single asterisks), NOT **bold**
- Italic: Use _italic_ (underscores)
- Strikethrough: Use ~strikethrough~
- Code: Use `code` for inline, ```code``` for blocks
- Links: Use <URL|text>
- NO HEADERS: Slack does not support # headers. Use *Bold Text* on its own line instead.
- Lists: Use bullet points (•) or dashes (-) or numbers (1.)

Be thorough but efficient. Always explain your reasoning.
"""


def convert_markdown_to_slack(text: str) -> str:
    """Convert standard Markdown to Slack mrkdwn format."""
    # Remove ### headers - replace with bold text
    text = re.sub(r'^###\s*(.+)$', r'*\1*', text, flags=re.MULTILINE)
    text = re.sub(r'^##\s*(.+)$', r'*\1*', text, flags=re.MULTILINE)
    text = re.sub(r'^#\s*(.+)$', r'*\1*', text, flags=re.MULTILINE)

    # Convert **bold** to *bold* (but not inside code blocks)
    # This is a simplified conversion - handles most cases
    text = re.sub(r'\*\*([^*]+)\*\*', r'*\1*', text)

    return text


async def process_investigation(incident_text: str, channel: str, thread_ts: str, say):
    """Process the investigation in the background, streaming output to Slack."""
    # Get the Python executable path (use the venv python)
    python_path = sys.executable

    # Configure the agent with subprocess-based MCP server
    # This avoids the SDK MCP race condition bug
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={
            "sre": {
                "command": python_path,
                "args": [str(MCP_SERVER_PATH)],
            }
        },
        allowed_tools=[
            "mcp__sre__query_metrics",
            "mcp__sre__list_metrics",
            "mcp__sre__get_service_health",
            "mcp__sre__get_logs",
            "mcp__sre__get_alerts",
            "mcp__sre__get_recent_deployments",
        ],
        permission_mode="acceptEdits",
    )

    # Stream responses to Slack as they arrive
    # Track last tool to avoid duplicate "Checking X..." messages
    last_tool_posted = None
    # Track if we've transitioned from tool use to analysis
    was_using_tools = False
    analysis_announced = False

    try:
        async for message in query(prompt=incident_text, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        # Post text blocks immediately as they arrive
                        # Convert any standard Markdown to Slack mrkdwn format
                        text = convert_markdown_to_slack(block.text.strip())

                        # Detect transition from tool use to analysis/summary
                        if was_using_tools and not analysis_announced:
                            await say(text="🧠 *Analyzing findings...*", thread_ts=thread_ts)
                            await asyncio.sleep(0.3)
                            analysis_announced = True

                        # Reset tool tracking when we get actual content
                        last_tool_posted = None
                        # Split long messages to respect Slack's 4000 char limit
                        if len(text) > 3900:
                            chunks = [text[i:i+3900] for i in range(0, len(text), 3900)]
                            for chunk in chunks:
                                await say(text=chunk, thread_ts=thread_ts)
                                await asyncio.sleep(0.3)
                        else:
                            await say(text=text, thread_ts=thread_ts)
                            await asyncio.sleep(0.3)
                    elif isinstance(block, ToolUseBlock):
                        # Show which tool is being used, but skip consecutive duplicates
                        tool_name = block.name.replace("mcp__sre__", "")
                        if tool_name != last_tool_posted:
                            await say(text=f"🔧 *Checking {tool_name}...*", thread_ts=thread_ts)
                            await asyncio.sleep(0.2)
                            last_tool_posted = tool_name
                        was_using_tools = True
            elif isinstance(message, ResultMessage):
                if message.is_error:
                    await say(text=f"❌ Investigation error: {message.result}", thread_ts=thread_ts)
                else:
                    # Show completion with stats
                    duration_sec = message.duration_ms / 1000 if message.duration_ms else 0
                    await say(text=f"✅ Investigation complete ({duration_sec:.1f}s)", thread_ts=thread_ts)

    except Exception as e:
        await say(text=f"❌ Investigation failed: {str(e)}", thread_ts=thread_ts)
        raise


@app.event("app_mention")
async def handle_mention(event, say, client):
    """Handle @mentions in Slack channels."""

    channel = event["channel"]
    thread_ts = event.get("thread_ts", event["ts"])
    incident_text = event["text"]

    # Remove the bot mention from the text
    incident_text = re.sub(r"<@[A-Z0-9]+>\s*", "", incident_text).strip()

    if not incident_text:
        await say(
            text="👋 I'm the SRE bot! Mention me with an incident description and I'll investigate.\n\nExample: `@SRE Bot API errors are spiking`",
            thread_ts=thread_ts
        )
        return

    # Acknowledge the request
    await say(text="🔍 Starting investigation...", thread_ts=thread_ts)

    # Schedule the investigation as a background task so handler returns quickly
    asyncio.create_task(process_investigation(incident_text, channel, thread_ts, say))


@app.event("message")
async def handle_message(event, say):
    """Handle direct messages to the bot."""
    # Only respond to DMs (channel starts with D)
    if not event.get("channel", "").startswith("D"):
        return
    
    # Ignore bot messages
    if event.get("bot_id"):
        return
    
    text = event.get("text", "").strip()
    if text:
        # Treat DMs as incident investigations
        await handle_mention(
            {"channel": event["channel"], "ts": event["ts"], "text": text, "user": event.get("user")},
            say,
            None
        )


async def main():
    """Start the Slack bot."""
    print("=" * 50)
    print("🤖 SRE Bot - Slack Mode (Claude Agent SDK)")
    print("=" * 50)
    print("Bot is starting...")
    print("Mention @SRE Bot in any channel to investigate")
    print("Press Ctrl+C to stop")
    print("=" * 50)
    
    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
