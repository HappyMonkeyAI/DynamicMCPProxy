import json
import subprocess
import sys
import time
import os

def test_capabilities():
    """Manual verification script for MCP handshake capabilities."""
    # Ensure src is in PYTHONPATH
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()

    # Start the proxy server in stdio mode
    proc = subprocess.Popen(
        ["uv", "run", "python", "-m", "src.proxy_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env
    )

    # Initialize request (MCP 2024-11-05 standard)
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"}
        }
    }

    try:
        # Give the server a moment to start
        time.sleep(1.0)
        
        # Send initialize
        proc.stdin.write(json.dumps(init_request) + "\n")
        proc.stdin.flush()

        # Read the first line of output
        line = proc.stdout.readline()
        if not line:
            print("❌ No response from server.")
            err = proc.stderr.read()
            if err:
                print(f"Stderr: {err}")
            return

        response = json.loads(line)
        result = response.get("result", {})
        capabilities = result.get("capabilities", {})
        prompts = capabilities.get("prompts", {})
        
        if prompts.get("listChanged") is True:
            print("✅ SUCCESS: 'listChanged' capability is present and True.")
        else:
            print("❌ FAILURE: 'listChanged' capability is missing or False.")
            print(f"Full response: {json.dumps(capabilities, indent=2)}")

    except Exception as e:
        print(f"❌ Error during test: {e}")
    finally:
        proc.terminate()

if __name__ == "__main__":
    test_capabilities()
