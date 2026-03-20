#!/usr/bin/env python3
"""Test all unmount approaches."""
import subprocess, sys

code = """
from fastmcp import FastMCP
import asyncio

async def test_approach(label, setup_fn, remove_fn):
    m = FastMCP(name="test")
    sub1 = FastMCP(name="sub1")
    sub2 = FastMCP(name="sub2")
    @sub1.tool()
    def tool_a() -> str: return "a"
    @sub2.tool()
    def tool_b() -> str: return "b"
    m.mount(sub1, namespace="ns1")
    m.mount(sub2, namespace="ns2")
    if setup_fn:
        setup_fn(m)
    before = [t.name for t in await m.list_tools()]
    remove_fn(m)
    after = [t.name for t in await m.list_tools()]
    print(f"{label}: before={before} after={after}")

# Approach 1: pop from providers list
def remove_pop(m):
    m.providers[:] = [p for p in m.providers
                      if not (hasattr(p, '_transforms') and
                              any(getattr(t, '_prefix', None) == 'ns1' for t in p._transforms))]

# Approach 2: check _name_prefix
def remove_name_prefix(m):
    m.providers[:] = [p for p in m.providers
                      if not (hasattr(p, '_transforms') and
                              any(getattr(t, '_name_prefix', None) == 'ns1' for t in p._transforms))]

# Approach 3: check repr
def remove_repr(m):
    m.providers[:] = [p for p in m.providers
                      if not (hasattr(p, '_transforms') and
                              any(repr(t) == "Namespace('ns1')" for t in p._transforms))]

# Approach 4: check _name_prefix with underscore suffix
def remove_name_prefix_us(m):
    m.providers[:] = [p for p in m.providers
                      if not (hasattr(p, '_transforms') and
                              any(getattr(t, '_name_prefix', None) == 'ns1_' for t in p._transforms))]

# First print Namespace attrs
m0 = FastMCP(name="t0")
sub0 = FastMCP(name="s0")
@sub0.tool()
def t0() -> str: return "x"
m0.mount(sub0, namespace="ns1")
for p in m0.providers:
    if hasattr(p, '_transforms'):
        for t in p._transforms:
            print(f"Namespace._prefix={getattr(t,'_prefix',None)!r}")
            print(f"Namespace._name_prefix={getattr(t,'_name_prefix',None)!r}")

asyncio.run(test_approach("pop+_prefix", None, remove_pop))
asyncio.run(test_approach("pop+_name_prefix", None, remove_name_prefix))
asyncio.run(test_approach("pop+repr", None, remove_repr))
asyncio.run(test_approach("pop+_name_prefix_us", None, remove_name_prefix_us))
"""

result = subprocess.run(
    [sys.executable, "-c", code],
    capture_output=True, text=True,
    cwd="/home/stephen/dynamic-mcp-proxy-server",
    env={"PATH": "/home/stephen/dynamic-mcp-proxy-server/.venv/bin:/usr/bin:/bin",
         "HOME": "/home/stephen",
         "PYTHONPATH": "/home/stephen/dynamic-mcp-proxy-server"}
)
with open("inspect_results.txt", "w") as f:
    f.write(result.stdout + result.stderr)
