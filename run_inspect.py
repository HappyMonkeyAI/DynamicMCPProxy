#!/usr/bin/env python3
import subprocess, sys
result = subprocess.run(
    [sys.executable, "inspect_fastmcp.py"],
    capture_output=True, text=True,
    cwd="/home/stephen/dynamic-mcp-proxy-server",
)
with open("inspect_results.txt", "w") as f:
    f.write(result.stdout + result.stderr)
