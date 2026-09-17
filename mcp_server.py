#!/usr/bin/env python3
"""
Alectra Green Button Energy Dashboard - MCP Server Runner (Stdio Transport)

Allows AI assistants (Antigravity, Claude Desktop, Cursor, ChatGPT) to interact with
the electricity dashboard over standard input/output (stdio).

Zero Hardcoding:
All paths and configs are read dynamically from environment variables:
- DATABASE_PATH: Path to SQLite DB (default: green_button.db)
- SCAN_FOLDER_PATH: Path to data folder (default: /app/data)
"""
import os
import sys
import asyncio

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_tools import mcp

if __name__ == "__main__":
    asyncio.run(mcp.run_stdio_async())
