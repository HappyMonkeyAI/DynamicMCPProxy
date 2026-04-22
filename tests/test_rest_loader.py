import pytest
import json
from src.loaders.rest import RESTLoader
from fastmcp import FastMCP

@pytest.mark.asyncio
async def test_rest_loader_registration():
    config_path = "tests/mock_rest_config.json"
    loader = RESTLoader(config_path, name="mock-api")
    mcp = loader.get_mcp()
    
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    
    assert "get_post" in tool_names
    assert "create_post" in tool_names

@pytest.mark.asyncio
async def test_rest_loader_execution(monkeypatch):
    # We'll use a real public API for a simple GET test
    config_path = "tests/mock_rest_config.json"
    loader = RESTLoader(config_path, name="mock-api")
    mcp = loader.get_mcp()
    
    # JSONPlaceholder is reliable for GET /posts/1
    result = await mcp.call_tool("get_post", {"id": 1})
    data = json.loads(result.content[0].text)
    
    assert data["id"] == 1
    assert "title" in data

@pytest.mark.asyncio
async def test_rest_loader_substitution():
    # Test env var substitution in baseUrl
    monkeypatch_env = {"MOCK_BASE_URL": "https://jsonplaceholder.typicode.com"}
    import os
    orig_environ = os.environ.copy()
    os.environ.update(monkeypatch_env)
    
    try:
        config = {
            "name": "test-env",
            "baseUrl": "${MOCK_BASE_URL}",
            "tools": [{"name": "test", "path": "/posts/1"}]
        }
        with open("tests/env_test_config.json", "w") as f:
            json.dump(config, f)
            
        loader = RESTLoader("tests/env_test_config.json", name="test-env")
        mcp = loader.get_mcp()
        
        result = await mcp.call_tool("test", {})
        data = json.loads(result.content[0].text)
        assert data["id"] == 1
    finally:
        os.environ = orig_environ
        if os.path.exists("tests/env_test_config.json"):
            os.remove("tests/env_test_config.json")
