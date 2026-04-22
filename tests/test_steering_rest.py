import pytest
import json
from src.proxy_server import _apply_steering
from src.config import ProxyEntry
from mcp.types import TextContent, CallToolResult

class MockResult:
    def __init__(self, text):
        self.content = [TextContent(type="text", text=text)]

def test_apply_steering_pick():
    entry = ProxyEntry(name="test", url="test://", pick=["name", "age"])
    data = {"name": "Alice", "age": 30, "secret": "password"}
    result = MockResult(json.dumps(data))
    
    steered = _apply_steering(result, entry)
    final_data = json.loads(steered.content[0].text)
    
    assert "name" in final_data
    assert "age" in final_data
    assert "secret" not in final_data
    assert final_data["name"] == "Alice"

def test_apply_steering_omit():
    entry = ProxyEntry(name="test", url="test://", omit=["secret"])
    data = {"name": "Alice", "secret": "password"}
    result = MockResult(json.dumps(data))
    
    steered = _apply_steering(result, entry)
    final_data = json.loads(steered.content[0].text)
    
    assert "name" in final_data
    assert "secret" not in final_data

def test_apply_steering_template():
    entry = ProxyEntry(name="test", url="test://", template="User: {name}, Age: {age}")
    data = {"name": "Alice", "age": 30}
    result = MockResult(json.dumps(data))
    
    steered = _apply_steering(result, entry)
    assert steered.content[0].text == "User: Alice, Age: 30"

def test_apply_steering_token_budget():
    entry = ProxyEntry(name="test", url="test://", token_budget=5) # ~20 chars
    text = "This is a very long text that should be truncated by the token budget logic."
    result = MockResult(text) # Not JSON, should still truncate
    
    steered = _apply_steering(result, entry)
    assert "truncated" in steered.content[0].text
    # max_chars = 5 * 4 = 20
    assert len(steered.content[0].text.split("\n")[0]) <= 20

def test_apply_steering_nested_pick():
    entry = ProxyEntry(name="test", url="test://", pick=["user.name", "user.id"])
    data = {"user": {"name": "Alice", "id": 123}, "meta": "data"}
    result = MockResult(json.dumps(data))
    
    steered = _apply_steering(result, entry)
    final_data = json.loads(steered.content[0].text)
    
    # Note: our _get_nested implementation for pick currently puts the 
    # nested value at the top level of the picked dict.
    # e.g. {"user.name": "Alice", "user.id": 123}
    assert final_data["user.name"] == "Alice"
    assert final_data["user.id"] == 123
    assert "meta" not in final_data
