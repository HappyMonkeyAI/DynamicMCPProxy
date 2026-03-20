#!/usr/bin/env python3
"""Test runner — writes results to test_results.txt"""
import subprocess, sys

result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
    capture_output=True,
    text=True,
    cwd="/home/stephen/dynamic-mcp-proxy-server",
)
output = result.stdout + result.stderr
with open("test_results.txt", "w") as f:
    f.write(output)
    f.write(f"\n\nEXIT CODE: {result.returncode}\n")
