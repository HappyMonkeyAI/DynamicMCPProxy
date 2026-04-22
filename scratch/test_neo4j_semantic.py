import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from src import proxy_server

async def test_neo4j_semantic():
    print("Initializing proxy...")
    proxy_server._startup()
    
    server_name = "neo4j-semantic-search"
    
    print(f"Activating {server_name}...")
    res = proxy_server.proxy_activate_server(server_name, eager=True)
    
    if '"ok": true' not in res:
        print("Failed to activate server.")
        return

    tool_name = f"{server_name}_search_knowledge_graph"
    
    print(f"Calling tool {tool_name} through proxy steering layer...")
    
    try:
        # Use mcp.call_tool to simulate a client request
        result = await proxy_server.mcp.call_tool(tool_name, {"query": "authentication", "top_k": 1})
        
        print("\n--- Steered Search Result ---")
        if hasattr(result, "content"):
            print(result.content[0].text)
        else:
            print(result)
        print("-----------------------------\n")
        
        # Check for successful search or expected error
        text = str(result)
        if "Result 1" in text or "Document:" in text:
            print("✅ Neo4j Semantic Search is working and returned results!")
        elif "... (truncated by token_budget)" in text:
            print("✅ Response Steering (token_budget) is WORKING!")
        else:
            print(f"⚠️ Search returned: {text}")
            
    except Exception as e:
        print(f"❌ Error calling tool: {e}")

if __name__ == "__main__":
    asyncio.run(test_neo4j_semantic())
