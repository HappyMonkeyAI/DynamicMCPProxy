import asyncio
import os
from src import proxy_server

async def test_sequential_thinking():
    print("=== Testing sequential-thinking ===")
    res = proxy_server.proxy_activate_server("sequential-thinking", eager=True)
    print("Activate Result:", res)
    
    tools_list = await proxy_server.proxy_list_tools("sequential-thinking")
    print("Tools List:", tools_list)

    tools = await proxy_server.mcp.list_tools()
    seq_tool = next((t for t in tools if "sequential" in t.name and t.name != "sequential-thinking_load"), None)

    if seq_tool:
        print("Found tool:", seq_tool.name)
        result = await proxy_server.mcp.call_tool(
            name=seq_tool.name,
            arguments={
                "thought": "This is a test thought from the proxy validation.",
                "thoughtNumber": 1,
                "totalThoughts": 1,
                "nextThoughtNeeded": False
            }
        )
        print("Result:", result)
    else:
        print("Failed to find sequential thinking tool.")

async def test_github():
    print("\n=== Testing github ===")
    res = proxy_server.proxy_activate_server("github", eager=True)
    print("Activate Result:", res)

    tools_list = await proxy_server.proxy_list_tools("github")
    print("Tools List:", tools_list)

    tools = await proxy_server.mcp.list_tools()
    # It might be named github-mcp-server or just github depending on the catalogue entry
    # Based on user.catalogue.json it is named "github-mcp-server". 
    repo_list_tool = next((t for t in tools if "list_repositories" in t.name or "list_repos" in t.name), None)

    if repo_list_tool:
        print("Found tool:", repo_list_tool.name)
        # Calling github tools might require arguments. Usually listing repos for owner is allowed
        # Let's see what args are required. Wait, we can just call it to see what comes back.
        try:
            result = await proxy_server.mcp.call_tool(name=repo_list_tool.name)
            print("Result:", result)
        except Exception as e:
            print("Failed to call github tool:", e)
    else:
        print("Failed to find github list_repositories tool.")

async def main():
    proxy_server._startup()
    await test_sequential_thinking()
    await test_github()

if __name__ == "__main__":
    asyncio.run(main())
