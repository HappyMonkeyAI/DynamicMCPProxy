"""
A simple FastMCP server to act as a target for integration testing.
"""
from fastmcp import FastMCP

mcp = FastMCP("Mock Target Server")

@mcp.tool()
def echo(message: str) -> str:
    """Echo the message back."""
    return f"Mock says: {message}"

@mcp.resource("mcp://mock/data")
def mock_resource() -> str:
    """Mock resource data."""
    return "This is mock data from the target server."

if __name__ == "__main__":
    # Run as SSE for integration test
    mcp.run("sse")
